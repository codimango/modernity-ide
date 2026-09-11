#!/usr/bin/env python3
"""Render deterministic multi-view evidence for the semantic Nian model."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from img2blockbench import build_texture, exported_cube_bounds, face_uv, read_json
from photo_reconstruction import _cube_point, _fidelity_metrics, _silhouette_metrics


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "benchmarks" / "references" / "04-nian.jpg"
OUTPUT = CYCLE / "render"

FACE_VERTICES = {
    "north": (1, 0, 3, 2),
    "east": (5, 1, 2, 6),
    "south": (4, 5, 6, 7),
    "west": (0, 4, 7, 3),
    "up": (7, 6, 2, 3),
    "down": (0, 1, 5, 4),
}

VIEWS = {
    # The reference shows the near flank with a modest face/top contribution.
    # Keep this source-matched vector fixed; geometry, not camera warping,
    # must account for silhouette changes between revisions.
    "reference_angle": (-1.0, 0.32, 0.60),
    "front": (0.0, 0.04, 1.0),
    "back": (0.0, 0.04, -1.0),
    "left": (1.0, 0.06, 0.0),
    "right": (-1.0, 0.06, 0.0),
    "profile": (-1.0, 0.0, 0.0),
    "top": (0.0, 1.0, 0.001),
    "isometric": (1.0, 0.58, 1.0),
}


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Load a stable UI font where available."""
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if bold
        else Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def cube_vertices(spec: dict[str, Any], cube: dict[str, Any]) -> np.ndarray:
    """Return compiler-convention world corners for one rotated cuboid."""
    minimum, maximum = exported_cube_bounds(spec, cube)
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    return np.asarray(
        [
            _cube_point(cube, x0, y0, z0),
            _cube_point(cube, x1, y0, z0),
            _cube_point(cube, x1, y1, z0),
            _cube_point(cube, x0, y1, z0),
            _cube_point(cube, x0, y0, z1),
            _cube_point(cube, x1, y0, z1),
            _cube_point(cube, x1, y1, z1),
            _cube_point(cube, x0, y1, z1),
        ],
        dtype=np.float64,
    )


