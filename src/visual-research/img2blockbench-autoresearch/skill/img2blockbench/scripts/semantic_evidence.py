#!/usr/bin/env python3
"""Deterministic multi-view renderer and attachment metrics for cuboid specs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    raise ModuleNotFoundError(
        "semantic_evidence requires the optional 'semantic-evidence' extra: "
        "pip install 'img2blockbench[semantic-evidence]'"
    ) from exc
from PIL import Image, ImageDraw, ImageFont, ImageOps

from img2blockbench import build_texture, exported_cube_bounds, face_uv
from photo_reconstruction import _cube_point


FACE_VERTICES = {
    "north": (1, 0, 3, 2),
    "east": (5, 1, 2, 6),
    "south": (4, 5, 6, 7),
    "west": (0, 4, 7, 3),
    "up": (7, 6, 2, 3),
    "down": (0, 1, 5, 4),
}

STANDARD_VIEWS = {
    "front": (0.0, 0.04, 1.0),
    "back": (0.0, 0.04, -1.0),
    "left": (1.0, 0.06, 0.0),
    "right": (-1.0, 0.06, 0.0),
    "top": (0.001, 1.0, 0.0),
    "isometric": (1.0, 0.58, 1.0),
}


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
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
    """Return the eight world-space corners using compiler conventions."""
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


def camera_basis(direction: tuple[float, float, float]) -> tuple[np.ndarray, ...]:
    """Create an orthographic right/up/view camera basis."""
    view = np.asarray(direction, dtype=np.float64)
    if np.linalg.norm(view) <= 1e-12:
        raise ValueError("camera direction cannot be zero")
    view /= np.linalg.norm(view)
    world_up = np.asarray((0.0, 1.0, 0.0))
    if abs(float(np.dot(view, world_up))) > 0.96:
        world_up = np.asarray((0.0, 0.0, -1.0))
    right = np.cross(world_up, view)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    up /= np.linalg.norm(up)
    return right, up, view


def _raster_triangle(
    canvas: np.ndarray,
    zbuffer: np.ndarray,
    points: np.ndarray,
    depths: np.ndarray,
    texture_uv: np.ndarray,
    atlas: np.ndarray,
    brightness: float,
) -> None:
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
        np.rint(sampled[:, :, :3].astype(np.float64) * brightness), 0, 255
    ).astype(np.uint8)
    visible &= sampled[:, :, 3] >= 16
    target = canvas[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    target[visible] = sampled[visible]
    target_depth[visible] = depth[visible]


def render_view(
    spec: dict[str, Any],
    direction: tuple[float, float, float],
    *,
    atlas_image: Image.Image | None = None,
    placements: dict[tuple[str, str], tuple[int, int, int, int]] | None = None,
    selected_names: set[str] | None = None,
    size: tuple[int, int] = (640, 640),
    background: tuple[int, int, int, int] = (13, 20, 28, 255),
) -> Image.Image:
    """Render native rotated cuboids through an orthographic depth buffer."""
    if atlas_image is None or placements is None:
        atlas_image, placements = build_texture(spec)
    cubes = [
        cube for cube in spec["cubes"]
        if selected_names is None or cube["name"] in selected_names
    ]
    if not cubes:
        raise ValueError("render selection contains no cuboids")
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
    canvas = np.empty((size[1], size[0], 4), dtype=np.uint8)
    canvas[:, :, :] = background
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
            first_u, first_v, second_u, second_v = face_uv(cube, face_name, placement)
            uv = np.asarray(
                ((first_u, second_v), (second_u, second_v),
                 (second_u, first_v), (first_u, first_v)),
                dtype=np.float64,
            )
            brightness = 0.72 + 0.32 * max(0.0, float(np.dot(normal, light)))
            for triangle in ((0, 1, 2), (0, 2, 3)):
                indexes_in_face = list(triangle)
                _raster_triangle(
                    canvas,
                    zbuffer,
                    screen[list(indexes)][indexes_in_face],
                    depths[list(indexes)][indexes_in_face],
                    uv[indexes_in_face],
                    atlas,
                    brightness,
                )
    return Image.fromarray(canvas, mode="RGBA")


def foreground_mask(
    image: Image.Image, background: tuple[int, int, int] = (13, 20, 28)
) -> Image.Image:
    """Extract foreground from a render with the standard solid background."""
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
    mask = np.any(pixels != np.asarray(background, dtype=np.uint8), axis=2)
    return Image.fromarray(mask.astype(np.uint8) * 255, mode="L")


def alpha_mask(image: Image.Image, *, threshold: int = 16) -> Image.Image:
    """Extract a silhouette from meaningful transparency without RGB guesses."""
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= 255:
        raise ValueError("alpha threshold must be an integer within 1..255")
    alpha = np.asarray(image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    if not np.any(alpha < 255):
        raise ValueError("image has no transparent pixels; provide a foreground mask")
    return Image.fromarray((alpha >= threshold).astype(np.uint8) * 255, mode="L")


def height_normalized_mask(
    mask: Image.Image,
    *,
    target_height: int = 496,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Crop and scale a mask by height while preserving its aspect ratio."""
    if (
        not isinstance(target_height, int)
        or isinstance(target_height, bool)
        or target_height < 8
    ):
        raise ValueError("target_height must be an integer of at least eight")
    pixels = np.asarray(mask.convert("L"), dtype=np.uint8) >= 128
    rows, columns = np.where(pixels)
    if not len(rows):
        raise ValueError("cannot normalize an empty silhouette")
    left = int(columns.min())
    top = int(rows.min())
    right = int(columns.max()) + 1
    bottom = int(rows.max()) + 1
    crop = pixels[top:bottom, left:right]
    scale = target_height / crop.shape[0]
    target_width = max(1, round(crop.shape[1] * scale))
    normalized = np.asarray(
        Image.fromarray(crop.astype(np.uint8) * 255, mode="L").resize(
            (target_width, target_height), Image.Resampling.NEAREST
        ),
        dtype=np.uint8,
    ) >= 128
    return normalized, {
        "bbox": [left, top, right, bottom],
        "source_width": int(crop.shape[1]),
        "source_height": int(crop.shape[0]),
        "normalized_width": target_width,
        "normalized_height": target_height,
        "scale": round(scale, 9),
        "touches_frame_edges": {
            "left": left == 0,
            "top": top == 0,
            "right": right == pixels.shape[1],
            "bottom": bottom == pixels.shape[0],
        },
    }


