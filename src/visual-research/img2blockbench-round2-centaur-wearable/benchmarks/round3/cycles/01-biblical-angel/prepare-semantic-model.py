#!/usr/bin/env python3
"""Author a fully volumetric, many-eyed angel from the Round 3 reference."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from semantic_geometry import SemanticModelBuilder, audit_attachments


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "round3-inputs" / "biblically-accurate-angel.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "1b4e05b4fa70f51fa37d4eb054b7355274fcfd576936402ca7db1515b391826c"

Point = tuple[float, float, float]


def material(base: str, shade: str, highlight: str) -> dict[str, Any]:
    """Create a restrained Minecraft material without stochastic texture."""
    return {
        "base": base,
        "shade": shade,
        "highlight": highlight,
        "pattern": "solid",
        "pattern_scale": 1,
    }


def box(
    name: str,
    bone: str,
    center: Point,
    size: Point,
    role: str,
    material_name: str,
    *,
    rotation: Point = (0.0, 0.0, 0.0),
    origin: Point | None = None,
    faces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one semantic native cuboid."""
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


def mirrored(point: Point, side: str) -> Point:
    """Mirror a left-authored point across the central X plane."""
    sign = -1.0 if side == "left" else 1.0
    return abs(point[0]) * sign, point[1], point[2]


def midpoint(first: Point, second: Point, fraction: float = 0.55) -> Point:
    """Return a stable intermediate feather joint."""
    return tuple(
        first[axis] + (second[axis] - first[axis]) * fraction
        for axis in range(3)
    )  # type: ignore[return-value]


