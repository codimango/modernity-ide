#!/usr/bin/env python3
"""Author the Cycle 1 volumetric American goldfinch benchmark model."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from PIL import Image

from semantic_geometry import (
    SemanticModelBuilder,
    ellipsoid_cuboids,
    point_to_cuboid_margin,
)


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "benchmarks" / "references" / "01-american-goldfinch.jpg"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "094818044cf5373d674e42dcff666a7a37063e940b252aa841028e9ac2dcab8d"


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "dither",
    scale: int = 3,
) -> dict[str, Any]:
    """Create one crisp deterministic feather or keratin material."""
    return {
        "base": base,
        "shade": shade,
        "highlight": highlight,
        "pattern": pattern,
        "pattern_scale": scale,
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
    faces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one semantic native cuboid without a source-image skin."""
    return {
        "name": name,
        "bone": bone,
        "center": list(center),
        "size": list(size),
        "rotation": list(rotation),
        "origin": list(origin or center),
        "role": role,
        "material": material_name,
        "faces": dict(faces or {}),
    }


def nearest_attachment(
    cubes: list[dict[str, Any]], point: tuple[float, float, float]
) -> tuple[str, tuple[float, float, float]]:
    """Return a safely inset attachment point in the nearest volume cuboid."""
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
                center[axis] - size[axis] / 2 + 0.16,
                min(center[axis] + size[axis] / 2 - 0.16, point[axis]),
            )
            for axis in range(3)
        )
        candidate = (math.dist(point, inset), cube, inset)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        raise ValueError("cannot attach to an empty volume")
    return best[1]["name"], best[2]


