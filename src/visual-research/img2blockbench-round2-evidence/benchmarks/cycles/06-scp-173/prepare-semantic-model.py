#!/usr/bin/env python3
"""Author the Cycle 6 volumetric SCP-173 benchmark model."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from semantic_geometry import (
    SemanticModelBuilder,
    ellipsoid_cuboids,
    point_to_cuboid_margin,
    segment_cube,
)


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "benchmarks" / "references" / "06-scp-173.jpg"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "85d698e25b04dbfc4009a05e1cdbb7dc13c5675d2f7c76e5af8cb5e13f0bd93f"


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "dither",
    scale: int = 2,
) -> dict[str, Any]:
    """Create one crisp deterministic pixel material."""
    return {
        "base": base,
        "shade": shade,
        "highlight": highlight,
        "pattern": pattern,
        "pattern_scale": scale,
    }


def procedural_face_texture() -> dict[str, Any]:
    """Return one original, opaque concrete-and-paint face decal.

    The decal is generated from primitive shapes rather than sampled from the
    restricted reference. Every visible front cell of the stepped egg uses a
    slice of this same image, so the markings remain flush with the volume.
    """
    width, height = 80, 124
    base = (180, 154, 105)
    image = Image.new("RGBA", (width, height), (*base, 255))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            coarse = ((x // 5) * 17 + (y // 7) * 29 + x * 3 + y * 5) % 37
            fine = ((x * 11 + y * 19) % 13) - 6
            stain = -18 if coarse in {0, 1} else 12 if coarse == 18 else 0
            pixels[x, y] = tuple(
                max(0, min(255, value + stain + fine)) for value in base
            ) + (255,)

    draw = ImageDraw.Draw(image)
    red = "#7f1b12"
    dark_red = "#51110d"
    olive = "#6b7024"
    olive_dark = "#33370e"
    black = "#171009"
    rust = "#82502d"

    # One irregular dried-red forehead smear around a narrow central slit.
    draw.polygon(
        [(37, 42), (34, 28), (37, 22), (38, 10), (41, 18), (45, 24),
         (43, 33), (46, 42), (44, 60), (35, 60)],
        fill=red,
    )
    draw.polygon([(38, 25), (35, 14), (39, 7), (42, 20)], fill=red)
    draw.polygon([(42, 29), (48, 18), (46, 35)], fill=dark_red)
    draw.ellipse((35, 38, 45, 68), fill=dark_red)
    draw.ellipse((37, 41, 43, 66), fill=black)

    # Paired olive discs have dark irregular rims, not geometric raised pads.
    for center_x in (23, 57):
        draw.ellipse((center_x - 10, 44, center_x + 10, 65), fill=olive_dark)
        draw.ellipse((center_x - 8, 46, center_x + 8, 63), fill=olive)
        draw.arc((center_x - 7, 47, center_x + 7, 62), 210, 35, fill="#96994b", width=2)

    # Lower sockets, red connective brush strokes, triangular nose, and mouth.
    draw.line((10, 70, 31, 72), fill=red, width=3)
    draw.line((49, 72, 71, 68), fill=red, width=3)
    for center_x, tilt in ((23, -2), (57, 2)):
        draw.ellipse((center_x - 10, 66 + tilt, center_x + 10, 89 + tilt), fill=dark_red)
        draw.ellipse((center_x - 7, 69 + tilt, center_x + 7, 87 + tilt), fill=black)
        draw.ellipse((center_x - 5, 71 + tilt, center_x + 4, 82 + tilt), fill="#2f2419")
    draw.polygon([(40, 78), (34, 89), (46, 89)], fill=black)
    draw.polygon([(40, 81), (37, 87), (43, 87)], fill=rust)
    draw.line((30, 96, 50, 94), fill=dark_red, width=4)
    draw.line((32, 97, 48, 98), fill=black, width=3)
    for x, drop in ((33, 5), (38, 8), (43, 7), (48, 4)):
        draw.polygon([(x - 2, 96), (x + 2, 96), (x, 96 + drop)], fill=rust)

    # Sparse stains and cracks make the plane match the surrounding concrete.
    draw.line((8, 35, 6, 51, 9, 64), fill=red, width=2)
    draw.line((63, 22, 70, 30, 68, 37), fill="#6a5438", width=1)
    draw.line((12, 101, 19, 96, 23, 104), fill="#55432d", width=1)
    draw.line((61, 105, 66, 99, 72, 103), fill="#55432d", width=1)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return {
        "data_uri": "data:image/png;base64,"
        + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "repeat": [1, 1],
        "offset": [0, 0],
        "center": [0, 0],
        "rotation": 0,
        "wrap": [1001, 1001],
        "flip_y": True,
    }


def box(
    name: str,
    bone: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    role: str,
    material_name: str,
    *,
    rotation: tuple[float, float, float] = (0, 0, 0),
    origin: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """Create one semantic cuboid without a flat source-image skin."""
    return {
        "name": name,
        "bone": bone,
        "center": list(center),
        "size": list(size),
        "rotation": list(rotation),
        "origin": list(origin or center),
        "role": role,
        "material": material_name,
        "faces": {},
    }


def nearest_attachment(
    cubes: list[dict[str, Any]], point: tuple[float, float, float]
) -> tuple[str, tuple[float, float, float]]:
    """Return a safely inset point in the closest occupied volume cuboid."""
    containing = [
        (point_to_cuboid_margin(cube, point), cube)
        for cube in cubes
        if point_to_cuboid_margin(cube, point) >= 0
    ]
    if containing:
        _, cube = max(containing, key=lambda item: item[0])
        return cube["name"], point
    best: tuple[float, dict[str, Any], tuple[float, float, float]] | None = None
    for cube in cubes:
        center = tuple(float(value) for value in cube["center"])
        size = tuple(float(value) for value in cube["size"])
        inset = tuple(
            max(
                center[axis] - size[axis] / 2 + 0.18,
                min(center[axis] + size[axis] / 2 - 0.18, point[axis]),
            )
            for axis in range(3)
        )
        distance = math.dist(point, inset)
        candidate = (distance, cube, inset)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        raise ValueError("cannot attach to an empty volume")
    return best[1]["name"], best[2]


def main() -> None:
    """Write a native deep statue with an unmistakable layered face."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected SCP-173 reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (750, 1000):
            raise ValueError(f"unexpected SCP-173 reference size: {opened.size}")

    materials = {
        "concrete": material("#b49a69", "#756044", "#d8c391", "dither", 10),
        "concrete_dark": material("#8d744e", "#493923", "#b99b69", "dither", 6),
        "crack": material("#483a29", "#211a12", "#705c40", "solid", 1),
    }
    materials["face_decal"] = {
        **material("#b49a69", "#756044", "#d8c391", "solid", 1),
        "source_texture": procedural_face_texture(),
    }

    builder = SemanticModelBuilder()
    builder.add_bone("torso", "root", (0, 21.0, 0))
    builder.add_bone("neck", "torso", (0, 31.0, 0))
    builder.add_bone("head", "neck", (0, 40.2, 0))

    torso_volume = ellipsoid_cuboids(
        "torso_volume",
        "torso",
        (0, 21.0, 0),
        (3.7, 10.7, 3.5),
        (10, 18, 8),
        "long rounded dirty concrete pillar torso",
        "concrete",
        max_cuboids=48,
        exponent=4.0,
    )
    torso_cubes = list(torso_volume.cubes)
    for cube in torso_cubes:
        builder.add_cube(cube)

    head_volume = ellipsoid_cuboids(
        "head_volume",
        "head",
        (0, 40.2, 0),
        (5.0, 7.8, 5.0),
        (10, 14, 10),
        "large smooth oval concrete head",
        "concrete",
        max_cuboids=64,
        exponent=2.0,
    )
    head_cubes = list(head_volume.cubes)
    for cube in head_cubes:
        center_x, center_y, _ = (float(value) for value in cube["center"])
        size_x, size_y, _ = (float(value) for value in cube["size"])
        left = max(0.0, (center_x - size_x / 2 + 5.0) / 10.0)
        right = min(1.0, (center_x + size_x / 2 + 5.0) / 10.0)
        top = max(0.0, (48.0 - (center_y + size_y / 2)) / 15.6)
        bottom = min(1.0, (48.0 - (center_y - size_y / 2)) / 15.6)
        cube["faces"] = {
            "south": {
                "material": "face_decal",
                "source_region": [left, top, right, bottom],
            }
        }
        builder.add_cube(cube)

    builder.add_cube(
        box(
            "neck_core",
            "neck",
            (0, 31.0, 0),
            (5.2, 5.2, 5.2),
            "narrow neck joining head and pillar torso",
            "concrete",
        )
    )

    attachments: list[tuple[str, str, tuple[float, float, float]]] = []
    torso_parent, torso_neck_joint = nearest_attachment(torso_cubes, (0, 30.2, 0))
    head_parent, head_neck_joint = nearest_attachment(head_cubes, (0, 32.7, 0))
    attachments.extend(
        [
            (torso_parent, "neck_core", torso_neck_joint),
            ("neck_core", head_parent, head_neck_joint),
        ]
    )

    # Two genuinely separated, tapered legs continue the pillar silhouette.
    leg_paths = (
        ("left_leg", (-2.0, 12.35, 0), (-2.1, 6.1, 0.1), (-2.15, 0.25, 0.2)),
        ("right_leg", (2.0, 12.35, 0), (2.1, 6.1, -0.1), (2.15, 0.25, 0.2)),
    )
    limb_chains: list[tuple[str, Any]] = []
    for name, root, knee, foot in leg_paths:
        parent_cube, inset_root = nearest_attachment(torso_cubes, root)
        chain = builder.add_chain(
            name,
            "torso",
            (inset_root, knee, foot),
            (2.85, 2.65),
            ("concrete", "concrete_dark"),
            "straight separated concrete leg",
            overlap=0.48,
            depths=(3.25, 3.0),
        )
        attachments.append((parent_cube, chain.cubes[0], chain.joints[0]))
        attachments.extend(chain.attachments)
        limb_chains.append((parent_cube, chain))

    # The viewer-left arm folds inward; viewer-right is raised and reaches out.
    arm_paths = (
        (
            "viewer_left_arm",
            (-3.2, 29.8, 0.1),
            (-4.65, 26.4, 0.7),
            (-3.85, 27.55, 2.1),
        ),
        (
            "viewer_right_arm",
            (3.2, 29.8, 0.0),
            (5.35, 26.8, 0.7),
            (6.55, 28.45, 2.1),
        ),
    )
    for name, root, elbow, wrist in arm_paths:
        parent_cube, inset_root = nearest_attachment(torso_cubes, root)
        chain = builder.add_chain(
            name,
            "torso",
            (inset_root, elbow, wrist),
            (2.55, 2.3),
            ("concrete_dark", "concrete"),
            "short asymmetric raised concrete arm",
            overlap=0.52,
            depths=(2.9, 2.65),
        )
        attachments.append((parent_cube, chain.cubes[0], chain.joints[0]))
        attachments.extend(chain.attachments)
        fist_bone = f"{name}_fist"
        builder.add_bone(fist_bone, chain.bones[-1], wrist)
        builder.add_cube(
            box(
                fist_bone,
                fist_bone,
                wrist,
                (2.85, 2.7, 2.85),
                "blocky clenched concrete fist",
                "concrete_dark",
                rotation=(4, 8 if wrist[0] > 0 else -8, -10 if wrist[0] > 0 else 12),
                origin=wrist,
            )
        )
        # A second offset knuckle mass rounds the fist from side/top views.
        knuckle_name = f"{name}_knuckles"
        knuckle_center = (wrist[0], wrist[1] + 0.38, wrist[2] + 0.72)
        builder.add_cube(
            box(
                knuckle_name,
                fist_bone,
                knuckle_center,
                (2.5, 1.75, 1.7),
                "forward clenched knuckle ridge",
                "concrete",
                rotation=(4, 8 if wrist[0] > 0 else -8, -10 if wrist[0] > 0 else 12),
                origin=wrist,
            )
        )
        attachments.append((chain.cubes[-1], fist_bone, wrist))
        attachments.append((fist_bone, knuckle_name, wrist))

    # Thin embedded crack segments break up the concrete without changing the
    # silhouette or pretending to recover unseen topology.
    crack_paths = (
        ("torso_crack_1", (-1.7, 25.0, 3.35), (-0.7, 21.8, 3.48)),
        ("torso_crack_2", (-0.7, 21.8, 3.48), (-1.25, 19.0, 3.43)),
        ("torso_crack_3", (1.8, 20.0, 3.35), (0.9, 16.5, 3.48)),
        ("torso_crack_4", (-2.0, 15.0, 3.2), (-1.5, 12.5, 3.12)),
    )
    for name, start, end in crack_paths:
        bone = "head" if name.startswith("head_") else "torso"
        builder.add_cube(
            segment_cube(
                name,
                bone,
                start,
                end,
                (0.28, 0.36),
                "shallow concrete crack",
                "crack",
                overlap=0.08,
            )
        )

    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    spec = {
        "schema_version": 1,
        "id": "scp_173",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 750,
            "height": 1000,
        },
        "subject": {
            "type": "character",
            "description": (
                "Volumetric dirty concrete SCP-173 statue with oval head, pillar "
                "body, asymmetric raised arms, split legs, and canonical painted face"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "The supplied reference is one frontal product-style image; profile "
                "and back depth are conservative semantic inference",
                "The user called the subject SCP-174, but the linked image depicts "
                "the legacy SCP-173 sculpture artwork",
                "No claim is made that synthetic proxy views establish hidden source geometry",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [75, 100],
            "identity_features": [
                "giant smooth egg-shaped head narrowing into neck",
                "long dirty beige concrete pillar torso",
                "two straight visibly separated legs",
                "short asymmetric bent raised arms with fists",
                "red forehead flame around a central black slit",
                "paired green upper discs and red-rimmed black lower sockets",
                "small triangular nose and rusty jagged mouth",
            ],
            "required_views": [
                "front", "back", "left", "right", "top", "isometric",
                "face-closeup", "left-head-closeup", "right-head-closeup",
                "arm-joints",
            ],
            "review_targets": [
                "egg silhouette", "head-to-body ratio", "canonical painted face",
                "leg separation", "arm attachment", "true depth",
            ],
        },
        "geometry": {"precision": 16},
        "texture": {
            "density": 4,
            "palette_size": 24,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": [],
        "collision": {"width": 0.95, "height": 3.1, "eye_height": 2.65},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "greedy-superellipsoid-flush-decal-statue-v2",
            "source_mesh": None,
            "source_skin_cuboids": 0,
            "source_projection": False,
            "anatomical_axis": "+Z front, X width, Y up",
            "single_view_hidden_geometry": "inferred_conservatively_not_observed",
            "procedural_face_decal": {
                "method": "one generated opaque PNG sliced across stepped south faces",
                "dimensions": [80, 124],
                "source_reference_pixels": False,
                "geometric_protrusion": 0,
                "painted_surface": "south/front only",
                "features": {
                    "red_forehead_flame": True,
                    "central_black_slit": True,
                    "upper_green_discs": 2,
                    "lower_black_sockets": 2,
                    "triangular_nose": True,
                    "jagged_mouth_teeth": 4,
                    "left_edge_red_smear": True,
                },
            },
            "feature_inventory": {
                "head_volumes": len(head_cubes),
                "torso_volumes": len(torso_cubes),
                "leg_segments": 4,
                "arm_segments": 4,
                "fist_volumes": 4,
                "procedural_face_decal_images": 1,
                "decal_mapped_front_faces": len(head_cubes),
                "geometric_face_pads": 0,
                "surface_cracks": len(crack_paths),
            },
            "head_ellipsoid": {
                "center": [0, 40.2, 0],
                "radii": [5.0, 7.8, 5.0],
                "subdivisions": list(head_volume.grid_shape),
                "occupied_voxels": head_volume.occupied_voxels,
                "greedy_cuboids": len(head_volume.cubes),
            },
            "torso_superellipsoid": {
                "center": [0, 21.0, 0],
                "radii": [3.7, 10.7, 3.5],
                "subdivisions": list(torso_volume.grid_shape),
                "exponent": 4.0,
                "occupied_voxels": torso_volume.occupied_voxels,
                "greedy_cuboids": len(torso_volume.cubes),
            },
            "attachment_contract": {
                "method": "declared-shared-joints-tested-against-oriented-cuboids",
                "endpoint_overlap": 0.48,
            },
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