def main() -> None:
    """Write a six-wing, front/back-eyed angel with substantial Z depth."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected biblical angel reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.mode != "RGBA" or opened.size != (744, 714):
            raise ValueError(f"unexpected angel reference: {opened.mode} {opened.size}")

    materials = {
        "ivory": material("#e8ddd5", "#b9acad", "#fff8ef"),
        "ivory_light": material("#f5eee7", "#cec2bd", "#ffffff"),
        "feather_shadow": material("#c6b7b7", "#897a80", "#e5d9d3"),
        "rose": material("#c58e88", "#805051", "#e4b8ae"),
        "rose_dark": material("#8e5656", "#4d3035", "#bb7770"),
        "rust": material("#8c443f", "#48252a", "#bd7066"),
        "sclera": material("#f1ede7", "#c2b7b4", "#ffffff"),
        "sclera_shadow": material("#d5c7c2", "#9f8887", "#eee4dd"),
        "iris_cyan": material("#63c1c8", "#2b737c", "#a8edf0"),
        "iris_dark": material("#2c7782", "#153b47", "#63b8c0"),
        "pupil": material("#17232a", "#070b10", "#3c5660"),
        "gold": material("#d6b67c", "#8f7246", "#f3dca8"),
    }

    builder = SemanticModelBuilder(pivot=(0.0, 38.0, 0.0))
    builder.add_bone("body", "root", (0.0, 38.0, 0.0))
    attachments: list[tuple[str, str, Point]] = []

    def add_attached(
        cube: dict[str, Any], parent: str | None, joint: Point | None = None
    ) -> str:
        builder.add_cube(cube)
        if parent is not None:
            if joint is None:
                raise ValueError("attached cubes require a joint")
            attachments.append((parent, str(cube["name"]), joint))
        return str(cube["name"])

    # A deep sacred core replaces the flat rectangular torso suggested by the
    # frontal illustration. Staggered volumes make the entity readable from
    # side, back, and top views without pretending those surfaces were observed.
    add_attached(
        box(
            "body_core",
            "body",
            (0.0, 39.0, 0.0),
            (18.0, 14.0, 14.0),
            "deep central many-eyed angel body",
            "ivory",
        ),
        None,
    )
    body_parts = (
        (
            box(
                "front_body_shell",
                "body",
                (0.0, 39.0, 9.5),
                (22.0, 10.0, 6.0),
                "projecting faceted front body shell",
                "ivory_light",
            ),
            (0.0, 39.0, 7.0),
        ),
        (
            box(
                "back_body_shell",
                "body",
                (0.0, 39.0, -9.5),
                (22.0, 10.0, 6.0),
                "projecting faceted rear body shell",
                "feather_shadow",
            ),
            (0.0, 39.0, -7.0),
        ),
        (
            box(
                "left_body_shell",
                "body",
                (-10.5, 39.0, 0.0),
                (6.0, 14.0, 13.0),
                "left rounded-step body shell",
                "ivory",
            ),
            (-9.0, 39.0, 0.0),
        ),
        (
            box(
                "right_body_shell",
                "body",
                (10.5, 39.0, 0.0),
                (6.0, 14.0, 13.0),
                "right rounded-step body shell",
                "ivory_light",
            ),
            (9.0, 39.0, 0.0),
        ),
        (
            box(
                "body_upper_crown",
                "body",
                (0.0, 49.0, -0.5),
                (16.0, 7.0, 15.0),
                "upper crown volume behind the ocular band",
                "ivory_light",
            ),
            (0.0, 45.5, 0.0),
        ),
        (
            box(
                "body_lower_shroud",
                "body",
                (0.0, 28.5, -0.5),
                (16.0, 9.0, 15.0),
                "lower torn sacred shroud volume",
                "feather_shadow",
            ),
            (0.0, 32.2, 0.0),
        ),
        (
            box(
                "front_eye_band",
                "body",
                (0.0, 44.0, 12.0),
                (17.0, 6.0, 4.0),
                "projecting frontal crown for seven eyes",
                "rose",
            ),
            (0.0, 44.0, 11.0),
        ),
        (
            box(
                "back_eye_band",
                "body",
                (0.0, 43.0, -12.0),
                (13.0, 7.0, 4.0),
                "fully modeled rear eye crown",
                "rose",
            ),
            (0.0, 43.0, -11.0),
        ),
        (
            box(
                "front_left_crown_wrap",
                "body",
                (-11.0, 43.8, 10.5),
                (10.0, 5.5, 7.0),
                "front-left angled ocular crown segment",
                "rose",
                rotation=(0.0, -38.0, 0.0),
            ),
            (-8.5, 43.5, 9.5),
        ),
        (
            box(
                "front_right_crown_wrap",
                "body",
                (11.0, 43.8, 10.5),
                (10.0, 5.5, 7.0),
                "front-right angled ocular crown segment",
                "rose",
                rotation=(0.0, 38.0, 0.0),
            ),
            (8.5, 43.5, 9.5),
        ),
        (
            box(
                "rear_left_crown_wrap",
                "body",
                (-11.0, 42.8, -10.5),
                (10.0, 5.5, 7.0),
                "rear-left angled ocular crown segment",
                "rose_dark",
                rotation=(0.0, 38.0, 0.0),
            ),
            (-8.5, 42.5, -9.5),
        ),
        (
            box(
                "rear_right_crown_wrap",
                "body",
                (11.0, 42.8, -10.5),
                (10.0, 5.5, 7.0),
                "rear-right angled ocular crown segment",
                "rose_dark",
                rotation=(0.0, -38.0, 0.0),
            ),
            (8.5, 42.5, -9.5),
        ),
        (
            box(
                "left_side_temple",
                "body",
                (-13.7, 40.5, 0.0),
                (4.0, 9.0, 10.0),
                "left volumetric eye temple",
                "rose",
            ),
            (-12.0, 40.5, 0.0),
        ),
        (
            box(
                "right_side_temple",
                "body",
                (13.7, 40.5, 0.0),
                (4.0, 9.0, 10.0),
                "right volumetric eye temple",
                "rose",
            ),
            (12.0, 40.5, 0.0),
        ),
        (
            box(
                "top_eye_plinth",
                "body",
                (0.0, 51.5, 0.0),
                (9.0, 4.0, 8.0),
                "top-facing eye plinth",
                "rose_dark",
            ),
            (0.0, 50.0, 0.0),
        ),
    )
    for cube, joint in body_parts:
        parent_by_name = {
            "top_eye_plinth": "body_upper_crown",
            "front_eye_band": "front_body_shell",
            "back_eye_band": "back_body_shell",
            "left_side_temple": "left_body_shell",
            "right_side_temple": "right_body_shell",
            "front_left_crown_wrap": "front_body_shell",
            "front_right_crown_wrap": "front_body_shell",
            "rear_left_crown_wrap": "back_body_shell",
            "rear_right_crown_wrap": "back_body_shell",
        }
        parent = parent_by_name.get(str(cube["name"]), "body_core")
        add_attached(cube, parent, joint)

    landmarks: list[dict[str, Any]] = []
    eye_records: list[dict[str, Any]] = []

    def add_axis_eye(
        name: str,
        parent_cube: str,
        bone: str,
        center: Point,
        outward: Point,
        scale: float,
        face: str,
    ) -> None:
        """Add a three-layer geometric eye facing one world axis."""
        axis = max(range(3), key=lambda index: abs(outward[index]))
        sign = 1.0 if outward[axis] >= 0 else -1.0
        sizes = [6.0 * scale, 4.4 * scale, 2.3 * scale]
        depth_sizes = [3.0 * scale, 1.6 * scale, 1.0 * scale]
        white_size = list(sizes)
        iris_size = [2.6 * scale, 2.6 * scale, 1.5 * scale]
        pupil_size = [1.15 * scale, 1.3 * scale, 0.8 * scale]
        # The default dimensions describe an eye normal to Z. Reorder them for
        # side and top eyes while retaining a deep sclera/iris stack.
        if axis == 0:
            white_size = [depth_sizes[0], sizes[1], sizes[0]]
            iris_size = [depth_sizes[1], 2.6 * scale, 2.6 * scale]
            pupil_size = [depth_sizes[2], 1.3 * scale, 1.15 * scale]
        elif axis == 1:
            white_size = [sizes[0], depth_sizes[0], sizes[1]]
            iris_size = [2.6 * scale, depth_sizes[1], 2.6 * scale]
            pupil_size = [1.15 * scale, depth_sizes[2], 1.3 * scale]
        white_center = list(center)
        joint = list(center)
        white_center[axis] += sign * 0.7 * scale
        joint[axis] -= sign * 0.35 * scale
        white_name = f"{name}_sclera"
        add_attached(
            box(
                white_name,
                bone,
                tuple(white_center),  # type: ignore[arg-type]
                tuple(white_size),  # type: ignore[arg-type]
                f"{name.replace('_', ' ')} raised sclera",
                "sclera" if scale >= 0.75 else "sclera_shadow",
            ),
            parent_cube,
            tuple(joint),  # type: ignore[arg-type]
        )
        iris_center = list(white_center)
        iris_center[axis] += sign * 1.4 * scale
        iris_name = f"{name}_iris"
        add_attached(
            box(
                iris_name,
                bone,
                tuple(iris_center),  # type: ignore[arg-type]
                tuple(iris_size),  # type: ignore[arg-type]
                f"{name.replace('_', ' ')} cyan iris",
                "iris_cyan",
            ),
            white_name,
            tuple(
                white_center[index]
                + (sign * 0.8 * scale if index == axis else 0.0)
                for index in range(3)
            ),  # type: ignore[arg-type]
        )
        pupil_center = list(iris_center)
        pupil_center[axis] += sign * 0.7 * scale
        pupil_name = f"{name}_pupil"
        add_attached(
            box(
                pupil_name,
                bone,
                tuple(pupil_center),  # type: ignore[arg-type]
                tuple(pupil_size),  # type: ignore[arg-type]
                f"{name.replace('_', ' ')} dark pupil",
                "pupil",
            ),
            iris_name,
            tuple(
                iris_center[index]
                + (sign * 0.35 * scale if index == axis else 0.0)
                for index in range(3)
            ),  # type: ignore[arg-type]
        )
        landmarks.append(
            {
                "name": f"{name}_glint",
                "cube": pupil_name,
                "face": face,
                "center_uv": [0.35, 0.32],
                "size": [1, 1],
                "color": "#f5ffff",
                "center_color": "#f5ffff",
            }
        )
        eye_records.append(
            {
                "name": name,
                "orientation": face,
                "center": list(center),
                "cubes": [white_name, iris_name, pupil_name],
            }
        )

    # Seven front eyes form the defining crown, with a deliberately oversized
    # central eye. Five rear eyes and three axial eyes prevent a one-view mask.
    front_positions = (-13.0, -9.0, -5.8, 0.0, 5.8, 9.0, 13.0)
    for index, x in enumerate(front_positions):
        scale = 2.25 if x == 0.0 else (0.82 if abs(x) < 10 else 0.62)
        parent_cube = (
            "front_left_crown_wrap"
            if index <= 1
            else "front_right_crown_wrap"
            if index >= 5
            else "front_eye_band"
        )
        add_axis_eye(
            f"front_eye_{index + 1}",
            parent_cube,
            "body",
            (x, 44.2 + (1.4 if x == 0 else 0.0), 13.2),
            (0.0, 0.0, 1.0),
            scale,
            "south",
        )
    # Raised lid bars make the large central eye read as the hierarchy
    # anchor rather than another same-sized square in the crown.
    for lid_name, center, size in (
        ("central_upper_lid", (0.0, 49.5, 16.0), (13.5, 1.5, 2.0)),
        ("central_lower_lid", (0.0, 41.8, 16.0), (13.5, 1.5, 2.0)),
    ):
        add_attached(
            box(
                lid_name,
                "body",
                center,
                size,
                "raised rose frame around the dominant central eye",
                "rose_dark",
            ),
            "front_eye_4_sclera",
            center,
        )
    for index, x in enumerate((-9.5, -4.8, 0.0, 4.8, 9.5)):
        parent_cube = (
            "rear_left_crown_wrap"
            if index == 0
            else "rear_right_crown_wrap"
            if index == 4
            else "back_eye_band"
        )
        add_axis_eye(
            f"back_eye_{index + 1}",
            parent_cube,
            "body",
            (x, 43.2, -13.2),
            (0.0, 0.0, -1.0),
            0.72 if x else 0.96,
            "north",
        )
    add_axis_eye(
        "left_temple_eye",
        "left_side_temple",
        "body",
        (-14.8, 41.0, 0.0),
        (-1.0, 0.0, 0.0),
        0.92,
        "west",
    )
    add_axis_eye(
        "right_temple_eye",
        "right_side_temple",
        "body",
        (14.8, 41.0, 0.0),
        (1.0, 0.0, 0.0),
        0.92,
        "east",
    )
    add_axis_eye(
        "zenith_eye",
        "top_eye_plinth",
        "body",
        (0.0, 52.6, 0.0),
        (0.0, 1.0, 0.0),
        0.95,
        "up",
    )

    wing_layers = (
        {
            "name": "rear_upper",
            "z": -14.0,
            "points": ((-8.0, 45.0, -6.0), (-13.0, 57.0, -11.0),
                       (-17.5, 71.0, -15.0), (-21.0, 85.0, -18.0)),
            "tips": (
                (1, (-32.0, 82.0, -21.0)),
                (2, (-42.0, 64.0, -18.0)),
                (3, (-40.0, 46.0, -14.0)),
            ),
            "panels": (
                (1, (-30.0, 76.0, -20.0)),
                (3, (-36.0, 51.0, -15.0)),
            ),
            "material": "ivory_light",
            "eye_face": "north",
        },
        {
            "name": "middle",
            "z": 7.5,
            "points": ((-9.0, 43.0, 0.0), (-21.0, 49.0, 4.0),
                       (-34.0, 51.0, 10.0), (-48.0, 47.0, 15.0)),
            "tips": (
                (1, (-44.0, 61.0, 14.0)),
                (2, (-54.0, 44.0, 18.0)),
                (3, (-44.0, 28.0, 19.0)),
            ),
            "panels": (
                (1, (-38.0, 56.0, 13.0)),
                (3, (-42.0, 33.0, 18.0)),
            ),
            "material": "ivory",
            "eye_face": "south",
        },
        {
            "name": "front_lower",
            "z": 16.0,
            "points": ((-8.0, 40.0, 6.0), (-16.0, 32.0, 12.0),
                       (-23.0, 19.0, 18.0), (-27.0, 5.0, 22.0)),
            "tips": (
                (1, (-38.0, 34.0, 19.0)),
                (2, (-44.0, 16.0, 23.0)),
                (3, (-31.0, -4.0, 25.0)),
            ),
            "panels": (
                (1, (-32.0, 30.0, 18.0)),
                (3, (-35.0, 4.0, 24.0)),
            ),
            "material": "feather_shadow",
            "eye_face": "south",
        },
    )
    wing_records: list[dict[str, Any]] = []

    for layer in wing_layers:
        layer_name = str(layer["name"])
        layer_bone = f"{layer_name}_wings"
        builder.add_bone(layer_bone, "body", layer["points"][0])
        for side in ("left", "right"):
            points = tuple(mirrored(point, side) for point in layer["points"])
            spar_name = f"{side}_{layer_name}_spar"
            spar = builder.add_chain(
                spar_name,
                layer_bone,
                points,
                (6.2, 5.3, 4.5),
                ("rose", "feather_shadow", str(layer["material"])),
                f"{side} {layer_name.replace('_', ' ')} load-bearing wing spar",
                overlap=0.7,
                depths=(6.0, 5.2, 4.4),
                longitudinal_axis="z",
            )
            attachments.append(("body_core", spar.cubes[0], points[0]))
            attachments.extend(spar.attachments)
            feather_names: list[str] = []
            feather_profiles: list[dict[str, Any]] = []
            for feather_index, (root_index, authored_tip) in enumerate(layer["tips"], start=1):
                root = points[int(root_index)]
                tip = mirrored(authored_tip, side)
                first_step = midpoint(root, tip, 0.46)
                second_step = midpoint(root, tip, 0.88)
                # A diminishing curve avoids straight extrusions while keeping
                # the terminal third visibly narrower than the two root stages.
                arc_sign = -1.0 if layer_name == "rear_upper" else 1.0
                first_step = (
                    first_step[0], first_step[1] + 1.7,
                    first_step[2] + arc_sign * 1.4,
                )
                second_step = (
                    second_step[0], second_step[1] + 0.7,
                    second_step[2] + arc_sign * 0.55,
                )
                feather_name = f"{side}_{layer_name}_feather_{feather_index}"
                parent_index = min(max(int(root_index) - 1, 0), len(spar.cubes) - 1)
                feather = builder.add_chain(
                    feather_name,
                    spar.bones[parent_index],
                    (root, first_step, second_step, tip),
                    (5.8, 3.0, 1.0),
                    (str(layer["material"]), "ivory_light", "ivory_light"),
                    f"{side} {layer_name.replace('_', ' ')} primary feather {feather_index}",
                    overlap=0.55,
                    depths=(4.8, 2.5, 0.8),
                    longitudinal_axis="z",
                )
                attachments.append((spar.cubes[parent_index], feather.cubes[0], root))
                attachments.extend(feather.attachments)
                feather_names.extend(feather.cubes)
                feather_profiles.append(
                    {
                        "name": feather_name,
                        "segments": list(feather.cubes),
                        "widths": [5.8, 3.0, 1.0],
                        "depths": [4.8, 2.5, 0.8],
                        "terminal_length": round(math.dist(second_step, tip), 6),
                    }
                )

            panel_names: list[str] = []
            panel_profiles: list[dict[str, Any]] = []
            for panel_index, (root_index, authored_tip) in enumerate(
                layer["panels"], start=1
            ):
                root = points[int(root_index)]
                tip = mirrored(authored_tip, side)
                first_step = midpoint(root, tip, 0.42)
                second_step = midpoint(root, tip, 0.90)
                first_step = (first_step[0], first_step[1] + 1.1, first_step[2])
                second_step = (second_step[0], second_step[1] + 0.45, second_step[2])
                panel_name = f"{side}_{layer_name}_overlap_vane_{panel_index}"
                parent_index = min(max(int(root_index) - 1, 0), len(spar.cubes) - 1)
                panel = builder.add_chain(
                    panel_name,
                    spar.bones[parent_index],
                    (root, first_step, second_step, tip),
                    (11.0, 6.0, 1.4) if layer_name != "front_lower" else (9.8, 5.5, 1.2),
                    (str(layer["material"]), "ivory", "ivory_light"),
                    f"{side} {layer_name.replace('_', ' ')} broad overlapping feather vane",
                    overlap=0.75,
                    depths=(5.8, 3.2, 1.0),
                    longitudinal_axis="z",
                )
                attachments.append((spar.cubes[parent_index], panel.cubes[0], root))
                attachments.extend(panel.attachments)
                panel_names.extend(panel.cubes)
                panel_profiles.append(
                    {
                        "name": panel_name,
                        "segments": list(panel.cubes),
                        "widths": (
                            [11.0, 6.0, 1.4]
                            if layer_name != "front_lower"
                            else [9.8, 5.5, 1.2]
                        ),
                        "depths": [5.8, 3.2, 1.0],
                        "terminal_length": round(math.dist(second_step, tip), 6),
                    }
                )

            # One real ocular ornament per wing keeps the many-eye identity
            # without displacing the three-stage feather tips under the 192-cube limit.
            ornament_names: list[str] = []
            for ornament_index, joint_index in enumerate((2,), start=1):
                joint = points[joint_index]
                outward_z = -1.0 if layer["eye_face"] == "north" else 1.0
                parent_index = joint_index - 1
                eye_name = f"{side}_{layer_name}_wing_eye_{ornament_index}"
                before = len(eye_records)
                add_axis_eye(
                    eye_name,
                    spar.cubes[parent_index],
                    spar.bones[parent_index],
                    (joint[0], joint[1], joint[2] + outward_z * 1.1),
                    (0.0, 0.0, outward_z),
                    0.58,
                    str(layer["eye_face"]),
                )
                ornament_names.extend(eye_records[before]["cubes"])
            wing_records.append(
                {
                    "layer": layer_name,
                    "side": side,
                    "depth_center": layer["z"],
                    "sector_sweep_degrees": round(
                        math.degrees(
                            math.atan2(
                                abs(points[-1][2] - points[0][2]),
                                abs(points[-1][0] - points[0][0]),
                            )
                        ),
                        6,
                    ),
                    "spar": list(spar.cubes),
                    "feathers": feather_names,
                    "feather_profiles": feather_profiles,
                    "overlap_vanes": panel_names,
                    "overlap_vane_profiles": panel_profiles,
                    "ocular_ornaments": ornament_names,
                }
            )

    layer_depths = sorted({float(record["depth_center"]) for record in wing_records})
    feature_inventory = {
        "wing_layers": len(layer_depths),
        "bilateral_wings": len(wing_records),
        "wing_spar_segments": sum(len(record["spar"]) for record in wing_records),
        "primary_feathers": sum(len(record["feathers"]) // 3 for record in wing_records),
        "feather_segments": sum(len(record["feathers"]) for record in wing_records),
        "broad_overlap_vanes": sum(
            len(record["overlap_vanes"]) // 3 for record in wing_records
        ),
        "broad_overlap_vane_segments": sum(
            len(record["overlap_vanes"]) for record in wing_records
        ),
        "front_crown_eyes": 7,
        "back_crown_eyes": 5,
        "side_eyes": 2,
        "top_eyes": 1,
        "wing_eyes": 6,
        "total_geometric_eyes": len(eye_records),
        "front_back_depth_bands": len(layer_depths),
    }
    spec = {
        "schema_version": 1,
        "id": "biblical_angel_many_eyed_six_wing",
        "reference": {
            "image": Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix(),
            "sha256": EXPECTED_SHA256,
            "width": 744,
            "height": 714,
        },
        "subject": {
            "type": "mob",
            "description": (
                "A hovering pale many-eyed angel with a seven-eye frontal crown, "
                "fully modeled rear/side/top eyes, and six layered feather wings"
            ),
            "symmetry": "bilateral",
            "uncertainties": [
                "Only one frontal illustration is available; rear eye placement and exact "
                "wing-root topology are conservative agentic-vision inference",
                "The reference is painterly and extremely bright, so the model translates it "
                "to a bounded ivory, rose, rust, and cyan Minecraft palette",
                "Clouds and bloom are environmental effects and are not modeled as anatomy",
                "Source rights are unknown and the ignored reference remains local only",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [180, 192],
            "identity_features": [
                "oversized cyan central eye in a seven-eye frontal crown",
                "five rear crown eyes plus bilateral temple and top eyes",
                "three bilateral wing pairs occupying rear, middle, and front depth bands",
                "eighteen three-stage primary feathers with pointed terminal caps",
                "twelve three-stage broad overlap vanes closing skeletal wing gaps",
                "rear, middle, and lower wings yaw through distinct radial sectors",
                "an eight-segment eye crown wraps continuously around the body",
                "deep central body and staggered wing Z positions that resist pancake views",
                "pale ivory, dusty rose, restrained rust, and cyan Minecraft palette",
            ],
            "required_views": [
                "front", "back", "left", "right", "top", "bottom", "isometric",
                "eye-crown-closeup", "rear-eyes-closeup", "wing-layers-closeup",
                "side-depth-closeup", "wing-tip-closeup", "crown-wrap-closeup",
            ],
            "review_targets": [
                "front-back readability", "side silhouette", "wing-layer separation",
                "eye count", "central-eye hierarchy", "feather taper", "joint continuity",
                "pixel-texture restraint", "all-angle volume",
            ],
        },
        "geometry": {"precision": 20},
        "texture": {
            "density": 1,
            "palette_size": 16,
            "gutter": 1,
            "atlas_size": 1024,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": landmarks,
        "collision": {"width": 3.4, "height": 5.6, "eye_height": 3.8},
        "generation": {
            "lane": "agent-authored-holistic-semantic-volume",
            "algorithm": "single-view-agentic-radial-depth-inference-six-wing-v2",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "single_view_hidden_geometry": "inferred_conservatively_not_observed",
            "holistic_3d_contract": {
                "front_is_not_a_texture_billboard": True,
                "rear_identity_geometry_authored": True,
                "side_identity_geometry_authored": True,
                "top_identity_geometry_authored": True,
                "wing_depth_layers": layer_depths,
                "minimum_required_depth_to_width": 0.40,
                "minimum_required_body_depth_to_width": 0.85,
                "minimum_required_side_to_front_silhouette_area": 0.60,
                "minimum_required_side_to_front_bbox_width": 0.50,
                "minimum_required_back_to_front_silhouette_area": 0.90,
                "minimum_required_top_to_front_silhouette_area": 0.70,
                "minimum_required_bottom_to_front_silhouette_area": 0.55,
            },
            "eye_crown": {
                "topology": "eight-part wrapped ring",
                "segments": [
                    "front_eye_band", "front_left_crown_wrap",
                    "left_side_temple", "rear_left_crown_wrap", "back_eye_band",
                    "rear_right_crown_wrap", "right_side_temple",
                    "front_right_crown_wrap",
                ],
                "angled_corner_yaw_degrees": 38.0,
            },
            "wing_sector_contract": {
                "rear_upper_degrees": [35.0, 55.0],
                "middle_degrees": [15.0, 30.0],
                "front_lower_degrees": [35.0, 55.0],
                "all_spar_feather_and_vane_cubes_require_nonzero_yaw": True,
            },
            "distal_taper_contract": {
                "segments_per_primary": 3,
                "segments_per_overlap_vane": 3,
                "strictly_decreasing_width_and_depth": True,
                "maximum_terminal_width": 1.4,
                "maximum_terminal_depth": 1.0,
                "staggered_terminal_lengths": True,
            },
            "feature_inventory": feature_inventory,
            "eyes": eye_records,
            "wing_records": wing_records,
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        },
    }

    if len(attachments) != len(builder.cubes) - 1:
        raise AssertionError(
            f"attachment tree has {len(attachments)} links for {len(builder.cubes)} cubes"
        )
    audit = audit_attachments(spec, attachments)
    if not audit["all_connected"]:
        failures = [record for record in audit["attachments"] if not record["connected"]]
        raise AssertionError(failures[:5])

    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
