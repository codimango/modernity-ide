#!/usr/bin/env python3
"""Author the Cycle 5 volumetric Tomato Devil benchmark model."""

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
    normal_rotation,
    point_to_cuboid_margin,
    segment_cube,
)


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "benchmarks" / "references" / "05-tomato-devil.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "a14835e56a9e35dbc01a532e2170d47a7f32c38476041a58ce716e017b31f651"


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "dither",
    scale: int = 3,
) -> dict[str, Any]:
    """Create one crisp deterministic pixel material."""
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
) -> dict[str, Any]:
    """Create one semantic cuboid without source-image projection."""
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


def main() -> None:
    """Write a deep native model with radial eyes and eight connected arms."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Tomato Devil reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (492, 764):
            raise ValueError(f"unexpected Tomato Devil reference size: {opened.size}")

    materials = {
        "tomato": material("#c65b57", "#873e45", "#e98273", "dither", 4),
        "tomato_dark": material("#73313a", "#3d1823", "#a94a4d", "dither", 2),
        "tomato_light": material("#cf6258", "#8c3b42", "#ef9277", "dither", 3),
        "mouth": material("#431b26", "#1f1018", "#6a2934", "gradient", 2),
        "tooth": material("#dcd6a2", "#88855f", "#f6efc2", "dither", 2),
        "sclera": material("#e1b99d", "#a87666", "#f4dac0", "gradient", 3),
        "iris": material("#c54e50", "#6d272e", "#eb7771", "solid", 1),
        "eye_stalk": material("#6d343b", "#32181f", "#ae5555", "dither", 2),
        "limb": material("#c29b7e", "#795c50", "#e2c3a3", "gradient", 3),
        "limb_shadow": material("#a47a65", "#62493f", "#cfaa8b", "gradient", 3),
        "stem": material("#4b8245", "#203d29", "#87b468", "stripes", 2),
        "stem_dark": material("#315c35", "#172b20", "#669459", "dither", 2),
    }

    builder = SemanticModelBuilder()
    builder.add_bone("body", "root", (0, 26.75, 0))
    builder.add_bone("mouth", "body", (0, 24.25, 12.5))
    builder.add_bone("stem_core", "body", (0, 39.0, 0))

    body_volume = ellipsoid_cuboids(
        "body_volume",
        "body",
        (-0.1, 26.8, 0.1),
        (12.6, 12.8, 12.5),
        (14, 16, 12),
        "greedy solid tomato ellipsoid",
        "tomato",
        max_cuboids=64,
        exponent=2.0,
    )
    body_cubes = list(body_volume.cubes)
    for body_cube in body_cubes:
        builder.add_cube(body_cube)

    def body_attachment(point: tuple[float, float, float]) -> tuple[str, tuple[float, float, float]]:
        """Resolve an intended surface anchor into the nearest occupied body block."""
        containing = [
            (point_to_cuboid_margin(body_cube, point), body_cube)
            for body_cube in body_cubes
            if point_to_cuboid_margin(body_cube, point) >= 0
        ]
        if containing:
            deepest_margin, deepest_cube = max(containing, key=lambda item: item[0])
            if deepest_margin >= 0.2:
                return deepest_cube["name"], point
        best: tuple[float, dict[str, Any], tuple[float, float, float]] | None = None
        for body_cube in body_cubes:
            center = body_cube["center"]
            size = body_cube["size"]
            clamped = tuple(
                max(
                    float(center[axis]) - float(size[axis]) / 2 + 0.2,
                    min(
                        float(center[axis]) + float(size[axis]) / 2 - 0.2,
                        point[axis],
                    ),
                )
                for axis in range(3)
            )
            distance = sum((clamped[axis] - point[axis]) ** 2 for axis in range(3))
            candidate = (distance, body_cube, clamped)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None:
            raise ValueError("ellipsoid contains no attachment cuboid")
        return best[1]["name"], best[2]

    # A narrow, pinched fleshy seam rather than a rectangular open slot.
    builder.add_cube(box("mouth_cavity", "mouth", (0, 24.25, 13.05), (0.68, 13.5, 0.8), "narrow pinched vertical mouth seam", "mouth", rotation=(0, 0, -1)))
    builder.add_cube(box("mouth_left_upper_lip", "mouth", (-0.49, 27.6, 13.0), (0.5, 6.7, 1.0), "bowed left upper lip", "tomato_dark", rotation=(0, 0, -5)))
    builder.add_cube(box("mouth_left_lower_lip", "mouth", (-0.43, 20.9, 13.0), (0.46, 6.7, 1.0), "bowed left lower lip", "tomato_dark", rotation=(0, 0, 4)))
    builder.add_cube(box("mouth_right_upper_lip", "mouth", (0.49, 27.6, 13.0), (0.5, 6.7, 1.0), "bowed right upper lip", "tomato_dark", rotation=(0, 0, 5)))
    builder.add_cube(box("mouth_right_lower_lip", "mouth", (0.43, 20.9, 13.0), (0.46, 6.7, 1.0), "bowed right lower lip", "tomato_dark", rotation=(0, 0, -4)))
    tooth_rows = (30.0, 27.2, 24.25, 21.2, 18.4)
    for index, y in enumerate(tooth_rows, start=1):
        side = -1 if index % 2 else 1
        builder.add_cube(
            box(
                f"tooth_{index}",
                "mouth",
                (side * (0.15 if index in {1, 5} else 0.22), y, 13.7),
                (0.42 if index in {1, 5} else 0.55, 0.72 if index in {1, 5} else 0.9, 0.55),
                f"uneven zipper tooth {index}",
                "tooth",
                rotation=(0, 0, side * (5 if index % 3 else 10)),
            )
        )

    builder.add_cube(box("stem_hub", "stem_core", (0, 39.2, -0.2), (3.4, 2.8, 3.2), "green stem hub", "stem_dark", rotation=(0, 0, 4)))
    stem_paths = (
        ((-3.5, 40.0, 0.0), (-8.2, 41.2, 0.0)),
        ((-2.2, 40.7, 0.5), (-4.8, 43.2, 1.4)),
        ((0.0, 41.2, 0.0), (0.0, 43.2, 0.0)),
        ((2.8, 40.7, 0.4), (6.0, 43.2, 0.8)),
        ((4.0, 40.0, -0.5), (8.8, 41.2, -0.8)),
        ((0.8, 40.0, -2.8), (1.6, 41.2, -5.8)),
    )
    stem_chains = []
    for index, (middle, tip) in enumerate(stem_paths, start=1):
        stem_chains.append(
            builder.add_chain(
                f"stem_leaf_{index}",
                "stem_core",
                ((0, 39.2, -0.2), middle, tip),
                (2.1 if index != 3 else 2.35, 1.15),
                "stem",
                "tapered flat stem leaf",
                overlap=0.35,
                depths=(0.6, 0.35),
                longitudinal_axis="z",
            )
        )

    # Ten deliberately asymmetric protruding eyes, matching the canonical
    # count and broad 2-D constellation while providing real stalk depth.
    eye_data = (
        ("upper_left_edge", "auto", (-5.8, 33.75, 7.0), (-7.1, 36.25, 11.3), 2.5, (-0.18, 0.08, 1.0)),
        ("upper_left", "auto", (-7.0, 30.75, 7.0), (-8.3, 32.5, 11.8), 2.8, (-0.14, 0.02, 1.0)),
        ("upper_center", "auto", (-0.8, 30.75, 10.0), (-0.2, 33.5, 14.3), 3.7, (0.0, 0.08, 1.0)),
        ("center_right", "auto", (3.5, 28.25, 10.7), (4.7, 30.75, 15.8), 4.8, (0.08, 0.02, 1.0)),
        ("upper_right_edge", "auto", (6.5, 33.75, 7.0), (9.3, 36.25, 11.8), 2.4, (0.18, 0.08, 1.0)),
        ("right_edge", "auto", (9.0, 27.75, 7.5), (11.5, 30.25, 11.3), 3.4, (0.32, 0.0, 1.0)),
        ("lower_right", "auto", (6.0, 22.75, 8.5), (7.6, 25.0, 12.8), 2.6, (0.14, -0.04, 1.0)),
        ("center_left", "auto", (-4.0, 24.25, 10.2), (-5.2, 27.25, 15.8), 4.5, (-0.08, 0.0, 1.0)),
        ("left_edge", "auto", (-9.0, 23.75, 7.5), (-11.5, 25.75, 11.3), 3.2, (-0.32, 0.0, 1.0)),
        ("lower_left", "auto", (-6.0, 18.75, 7.0), (-7.4, 21.0, 10.8), 3.1, (-0.2, -0.05, 1.0)),
    )
    eye_chains = []
    landmarks = []
    for index, (label, _parent_cube, intended_anchor, center, diameter, outward) in enumerate(eye_data, start=1):
        parent_cube, anchor = body_attachment(intended_anchor)
        chain = builder.add_chain(
            f"eye_stalk_{index}",
            "body",
            (anchor, center),
            max(1.0, min(1.6, diameter * 0.34)),
            "eye_stalk",
            f"{label} eye stalk",
            overlap=0.3,
        )
        eye_bone = f"eye_{index}"
        builder.add_bone(eye_bone, chain.bones[-1], center)
        outward_length = sum(value * value for value in outward) ** 0.5
        normal = tuple(value / outward_length for value in outward)
        eye_rotation = tuple(normal_rotation(normal))
        builder.add_cube(
            box(
                f"eye_bulb_{index}",
                eye_bone,
                center,
                (
                    diameter * 0.7,
                    diameter * 0.7,
                    diameter * 0.84,
                ),
                f"{label} cream eyeball",
                "sclera",
                rotation=eye_rotation,
                origin=center,
            )
        )
        builder.add_cube(
            box(
                f"eye_band_horizontal_{index}",
                eye_bone,
                center,
                (diameter, diameter * 0.58, diameter * 0.78),
                f"{label} horizontal eyeball band",
                "sclera",
                rotation=eye_rotation,
                origin=center,
            )
        )
        eye_band_names = [f"eye_band_horizontal_{index}"]
        if index in {3, 4, 6, 8}:
            builder.add_cube(
                box(
                    f"eye_band_vertical_{index}",
                    eye_bone,
                    center,
                    (diameter * 0.58, diameter, diameter * 0.78),
                    f"{label} vertical eyeball band",
                    "sclera",
                    rotation=eye_rotation,
                    origin=center,
                )
            )
            eye_band_names.append(f"eye_band_vertical_{index}")
        iris_center = tuple(
            center[axis] + normal[axis] * diameter * 0.36 for axis in range(3)
        )
        iris_size = max(0.85, diameter * 0.38)
        builder.add_cube(
            box(
                f"iris_{index}",
                eye_bone,
                iris_center,
                (iris_size, iris_size, 0.6),
                f"{label} red iris",
                "iris",
                rotation=eye_rotation,
                origin=iris_center,
            )
        )
        landmarks.append(
            {
                "name": f"pupil_{index}",
                "cube": f"iris_{index}",
                "face": "south",
                "center_uv": [0.5, 0.5],
                "size": [1, 1],
                "color": "#25181a",
                "center_color": "#25181a",
            }
        )
        eye_chains.append(
            (parent_cube, chain, center, diameter, iris_center, normal, eye_band_names)
        )

    # Eight long human-like arms emerge around the lower perimeter. The first
    # two spans are a visibly bent upper arm and forearm; the short third span
    # is a wrist entering a broad palm with four individually splayed fingers.
    arm_paths = (
        ("back_left", ((-4.5, 16.5, -5.0), (-8.5, 9.5, -8.0), (-8.2, 1.8, -7.0), (-7.2, 0.4, -8.0)), "limb_shadow"),
        ("outer_left", ((-8.0, 17.0, -1.0), (-11.5, 9.5, -2.5), (-13.0, 1.8, -0.5), (-13.7, 0.4, 1.0)), "limb"),
        ("front_left", ((-5.5, 16.5, 4.5), (-9.5, 9.3, 7.5), (-11.5, 1.8, 7.5), (-12.0, 0.4, 8.8)), "limb"),
        ("inner_left", ((-2.5, 14.8, 4.0), (-4.0, 7.0, 7.5), (-5.0, 1.5, 8.0), (-5.0, 0.4, 10.0)), "limb"),
        ("inner_right", ((2.0, 14.8, 4.2), (3.8, 7.0, 7.7), (4.8, 1.5, 8.2), (4.8, 0.4, 10.2)), "limb"),
        ("front_right", ((5.5, 16.5, 4.5), (9.5, 9.3, 7.5), (11.5, 1.8, 7.5), (12.0, 0.4, 8.8)), "limb"),
        ("outer_right", ((8.0, 17.0, -1.0), (11.5, 9.5, -2.5), (13.0, 1.8, -0.5), (13.7, 0.4, 1.0)), "limb"),
        ("back_right", ((4.5, 16.5, -5.0), (8.5, 9.5, -8.0), (8.2, 1.8, -7.0), (7.2, 0.4, -8.0)), "limb_shadow"),
    )
    arm_chains = []
    finger_links = []
    palm_links = []
    for index, (label, intended_points, limb_material) in enumerate(arm_paths, start=1):
        parent_cube, root_joint = body_attachment(intended_points[0])
        points = (root_joint, *intended_points[1:])
        chain = builder.add_chain(
            f"arm_{index}",
            "body",
            points,
            (2.15, 1.6, 1.55),
            (limb_material, limb_material, limb_material),
            f"{label} human arm",
            overlap=0.42,
        )
        arm_chains.append((parent_cube, chain))
        hand = points[-1]
        wrist = points[-2]
        horizontal = (hand[0] - wrist[0], 0.0, hand[2] - wrist[2])
        horizontal_length = math.sqrt(horizontal[0] ** 2 + horizontal[2] ** 2)
        if horizontal_length <= 1e-6:
            raise ValueError(f"arm {index} requires a horizontal hand direction")
        hand_direction = (
            horizontal[0] / horizontal_length,
            0.0,
            horizontal[2] / horizontal_length,
        )
        lateral = (hand_direction[2], 0.0, -hand_direction[0])
        palm_bone = f"arm_{index}_palm"
        builder.add_bone(palm_bone, chain.bones[-1], hand)
        palm_tip = tuple(
            hand[axis] + hand_direction[axis] * 2.6 for axis in range(3)
        )
        builder.add_cube(
            segment_cube(
                palm_bone,
                palm_bone,
                hand,
                palm_tip,
                (3.0, 0.8),
                f"{label} flat human palm",
                limb_material,
                overlap=0.2,
                longitudinal_axis="z",
            )
        )
        palm_links.append((chain.cubes[-1], palm_bone, hand))
        finger_offsets = (-1.05, -0.35, 0.35, 1.05)
        for finger_index, lateral_offset in enumerate(finger_offsets, start=1):
            finger_base = tuple(
                palm_tip[axis] + lateral[axis] * lateral_offset
                for axis in range(3)
            )
            splayed = tuple(
                hand_direction[axis] + lateral[axis] * lateral_offset * 0.1
                for axis in range(3)
            )
            splayed_length = math.sqrt(sum(value * value for value in splayed))
            finger_direction = tuple(value / splayed_length for value in splayed)
            finger_length = 2.35 + 0.2 * (finger_index % 2)
            finger_tip = tuple(
                finger_base[axis] + finger_direction[axis] * finger_length
                for axis in range(3)
            )
            finger_name = f"arm_{index}_finger_{finger_index}"
            builder.add_cube(
                segment_cube(
                    finger_name,
                    palm_bone,
                    finger_base,
                    finger_tip,
                    (0.5, 0.48),
                    f"{label} splayed hand finger {finger_index}",
                    limb_material,
                    overlap=0.18,
                    longitudinal_axis="z",
                )
            )
            finger_links.append((palm_bone, finger_name, finger_base))

    stem_parent, stem_joint = body_attachment((0, 39.0, -0.2))
    attachment_links = [(stem_parent, "stem_hub", stem_joint)]
    for chain in stem_chains:
        attachment_links.append(("stem_hub", chain.cubes[0], chain.joints[0]))
        attachment_links.extend(chain.attachments)
    for index, (
        parent_cube,
        chain,
        center,
        diameter,
        iris_center,
        normal,
        eye_band_names,
    ) in enumerate(eye_chains, start=1):
        attachment_links.append((parent_cube, chain.cubes[0], chain.joints[0]))
        attachment_links.extend(chain.attachments)
        attachment_links.append((chain.cubes[-1], f"eye_bulb_{index}", chain.joints[-1]))
        attachment_links.append(
            (
                f"eye_bulb_{index}",
                f"iris_{index}",
                tuple(iris_center[axis] - normal[axis] * 0.2 for axis in range(3)),
            )
        )
        attachment_links.extend(
            (f"eye_bulb_{index}", band_name, center)
            for band_name in eye_band_names
        )
    for parent_cube, chain in arm_chains:
        attachment_links.append((parent_cube, chain.cubes[0], chain.joints[0]))
        attachment_links.extend(chain.attachments)
    attachment_links.extend(palm_links)
    attachment_links.extend(finger_links)

    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    spec = {
        "schema_version": 1,
        "id": "tomato_devil",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 492,
            "height": 764,
        },
        "subject": {
            "type": "mob",
            "description": "Volumetric Tomato Devil with ten stalked eyes, a vertical toothed mouth, leafy crown, and eight human-like arms",
            "symmetry": "asymmetric",
            "uncertainties": [
                "The single frontal illustration hides the exact back-eye arrangement",
                "Rear arm crossings are inferred conservatively from visible joints",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [170, 192],
            "identity_features": [
                "deep round red tomato globe",
                "ten protruding cream eyes with red irises",
                "pinched vertical mouth with five irregular teeth",
                "six-leaf green stem crown",
                "eight long grounded human arms with palms and fingers",
            ],
            "required_views": ["front", "back", "left", "right", "top", "isometric", "eye-closeup", "mouth-closeup", "arm-joint-closeup"],
            "review_targets": ["round silhouette", "true body depth", "eye constellation", "vertical mouth", "arm attachment", "ground contact"],
        },
        "geometry": {"precision": 16},
        "texture": {
            "density": 2,
            "palette_size": 32,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": landmarks,
        "collision": {"width": 1.45, "height": 2.45, "eye_height": 2.05},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "greedy-ellipsoid-connected-radial-v2",
            "source_mesh": None,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "feature_inventory": {
                "body_volumes": len(body_cubes),
                "eye_assemblies": len(eye_chains),
                "eye_stalk_segments": sum(len(chain.cubes) for _, chain, *_ in eye_chains),
                "red_irises": len(eye_chains),
                "rounded_eye_bands": sum(len(entry[-1]) for entry in eye_chains),
                "pupil_landmarks": len(landmarks),
                "arm_chains": len(arm_chains),
                "arm_segments": sum(len(chain.cubes) for _, chain in arm_chains),
                "arm_palms": len(arm_chains),
                "grounded_fingers": len(finger_links),
                "stem_leaves": len(stem_chains),
                "stem_leaf_segments": sum(len(chain.cubes) for chain in stem_chains),
                "mouth_teeth": len(tooth_rows),
            },
            "ellipsoid": {
                "center": [-0.1, 26.8, 0.1],
                "radii": [12.6, 12.8, 12.5],
                "subdivisions": list(body_volume.grid_shape),
                "exponent": 2.0,
                "occupied_voxels": body_volume.occupied_voxels,
                "greedy_cuboids": len(body_volume.cubes),
                "voxel_size": list(body_volume.voxel_size),
            },
            "attachment_contract": {
                "method": "declared-shared-joints-tested-against-oriented-cuboids",
                "endpoint_overlap": 0.3,
            },
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachment_links
            ],
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