def camera_basis(direction: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create an orthographic right/up/view basis."""
    view = np.asarray(direction, dtype=np.float64)
    view /= np.linalg.norm(view)
    world_up = np.asarray((0.0, 1.0, 0.0))
    if abs(float(np.dot(view, world_up))) > 0.96:
        world_up = np.asarray((0.0, 0.0, -1.0))
    right = np.cross(world_up, view)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    up /= np.linalg.norm(up)
    return right, up, view


def raster_triangle(
    canvas: np.ndarray,
    zbuffer: np.ndarray,
    points: np.ndarray,
    depths: np.ndarray,
    texture_uv: np.ndarray,
    atlas: np.ndarray,
    brightness: float,
) -> None:
    """Rasterize one textured orthographic triangle with a depth buffer."""
    minimum_x = max(0, math.floor(float(points[:, 0].min())))
    maximum_x = min(canvas.shape[1] - 1, math.ceil(float(points[:, 0].max())))
    minimum_y = max(0, math.floor(float(points[:, 1].min())))
    maximum_y = min(canvas.shape[0] - 1, math.ceil(float(points[:, 1].max())))
    if maximum_x < minimum_x or maximum_y < minimum_y:
        return
    denominator = (
        (points[1, 1] - points[2, 1]) * (points[0, 0] - points[2, 0])
        + (points[2, 0] - points[1, 0]) * (points[0, 1] - points[2, 1])
    )
    if abs(float(denominator)) < 1e-9:
        return
    grid_x, grid_y = np.meshgrid(
        np.arange(minimum_x, maximum_x + 1, dtype=np.float64) + 0.5,
        np.arange(minimum_y, maximum_y + 1, dtype=np.float64) + 0.5,
    )
    weight_a = (
        (points[1, 1] - points[2, 1]) * (grid_x - points[2, 0])
        + (points[2, 0] - points[1, 0]) * (grid_y - points[2, 1])
    ) / denominator
    weight_b = (
        (points[2, 1] - points[0, 1]) * (grid_x - points[2, 0])
        + (points[0, 0] - points[2, 0]) * (grid_y - points[2, 1])
    ) / denominator
    weight_c = 1.0 - weight_a - weight_b
    inside = (weight_a >= -1e-7) & (weight_b >= -1e-7) & (weight_c >= -1e-7)
    if not inside.any():
        return
    depth = weight_a * depths[0] + weight_b * depths[1] + weight_c * depths[2]
    target_depth = zbuffer[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    visible = inside & (depth > target_depth)
    if not visible.any():
        return
    uv = (
        weight_a[:, :, None] * texture_uv[0]
        + weight_b[:, :, None] * texture_uv[1]
        + weight_c[:, :, None] * texture_uv[2]
    )
    texture_x = np.clip(np.rint(uv[:, :, 0]), 0, atlas.shape[1] - 1).astype(np.int64)
    texture_y = np.clip(np.rint(uv[:, :, 1]), 0, atlas.shape[0] - 1).astype(np.int64)
    sampled = atlas[texture_y, texture_x].copy()
    sampled[:, :, :3] = np.clip(
        np.rint(sampled[:, :, :3].astype(np.float64) * brightness),
        0,
        255,
    ).astype(np.uint8)
    visible &= sampled[:, :, 3] >= 16
    target = canvas[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    target[visible] = sampled[visible]
    target_depth[visible] = depth[visible]


def render_view(
    spec: dict[str, Any],
    atlas_image: Image.Image,
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
    direction: tuple[float, float, float],
    *,
    selected_names: set[str] | None = None,
    size: tuple[int, int] = (640, 640),
) -> Image.Image:
    """Render selected native cuboids from one orthographic camera."""
    cubes = [
        cube
        for cube in spec["cubes"]
        if selected_names is None or cube["name"] in selected_names
    ]
    right, up, view = camera_basis(direction)
    all_vertices = np.concatenate([cube_vertices(spec, cube) for cube in cubes])
    projected = np.column_stack((all_vertices @ right, all_vertices @ up))
    lower = projected.min(axis=0)
    upper = projected.max(axis=0)
    margin = 42
    scale = min(
        (size[0] - margin * 2) / max(1e-6, upper[0] - lower[0]),
        (size[1] - margin * 2) / max(1e-6, upper[1] - lower[1]),
    )
    center = (lower + upper) / 2
    atlas = np.asarray(atlas_image.convert("RGBA"), dtype=np.uint8)
    canvas = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    canvas[:, :, :] = (13, 20, 28, 255)
    zbuffer = np.full((size[1], size[0]), -np.inf, dtype=np.float64)
    light = np.asarray((0.35, 0.8, 0.48), dtype=np.float64)
    light /= np.linalg.norm(light)

    for cube in cubes:
        vertices = cube_vertices(spec, cube)
        screen = np.column_stack((vertices @ right, vertices @ up))
        screen[:, 0] = (screen[:, 0] - center[0]) * scale + size[0] / 2
        screen[:, 1] = size[1] / 2 - (screen[:, 1] - center[1]) * scale
        depths = vertices @ view
        for face_name, indexes in FACE_VERTICES.items():
            face_vertices = vertices[list(indexes)]
            normal = np.cross(
                face_vertices[1] - face_vertices[0],
                face_vertices[2] - face_vertices[0],
            )
            length = np.linalg.norm(normal)
            if length <= 1e-12:
                continue
            normal /= length
            if float(np.dot(normal, view)) <= 1e-7:
                continue
            placement = placements[(cube["name"], face_name)]
            left, top, width, height = placement
            first_u, first_v, second_u, second_v = face_uv(
                cube, face_name, placement
            )
            uv = np.asarray(
                (
                    (first_u, second_v),
                    (second_u, second_v),
                    (second_u, first_v),
                    (first_u, first_v),
                ),
                dtype=np.float64,
            )
            brightness = 0.72 + 0.32 * max(0.0, float(np.dot(normal, light)))
            for triangle in ((0, 1, 2), (0, 2, 3)):
                triangle_indexes = list(triangle)
                raster_triangle(
                    canvas,
                    zbuffer,
                    screen[list(indexes)][triangle_indexes],
                    depths[list(indexes)][triangle_indexes],
                    uv[triangle_indexes],
                    atlas,
                    brightness,
                )
    return Image.fromarray(canvas, mode="RGBA")


def world_bounds(
    spec: dict[str, Any], cube: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    """Return an axis-aligned world bound for attachment evidence."""
    vertices = cube_vertices(spec, cube)
    return vertices.min(axis=0), vertices.max(axis=0)


def aabb_gap(
    spec: dict[str, Any],
    left: dict[str, Any],
    right: dict[str, Any],
) -> float:
    """Measure shortest separation between two rotated-cuboid world AABBs."""
    left_minimum, left_maximum = world_bounds(spec, left)
    right_minimum, right_maximum = world_bounds(spec, right)
    separation = np.maximum(
        0,
        np.maximum(left_minimum - right_maximum, right_minimum - left_maximum),
    )
    return float(np.linalg.norm(separation))


def aabb_axis_overlap(
    spec: dict[str, Any],
    left: dict[str, Any],
    right: dict[str, Any],
) -> list[float]:
    """Measure signed overlap on each world AABB axis; positive means penetration."""
    left_minimum, left_maximum = world_bounds(spec, left)
    right_minimum, right_maximum = world_bounds(spec, right)
    overlap = np.minimum(left_maximum, right_maximum) - np.maximum(
        left_minimum, right_minimum
    )
    return [round(float(value), 6) for value in overlap]


def make_sheet(reference: Image.Image, views: dict[str, Image.Image]) -> Image.Image:
    """Compose the reference and required model views."""
    tile = (300, 250)
    header = 38
    columns = 4
    rows = math.ceil((len(views) + 1) / columns)
    sheet = Image.new(
        "RGB",
        (tile[0] * columns, (tile[1] + header) * rows),
        "#09111a",
    )
    entries = [("reference", reference.convert("RGBA")), *views.items()]
    for index, (name, image) in enumerate(entries):
        x = index % columns * tile[0]
        y = index // columns * (tile[1] + header)
        fitted = image.copy()
        fitted.thumbnail(tile, Image.Resampling.LANCZOS)
        panel = Image.new("RGBA", tile, "#0d141c")
        panel.alpha_composite(
            fitted,
            ((tile[0] - fitted.width) // 2, (tile[1] - fitted.height) // 2),
        )
        sheet.paste(panel.convert("RGB"), (x, y + header))
        ImageDraw.Draw(sheet).text(
            (x + 12, y + 10),
            name.upper().replace("_", " "),
            fill="#f0bd31",
            font=font(17, bold=True),
        )
    return sheet


def foreground_mask(image: Image.Image) -> Image.Image:
    """Extract the deterministic renderer foreground from its solid backdrop."""
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
    mask = np.any(pixels != np.asarray((13, 20, 28), dtype=np.uint8), axis=2)
    return Image.fromarray((mask.astype(np.uint8) * 255), mode="L")


def align_semantic_profile(
    reference: Image.Image,
    profile: Image.Image,
    expected_mask: Image.Image,
) -> tuple[Image.Image, dict[str, Any]]:
    """Uniformly align the real semantic side render to the reference mask."""
    model_mask = foreground_mask(profile)
    model_bbox = model_mask.getbbox()
    expected_bbox = expected_mask.getbbox()
    if model_bbox is None or expected_bbox is None:
        raise ValueError("profile alignment requires non-empty masks")
    cropped_image = profile.crop(model_bbox).convert("RGBA")
    cropped_mask = model_mask.crop(model_bbox)
    cropped_image.putalpha(cropped_mask)
    expected_values = np.asarray(expected_mask, dtype=np.uint8) >= 128
    expected_width = expected_bbox[2] - expected_bbox[0]
    expected_height = expected_bbox[3] - expected_bbox[1]
    base_scale = min(
        expected_width / cropped_image.width,
        expected_height / cropped_image.height,
    )
    expected_center = (
        (expected_bbox[0] + expected_bbox[2]) / 2,
        (expected_bbox[1] + expected_bbox[3]) / 2,
    )
    best: tuple[float, float, int, int, int, int] | None = None
    for scale_step in range(85, 116):
        scale = base_scale * scale_step / 100
        width = max(1, round(cropped_image.width * scale))
        height = max(1, round(cropped_image.height * scale))
        resized_mask = np.asarray(
            cropped_mask.resize((width, height), Image.Resampling.NEAREST),
            dtype=np.uint8,
        ) >= 128
        for offset_y in range(-18, 19, 3):
            for offset_x in range(-18, 19, 3):
                left = round(expected_center[0] - width / 2 + offset_x)
                top = round(expected_center[1] - height / 2 + offset_y)
                right = min(expected_values.shape[1], left + width)
                bottom = min(expected_values.shape[0], top + height)
                source_left = max(0, -left)
                source_top = max(0, -top)
                destination_left = max(0, left)
                destination_top = max(0, top)
                if right <= destination_left or bottom <= destination_top:
                    continue
                candidate = np.zeros_like(expected_values)
                candidate[destination_top:bottom, destination_left:right] = resized_mask[
                    source_top : source_top + bottom - destination_top,
                    source_left : source_left + right - destination_left,
                ]
                intersection = int(np.count_nonzero(candidate & expected_values))
                union = int(np.count_nonzero(candidate | expected_values))
                iou = intersection / union if union else 1.0
                score = (iou, -abs(offset_x) - abs(offset_y), left, top, width, height)
                if best is None or score > best:
                    best = score
    if best is None:
        raise ValueError("could not align semantic profile")
    iou, _, left, top, width, height = best
    resized = cropped_image.resize((width, height), Image.Resampling.NEAREST)
    output = Image.new("RGBA", reference.size, (0, 0, 0, 0))
    output.alpha_composite(resized, (left, top))
    metrics = _fidelity_metrics(reference, output)
    metrics.update(_silhouette_metrics(expected_mask, output.getchannel("A")))
    metrics["alignment"] = {
        "method": "uniform-scale-translation-grid-search-no-warp",
        "scale": round(width / cropped_image.width, 6),
        "offset": [left, top],
        "aligned_iou_objective": round(iou, 6),
    }
    return output, metrics


def bilateral_metrics(first: Image.Image, second: Image.Image) -> dict[str, float]:
    """Measure mirrored side-to-side silhouette and overlapping color agreement."""
    first = first.convert("RGB")
    second = ImageOps.mirror(second.convert("RGB"))
    first_mask = np.asarray(foreground_mask(first), dtype=np.uint8) >= 128
    second_mask = np.asarray(foreground_mask(second), dtype=np.uint8) >= 128
    intersection = first_mask & second_mask
    union = first_mask | second_mask
    first_pixels = np.asarray(first, dtype=np.int16)
    second_pixels = np.asarray(second, dtype=np.int16)
    mae = (
        float(np.abs(first_pixels[intersection] - second_pixels[intersection]).mean())
        if intersection.any()
        else 255.0
    )
    return {
        "silhouette_iou": round(
            float(np.count_nonzero(intersection) / max(1, np.count_nonzero(union))),
            6,
        ),
        "overlap_rgb_mae": round(mae, 4),
    }


def silhouette_overlap_image(
    expected_mask: Image.Image, rendered_mask: Image.Image
) -> Image.Image:
    """Visualize semantic/reference silhouette agreement without hiding misses."""
    expected = np.asarray(expected_mask, dtype=np.uint8) >= 128
    rendered = np.asarray(rendered_mask, dtype=np.uint8) >= 128
    canvas = np.zeros((expected.shape[0], expected.shape[1], 3), dtype=np.uint8)
    canvas[expected & rendered] = (82, 205, 105)
    canvas[expected & ~rendered] = (231, 82, 82)
    canvas[~expected & rendered] = (76, 142, 230)
    return Image.fromarray(canvas, mode="RGB")


def main() -> None:
    """Render all review views and write objective attachment diagnostics."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    views: dict[str, Image.Image] = {}
    for name, direction in VIEWS.items():
        views[name] = render_view(spec, atlas, placements, direction)
        views[name].save(OUTPUT / f"{name}.png", optimize=True)

    head_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["bone"].startswith("horn_")
        or cube["bone"] in {"head", "jaw", "neck"}
        or cube["name"].startswith("mane_")
    }
    views["head_near"] = render_view(
        spec,
        atlas,
        placements,
        (-1.0, 0.18, 0.65),
        selected_names=head_names,
    )
    views["head_near"].save(OUTPUT / "head-near.png", optimize=True)
    views["head_far"] = render_view(
        spec,
        atlas,
        placements,
        (1.0, 0.18, 0.65),
        selected_names=head_names,
    )
    views["head_far"].save(OUTPUT / "head-far.png", optimize=True)

    joint_names = {
        "shoulder_mass",
        "front_near_upper",
        "front_near_lower",
        "front_near_paw",
        "front_near_claw_1",
        "front_near_claw_2",
    }
    joint = render_view(
        spec,
        atlas,
        placements,
        (-1.0, 0.35, 0.45),
        selected_names=joint_names,
    )
    joint.save(OUTPUT / "joint-closeup.png", optimize=True)

    rear_joint_names = {
        "pelvis_mass",
        "rear_near_upper",
        "rear_near_lower",
        "rear_near_paw",
        "rear_near_claw_1",
        "rear_near_claw_2",
    }
    rear_joint_source = render_view(
        spec,
        atlas,
        placements,
        VIEWS["reference_angle"],
        selected_names=rear_joint_names,
    )
    rear_joint_source.save(OUTPUT / "rear-joint-source.png", optimize=True)
    rear_joint_profile = render_view(
        spec,
        atlas,
        placements,
        VIEWS["profile"],
        selected_names=rear_joint_names,
    )
    rear_joint_profile.save(OUTPUT / "rear-joint-profile.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGB")
    with Image.open(CYCLE / "inputs" / "foreground-mask.png") as opened:
        expected_mask = opened.convert("L")
    reprojection, profile_fidelity = align_semantic_profile(
        reference,
        views["profile"],
        expected_mask,
    )
    reprojection.save(OUTPUT / "semantic-profile-reprojection.png", optimize=True)
    silhouette_overlap_image(
        expected_mask, reprojection.getchannel("A")
    ).save(OUTPUT / "semantic-profile-overlap.png", optimize=True)
    reference_reprojection, reference_view_fidelity = align_semantic_profile(
        reference,
        views["reference_angle"],
        expected_mask,
    )
    reference_reprojection.save(
        OUTPUT / "semantic-reference-reprojection.png", optimize=True
    )
    silhouette_overlap_image(
        expected_mask, reference_reprojection.getchannel("A")
    ).save(OUTPUT / "semantic-reference-overlap.png", optimize=True)
    sheet_views = {
        "reference angle": views["reference_angle"],
        "true profile": views["profile"],
        "right": views["right"],
        "left": views["left"],
        "front": views["front"],
        "back": views["back"],
        "isometric": views["isometric"],
        "top": views["top"],
        "head near": views["head_near"],
        "head far": views["head_far"],
        "front joint": joint,
        "rear joint source": rear_joint_source,
        "rear joint profile": rear_joint_profile,
    }
    make_sheet(reference, sheet_views).save(
        OUTPUT / "comparison-sheet.png", optimize=True
    )

    cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
    chains = {
        "rear_near": ("pelvis_mass", "rear_near_upper", "rear_near_lower", "rear_near_paw"),
        "rear_far": ("pelvis_mass", "rear_far_upper", "rear_far_lower", "rear_far_paw"),
        "front_near": ("shoulder_mass", "front_near_upper", "front_near_lower", "front_near_paw"),
        "front_far": ("shoulder_mass", "front_far_upper", "front_far_lower", "front_far_paw"),
        "horn_near": ("head_cranium", "horn_near_base", "horn_near_mid", "horn_near_curve", "horn_near_return", "horn_near_tip"),
        "horn_far": ("head_cranium", "horn_far_base", "horn_far_mid", "horn_far_curve", "horn_far_return", "horn_far_tip"),
        "tail": ("pelvis_mass", "tail_base", "tail_mid", "tail_tip"),
    }
    attachment = {}
    for name, chain in chains.items():
        gaps = [
            round(
                aabb_gap(spec, cube_by_name[left], cube_by_name[right]),
                6,
            )
            for left, right in zip(chain, chain[1:])
        ]
        attachment[name] = {
            "chain": list(chain),
            "joint_gaps": gaps,
            "joint_axis_overlaps": [
                aabb_axis_overlap(spec, cube_by_name[left], cube_by_name[right])
                for left, right in zip(chain, chain[1:])
            ],
            "maximum_gap": max(gaps),
            "connected_with_tolerance": max(gaps) <= 0.5,
        }
    all_vertices = np.concatenate(
        [cube_vertices(spec, cube) for cube in spec["cubes"]]
    )
    extents = all_vertices.max(axis=0) - all_vertices.min(axis=0)
    trunk_names = ("pelvis_mass", "torso_core", "ribcage", "shoulder_mass")
    trunk_rear = min(
        cube_by_name[name]["center"][2] - cube_by_name[name]["size"][2] / 2
        for name in trunk_names
    )
    trunk_front = max(
        cube_by_name[name]["center"][2] + cube_by_name[name]["size"][2] / 2
        for name in trunk_names
    )
    shoulder = cube_by_name["shoulder_mass"]
    rump = cube_by_name["pelvis_mass"]
    face_names = ("head_cranium", "brow", "muzzle", "jaw")
    face_bottom = min(
        cube_by_name[name]["center"][1] - cube_by_name[name]["size"][1] / 2
        for name in face_names
    )
    face_top = max(
        cube_by_name[name]["center"][1] + cube_by_name[name]["size"][1] / 2
        for name in face_names
    )
    near_horn_outer = cube_by_name["horn_near_curve"]
    far_horn_outer = cube_by_name["horn_far_curve"]
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v1",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "model_extents": [round(float(value), 6) for value in extents],
        "width_to_length_ratio": round(float(extents[0] / extents[2]), 6),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "anatomy_metrics": {
            "measurement_basis": "authored cuboid centers and sizes before rotation",
            "main_trunk_z_span": round(float(trunk_front - trunk_rear), 6),
            "shoulder_top_minus_rump_top": round(
                float(
                    shoulder["center"][1]
                    + shoulder["size"][1] / 2
                    - rump["center"][1]
                    - rump["size"][1] / 2
                ),
                6,
            ),
            "shoulder_to_rump_width_ratio": round(
                float(shoulder["size"][0] / rump["size"][0]), 6
            ),
            "front_to_rear_upper_limb_width_ratio": round(
                float(
                    cube_by_name["front_near_upper"]["size"][0]
                    / cube_by_name["rear_near_upper"]["size"][0]
                ),
                6,
            ),
            "front_chain_pitch_degrees": [
                abs(float(cube_by_name[name]["rotation"][0]))
                for name in (
                    "front_near_upper",
                    "front_near_lower",
                    "front_near_paw",
                )
            ],
            "front_paw_depth": float(cube_by_name["front_near_paw"]["size"][2]),
            "front_pad_depth": float(cube_by_name["front_near_paw_pad"]["size"][2]),
            "green_face_y_span": round(float(face_top - face_bottom), 6),
            "horn_span": round(
                float(
                    far_horn_outer["center"][0]
                    + far_horn_outer["size"][0] / 2
                    - near_horn_outer["center"][0]
                    + near_horn_outer["size"][0] / 2
                ),
                6,
            ),
            "horn_tip_forward_z": float(cube_by_name["horn_near_tip"]["center"][2]),
            "rear_ankle_vertical_overlap": {
                side: aabb_axis_overlap(
                    spec,
                    cube_by_name[f"rear_{side}_lower"],
                    cube_by_name[f"rear_{side}_paw"],
                )[1]
                for side in ("near", "far")
            },
            "rear_toe_vertical_overlap": {
                side: min(
                    aabb_axis_overlap(
                        spec,
                        cube_by_name[f"rear_{side}_paw"],
                        cube_by_name[f"rear_{side}_claw_{index}"],
                    )[1]
                    for index in (1, 2)
                )
                for side in ("near", "far")
            },
            "reference_view_direction": list(VIEWS["reference_angle"]),
        },
        "semantic_profile_fidelity": profile_fidelity,
        "reference_view_fidelity": reference_view_fidelity,
        "bilateral_consistency": {
            "full_body": bilateral_metrics(views["right"], views["left"]),
            "head": bilateral_metrics(views["head_near"], views["head_far"]),
        },
        "attachment_chains": attachment,
        "all_required_chains_connected": all(
            value["connected_with_tolerance"] for value in attachment.values()
        ),
        "views": [
            "front.png",
            "back.png",
            "left.png",
            "right.png",
            "profile.png",
            "top.png",
            "isometric.png",
            "head-near.png",
            "head-far.png",
            "joint-closeup.png",
            "rear-joint-source.png",
            "rear-joint-profile.png",
            "comparison-sheet.png",
            "semantic-profile-reprojection.png",
            "semantic-profile-overlap.png",
            "reference_angle.png",
            "semantic-reference-reprojection.png",
            "semantic-reference-overlap.png",
        ],
    }
    (OUTPUT / "semantic-evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