def _normalized_keypoint(
    point: Sequence[float], bounds: Sequence[int], label: str
) -> tuple[float, float]:
    """Express an image point relative to silhouette center and height."""
    if len(point) != 2 or not all(math.isfinite(float(value)) for value in point):
        raise ValueError(f"{label} must contain two finite numbers")
    left, top, right, bottom = (float(value) for value in bounds)
    height = bottom - top
    if height <= 0 or right <= left:
        raise ValueError(f"{label} silhouette bounds are degenerate")
    return (
        (float(point[0]) - (left + right) / 2) / height,
        (float(point[1]) - top) / height,
    )


def alpha_silhouette_metrics(
    reference: Image.Image,
    rendered: Image.Image,
    *,
    reference_keypoints: Mapping[str, Sequence[float]] | None = None,
    rendered_keypoints: Mapping[str, Sequence[float]] | None = None,
    rendered_background: tuple[int, int, int] = (13, 20, 28),
    alpha_threshold: int = 16,
    target_height: int = 496,
) -> dict[str, Any]:
    """Compare a transparent source and rendered silhouette at equal height.

    Optional named points are normalized by their own silhouette height and
    horizontal center before Euclidean error is measured. This keeps landmark
    scoring independent of source resolution and aspect ratio.
    """
    source_mask = alpha_mask(reference, threshold=alpha_threshold)
    model_mask = foreground_mask(rendered, background=rendered_background)
    source, source_transform = height_normalized_mask(
        source_mask, target_height=target_height
    )
    model, model_transform = height_normalized_mask(
        model_mask, target_height=target_height
    )
    padding = 8
    canvas_width = max(source.shape[1], model.shape[1]) + padding * 2

    def centered(mask: np.ndarray) -> np.ndarray:
        canvas = np.zeros((target_height, canvas_width), dtype=bool)
        left = (canvas_width - mask.shape[1]) // 2
        canvas[:, left : left + mask.shape[1]] = mask
        return canvas

    source_canvas = centered(source)
    model_canvas = centered(model)
    intersection = source_canvas & model_canvas
    union = source_canvas | model_canvas
    keypoint_report: dict[str, Any] | None = None
    if (reference_keypoints is None) != (rendered_keypoints is None):
        raise ValueError("reference and rendered keypoints must be supplied together")
    if reference_keypoints is not None and rendered_keypoints is not None:
        if set(reference_keypoints) != set(rendered_keypoints):
            raise ValueError("reference and rendered keypoint names must match")
        records = {}
        errors = []
        for name in sorted(reference_keypoints):
            source_point = _normalized_keypoint(
                reference_keypoints[name], source_transform["bbox"], f"reference {name}"
            )
            model_point = _normalized_keypoint(
                rendered_keypoints[name], model_transform["bbox"], f"rendered {name}"
            )
            error = math.dist(source_point, model_point)
            errors.append(error)
            records[name] = {
                "reference": [round(value, 6) for value in source_point],
                "rendered": [round(value, 6) for value in model_point],
                "error_subject_heights": round(error, 6),
            }
        keypoint_report = {
            "count": len(records),
            "mean_error_subject_heights": round(
                sum(errors) / max(1, len(errors)), 6
            ),
            "maximum_error_subject_heights": round(max(errors, default=0.0), 6),
            "points": records,
        }
    return {
        "method": "alpha-mask-aspect-preserving-height-normalized-centered-iou-v1",
        "alpha_threshold": alpha_threshold,
        "target_height": target_height,
        "iou": round(float(intersection.sum() / max(1, union.sum())), 6),
        "recall": round(float(intersection.sum() / max(1, source_canvas.sum())), 6),
        "precision": round(float(intersection.sum() / max(1, model_canvas.sum())), 6),
        "reference_aspect_ratio": round(source.shape[1] / source.shape[0], 6),
        "rendered_aspect_ratio": round(model.shape[1] / model.shape[0], 6),
        "reference_transform": source_transform,
        "rendered_transform": model_transform,
        "keypoints": keypoint_report,
        "source_touches_frame": any(source_transform["touches_frame_edges"].values()),
        "limitation": (
            "front alpha silhouette and annotated keypoints only; hidden-side geometry "
            "still requires multi-view inspection. A source touching the frame may contain "
            "clipped appendages, so IoU cannot establish their off-frame continuation."
        ),
    }