def main() -> None:
    """Write a true bilateral bird with connected wings, tail, legs, and toes."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected American goldfinch reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (3072, 3072):
            raise ValueError(f"unexpected American goldfinch reference size: {opened.size}")

    materials = {
        "lemon_feather": material("#e8d92b", "#9c8c16", "#fff04b", "dither", 3),
        "gold_feather": material("#cfad19", "#7b6913", "#f5d93e", "gradient", 3),
        "cream_feather": material("#ded7a6", "#918b68", "#fff7ca", "dither", 3),
        "white_feather": material("#e6e1c7", "#999477", "#fffce8", "gradient", 2),
        "black_feather": material("#151b20", "#07090c", "#424b51", "dither", 2),
        "wing_bar": material("#e5e1ca", "#8e8a72", "#fffceb", "solid", 1),
        "beak_upper": material("#d68b51", "#7d3f2e", "#f3ba72", "gradient", 2),
        "beak_lower": material("#e1a64d", "#8e5626", "#ffd277", "gradient", 2),
        "eye_ring": material("#d6b33f", "#6b5722", "#f6db69", "dither", 2),
        "eye_black": material("#11141a", "#020305", "#59636c", "solid", 1),
        "leg_pink": material("#b97865", "#704238", "#db9b80", "dither", 2),
        "claw_dark": material("#59443d", "#241c1a", "#8f7165", "gradient", 2),
    }

    builder = SemanticModelBuilder()
    builder.add_bone("body", "root", (0, 10.5, -1.0))
    builder.add_bone("neck", "body", (0, 12.3, 3.5))
    builder.add_bone("head", "neck", (0, 14.2, 5.6))
    builder.add_bone("cap", "head", (0, 16.1, 6.6))
    builder.add_bone("left_eye", "head", (3.1, 15.1, 7.35))
    builder.add_bone("right_eye", "head", (-3.1, 15.1, 7.35))
    builder.add_bone("beak", "head", (0, 14.2, 8.8))
    builder.add_bone("tail", "body", (0, 10.7, -7.0))

    body_volume = ellipsoid_cuboids(
        "body_volume",
        "body",
        (0, 10.5, -1.0),
        (4.65, 5.25, 8.1),
        (8, 10, 12),
        "rounded teardrop breast and rump",
        "lemon_feather",
        max_cuboids=32,
        exponent=2.15,
    )
    body_cubes = list(body_volume.cubes)
    for cube in body_cubes:
        center_y = float(cube["center"][1])
        center_z = float(cube["center"][2])
        if center_z < -5.0 and center_y < 11.0:
            cube["material"] = "white_feather"
            cube["role"] = cube["role"].replace("breast and rump", "pale rear rump")
        elif center_y < 7.6:
            cube["material"] = "cream_feather"
            cube["role"] = cube["role"].replace("breast and rump", "cream lower belly")
        elif center_y < 9.0:
            cube["material"] = "gold_feather"
            cube["role"] = cube["role"].replace("breast and rump", "warm lower breast")
        builder.add_cube(cube)

    builder.add_cube(
        box(
            "neck_bridge",
            "neck",
            (0, 12.7, 3.7),
            (5.0, 3.7, 4.6),
            "feathered neck joining head to breast",
            "lemon_feather",
        )
    )
    head_volume = ellipsoid_cuboids(
        "head_volume",
        "head",
        (0, 14.3, 5.7),
        (3.05, 3.15, 3.5),
        (8, 8, 8),
        "small rounded goldfinch head",
        "lemon_feather",
        max_cuboids=32,
        exponent=2.1,
    )
    head_cubes = list(head_volume.cubes)
    for cube in head_cubes:
        builder.add_cube(cube)

    builder.add_cube(
        box(
            "black_cap_crown",
            "cap",
            (0, 17.15, 6.45),
            (5.15, 1.55, 3.8),
            "breeding-plumage black crown",
            "black_feather",
            rotation=(0, 0, 0),
        )
    )
    builder.add_cube(
        box(
            "black_cap_forehead",
            "cap",
            (0, 15.65, 9.05),
            (5.3, 2.45, 1.25),
            "black forehead mask above bill",
            "black_feather",
        )
    )

    for side, sign, outward_face in (("left", 1, "east"), ("right", -1, "west")):
        builder.add_cube(
            box(
                f"{side}_eye_ring",
                f"{side}_eye",
                (sign * 2.9, 15.05, 7.42),
                (0.58, 1.15, 1.15),
                f"{side} golden eye ring",
                "eye_ring",
            )
        )
        builder.add_cube(
            box(
                f"{side}_eye",
                f"{side}_eye",
                (sign * 3.16, 15.07, 7.47),
                (0.32, 0.66, 0.66),
                f"{side} glossy black eye",
                "eye_black",
                faces={outward_face: {"material": "eye_black"}},
            )
        )

    head_beak_parent, beak_anchor = nearest_attachment(head_cubes, (0, 14.25, 8.75))
    upper_beak = builder.add_chain(
        "upper_beak",
        "beak",
        (beak_anchor, (0, 14.25, 10.75), (0, 14.05, 12.25)),
        (2.9, 1.35),
        ("beak_upper", "beak_upper"),
        "tapering pointed upper bill",
        overlap=0.28,
        depths=(1.25, 0.72),
        longitudinal_axis="z",
    )
    lower_beak = builder.add_chain(
        "lower_beak",
        "beak",
        ((beak_anchor[0], beak_anchor[1] - 0.55, beak_anchor[2]), (0, 13.55, 10.6), (0, 13.9, 12.0)),
        (2.55, 1.05),
        ("beak_lower", "beak_lower"),
        "tapering pointed lower bill",
        overlap=0.24,
        depths=(0.88, 0.5),
        longitudinal_axis="z",
    )

    wing_chains = []
    wing_patch_names: list[tuple[str, str]] = []
    for side, sign in (("left", 1), ("right", -1)):
        body_parent, wing_anchor = nearest_attachment(
            body_cubes, (sign * 3.0, 12.7, 2.5)
        )
        chain = builder.add_chain(
            f"wing_{side}",
            "body",
            (
                wing_anchor,
                (sign * 4.38, 11.65, -3.8),
                (sign * 4.05, 10.75, -9.2),
                (sign * 3.55, 10.55, -12.25),
            ),
            (0.95, 0.78, 0.58),
            ("black_feather", "black_feather", "black_feather"),
            f"{side} tapered folded flight wing",
            overlap=0.45,
            depths=(4.7, 3.4, 2.25),
            longitudinal_axis="z",
        )
        wing_chains.append((side, sign, body_parent, chain))
        primary_name = f"white_bar_{side}_primary"
        secondary_name = f"white_bar_{side}_secondary"
        builder.add_cube(
            box(
                primary_name,
                chain.bones[0],
                (sign * 4.82, 12.1, -1.45),
                (0.24, 3.15, 1.05),
                f"{side} raised white covert-feather bar",
                "wing_bar",
                rotation=(-34, 0, 0),
            )
        )
        builder.add_cube(
            box(
                secondary_name,
                chain.bones[1],
                (sign * 4.45, 11.25, -6.45),
                (0.22, 2.3, 0.72),
                f"{side} secondary white flight-feather bar",
                "wing_bar",
                rotation=(-30, 0, 0),
            )
        )
        wing_patch_names.append((primary_name, secondary_name))

    body_tail_parent, tail_anchor = nearest_attachment(body_cubes, (0, 10.7, -7.1))
    tail_chain = builder.add_chain(
        "tail_feather",
        "tail",
        (tail_anchor, (0, 10.5, -12.2), (0, 10.25, -16.0), (0, 10.0, -18.35)),
        (5.3, 3.75, 2.15),
        ("black_feather", "black_feather", "black_feather"),
        "tapered black tail fan",
        overlap=0.45,
        depths=(1.15, 0.88, 0.62),
        longitudinal_axis="z",
    )

    leg_chains = []
    cuff_names: dict[str, str] = {}
    for side, sign, root_z, ankle_z in (
        ("left", 1, -0.3, 0.7),
        ("right", -1, -2.1, -0.3),
    ):
        intended_root = (sign * 1.55, 6.25, root_z)
        body_parent, leg_root = nearest_attachment(body_cubes, intended_root)
        cuff_bone = f"{side}_leg_cuff"
        builder.add_bone(cuff_bone, "body", leg_root)
        cuff_name = f"{side}_thigh_fluff"
        builder.add_cube(
            box(
                cuff_name,
                cuff_bone,
                (leg_root[0], leg_root[1] - 0.25, leg_root[2]),
                (1.75, 2.0, 1.7),
                f"{side} pale feathered thigh cuff",
                "cream_feather",
            )
        )
        cuff_names[side] = cuff_name
        knee = (sign * 1.72, 4.55, root_z + 0.45)
        ankle = (sign * 1.35, 3.35, ankle_z)
        chain = builder.add_chain(
            f"leg_{side}",
            cuff_bone,
            (leg_root, knee, ankle),
            (0.72, 0.54),
            ("leg_pink", "leg_pink"),
            f"{side} connected perching leg",
            overlap=0.28,
        )
        leg_chains.append((side, sign, body_parent, leg_root, ankle, chain))

    toe_chains = []
    for side, sign, _body_parent, _root, ankle, leg_chain in leg_chains:
        toe_paths = (
            (
                "outer",
                ankle,
                (ankle[0] + sign * 0.42, 2.85, ankle[2] + 1.15),
                (ankle[0] + sign * 0.72, 2.55, ankle[2] + 2.05),
            ),
            (
                "inner",
                ankle,
                (ankle[0] - sign * 0.38, 2.82, ankle[2] + 1.25),
                (ankle[0] - sign * 0.56, 2.53, ankle[2] + 2.18),
            ),
            (
                "rear",
                ankle,
                (ankle[0] + sign * 0.18, 2.8, ankle[2] - 1.0),
                (ankle[0] + sign * 0.32, 2.56, ankle[2] - 1.85),
            ),
        )
        for label, start, middle, end in toe_paths:
            chain = builder.add_chain(
                f"toe_{side}_{label}",
                leg_chain.bones[-1],
                (start, middle, end),
                (0.44, 0.29),
                ("leg_pink", "claw_dark"),
                f"{side} {label} gripping toe and claw",
                overlap=0.2,
                depths=(0.42, 0.26),
                longitudinal_axis="z",
            )
            toe_chains.append((side, leg_chain, chain))

    landmarks = []
    for side, _sign, outward_face in (("left", 1, "east"), ("right", -1, "west")):
        landmarks.extend(
            [
                {
                    "name": f"{side}_wing_bar_primary",
                    "cube": f"wing_{side}_1",
                    "face": outward_face,
                    "center_uv": [0.38, 0.48],
                    "size": [18, 6],
                    "color": "#f2efda",
                    "center_color": "#ffffff",
                },
                {
                    "name": f"{side}_wing_bar_secondary",
                    "cube": f"wing_{side}_2",
                    "face": outward_face,
                    "center_uv": [0.32, 0.52],
                    "size": [13, 4],
                    "color": "#d7d3be",
                    "center_color": "#f8f6e5",
                },
            ]
        )

    body_neck_parent, body_neck_joint = nearest_attachment(body_cubes, (0, 12.0, 3.2))
    head_neck_parent, head_neck_joint = nearest_attachment(head_cubes, (0, 13.2, 4.7))
    attachments: list[tuple[str, str, tuple[float, float, float]]] = [
        (body_neck_parent, "neck_bridge", body_neck_joint),
        ("neck_bridge", head_neck_parent, head_neck_joint),
        (head_beak_parent, upper_beak.cubes[0], upper_beak.joints[0]),
        (head_beak_parent, lower_beak.cubes[0], lower_beak.joints[0]),
        (body_tail_parent, tail_chain.cubes[0], tail_chain.joints[0]),
    ]
    attachments.extend(upper_beak.attachments)
    attachments.extend(lower_beak.attachments)
    attachments.extend(tail_chain.attachments)
    for _side, _sign, body_parent, chain in wing_chains:
        attachments.append((body_parent, chain.cubes[0], chain.joints[0]))
        attachments.extend(chain.attachments)
    for side, _sign, body_parent, leg_root, _ankle, chain in leg_chains:
        attachments.append((body_parent, cuff_names[side], leg_root))
        attachments.append((cuff_names[side], chain.cubes[0], leg_root))
        attachments.extend(chain.attachments)
    for _side, leg_chain, chain in toe_chains:
        attachments.append((leg_chain.cubes[-1], chain.cubes[0], chain.joints[0]))
        attachments.extend(chain.attachments)

    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    spec = {
        "schema_version": 1,
        "id": "american_goldfinch",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 3072,
            "height": 3072,
        },
        "subject": {
            "type": "bird",
            "description": (
                "Native volumetric male American goldfinch with rounded yellow body, "
                "black cap and barred folded wings, pointed bill, tapered tail, and gripping feet"
            ),
            "symmetry": "bilateral",
            "uncertainties": [
                "The supplied photograph is one cropped side view; far-side markings and tail length are conservative bilateral inference",
                "The source-facing silhouette metric excludes legs because the reference foot is occluded by a branch and the tail is cropped",
                "No projected photograph skin is used; hidden surfaces use semantic pixel materials",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [60, 100],
            "identity_features": [
                "rounded lemon-yellow breast and pale rump",
                "small head with black breeding cap and paired dark eyes",
                "short pointed peach-and-gold conical bill",
                "separate bilateral black folded wings with white bars",
                "connected tapered black tail fan",
                "two thin pink legs with six gripping toes and dark claws",
            ],
            "required_views": [
                "front", "back", "left", "right", "top", "isometric",
                "left-head-closeup", "right-head-closeup", "wing-joints", "feet-joints",
            ],
            "review_targets": [
                "bird profile", "head-to-body ratio", "cap and bill", "wing bars",
                "bilateral depth", "wing attachment", "leg and toe attachment",
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
        "landmarks": landmarks,
        "collision": {"width": 0.75, "height": 1.15, "eye_height": 1.0},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "greedy-ellipsoid-articulated-bird-v1",
            "source_mesh": None,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z bill/front, X bilateral width, Y up",
            "single_view_hidden_geometry": "bilateral_semantic_inference_not_observed",
            "feature_inventory": {
                "body_volumes": len(body_cubes),
                "head_volumes": len(head_cubes),
                "cap_volumes": 2,
                "eyes": 2,
                "beak_segments": len(upper_beak.cubes) + len(lower_beak.cubes),
                "wing_chains": len(wing_chains),
                "wing_segments": sum(len(chain.cubes) for *_, chain in wing_chains),
                "raised_white_wing_patches": len(wing_patch_names) * 2,
                "wing_bar_landmarks": len(landmarks),
                "tail_segments": len(tail_chain.cubes),
                "leg_chains": len(leg_chains),
                "leg_segments": sum(len(chain.cubes) for *_, chain in leg_chains),
                "toe_chains": len(toe_chains),
                "toe_and_claw_segments": sum(len(chain.cubes) for *_, chain in toe_chains),
            },
            "body_ellipsoid": {
                "center": [0, 10.5, -1.0],
                "radii": [4.65, 5.25, 8.1],
                "subdivisions": list(body_volume.grid_shape),
                "exponent": 2.15,
                "occupied_voxels": body_volume.occupied_voxels,
                "greedy_cuboids": len(body_volume.cubes),
            },
            "head_ellipsoid": {
                "center": [0, 14.3, 5.7],
                "radii": [3.05, 3.15, 3.5],
                "subdivisions": list(head_volume.grid_shape),
                "exponent": 2.1,
                "occupied_voxels": head_volume.occupied_voxels,
                "greedy_cuboids": len(head_volume.cubes),
            },
            "attachment_contract": {
                "method": "declared-shared-joints-tested-against-oriented-cuboids",
                "endpoint_overlap": 0.2,
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