def bilateral_metrics(first: Image.Image, second: Image.Image) -> dict[str, float]:
    """Measure mirror silhouette and overlapping RGB consistency."""
    first_rgb = first.convert("RGB")
    second_rgb = ImageOps.mirror(second.convert("RGB"))
    first_mask = np.asarray(foreground_mask(first_rgb), dtype=np.uint8) >= 128
    second_mask = np.asarray(foreground_mask(second_rgb), dtype=np.uint8) >= 128
    intersection = first_mask & second_mask
    union = first_mask | second_mask
    first_pixels = np.asarray(first_rgb, dtype=np.int16)
    second_pixels = np.asarray(second_rgb, dtype=np.int16)
    mae = (
        float(np.abs(first_pixels[intersection] - second_pixels[intersection]).mean())
        if intersection.any() else 255.0
    )
    return {
        "silhouette_iou": round(
            float(np.count_nonzero(intersection) / max(1, np.count_nonzero(union))), 6
        ),
        "overlap_rgb_mae": round(mae, 4),
    }


def aabb_gap(spec: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> float:
    """Return shortest separation between rotated-cuboid world AABBs."""
    first_vertices = cube_vertices(spec, first)
    second_vertices = cube_vertices(spec, second)
    separation = np.maximum(
        0,
        np.maximum(
            first_vertices.min(axis=0) - second_vertices.max(axis=0),
            second_vertices.min(axis=0) - first_vertices.max(axis=0),
        ),
    )
    return float(np.linalg.norm(separation))


def contact_sheet(
    reference: Image.Image,
    views: dict[str, Image.Image],
    *,
    columns: int = 4,
    tile: tuple[int, int] = (300, 250),
) -> Image.Image:
    """Compose a labeled reference-plus-renders review sheet."""
    header = 38
    entries = [("reference", reference.convert("RGBA")), *views.items()]
    rows = math.ceil(len(entries) / columns)
    sheet = Image.new("RGB", (tile[0] * columns, (tile[1] + header) * rows), "#09111a")
    draw = ImageDraw.Draw(sheet)
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
        draw.text(
            (x + 12, y + 10),
            name.upper().replace("_", " "),
            fill="#f0bd31",
            font=_font(17, bold=True),
        )
    return sheet
