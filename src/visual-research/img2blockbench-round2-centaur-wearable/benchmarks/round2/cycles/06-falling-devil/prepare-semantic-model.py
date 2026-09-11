#!/usr/bin/env python3
"""Author the Falling Devil as a deep, twelve-armed native cuboid character."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from semantic_geometry import SemanticModelBuilder, audit_attachments, segment_cube


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "image-12.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "e2824aa87127cb8922be7e37ae0942f9abfbf8413fbe39ce133edf4ed06c18fb"


Point = tuple[float, float, float]


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "solid",
    scale: int = 1,
) -> dict[str, Any]:
    """Create one deterministic pixel material."""
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
    """Mirror one left-authored point across the character centerline."""
    if side not in {"left", "right"}:
        raise ValueError("side must be left or right")
    sign = 1.0 if side == "left" else -1.0
    return point[0] * sign, point[1], point[2]


def main() -> None:
    """Write a volumetric chef body, detached head, twelve arms, and tendril."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Falling Devil reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.mode != "RGB" or opened.size != (399, 501):
            raise ValueError(f"unexpected Falling Devil reference: {opened.mode} {opened.size}")

    materials = {
        "skin": material("#dc937b", "#8d4c45", "#ffd0a8", "solid", 1),
        "skin_light": material("#efaa8e", "#a55f52", "#ffd8b8", "solid", 1),
        "skin_shadow": material("#b86e63", "#713b3b", "#eaa28a", "solid", 1),
        "white_cloth": material("#e4ded2", "#8f9292", "#fff8e9", "solid", 1),
        "white_shadow": material("#b8bab5", "#696e73", "#ebe6dc", "solid", 1),
        "black_cloth": material("#181a27", "#090a0f", "#383f70", "solid", 1),
        "black_shadow": material("#0d0f18", "#05060a", "#252a4c", "solid", 1),
        "blue_sheen": material("#283064", "#10142e", "#5663a8", "solid", 1),
        "hair": material("#14131a", "#07070a", "#35303b", "solid", 1),
        "eye": material("#292027", "#0b080b", "#5e4447", "solid", 1),
        "lip": material("#692f39", "#2b1118", "#bb6670", "solid", 1),
        "blood": material("#7a2431", "#310b12", "#b84a52", "solid", 1),
    }

    builder = SemanticModelBuilder(pivot=(0.0, 0.0, 0.0))
    attachments: list[tuple[str, str, Point]] = []

    def add_attached(cube: dict[str, Any], parent: str | None, joint: Point) -> str:
        """Add a cube and its single structural parent contact."""
        builder.add_cube(cube)
        if parent is not None:
            attachments.append((parent, cube["name"], joint))
        return str(cube["name"])

    # The body uses broad, deep volumes. The visible hem is cropped by the source,
    # but the model retains plausible feet beneath the layered chef skirt.
    for name, parent, pivot in (
        ("pelvis", "root", (0.0, 43.0, 0.0)),
        ("torso", "pelvis", (0.0, 55.0, 0.0)),
        ("chest", "torso", (0.0, 64.0, 0.0)),
        ("collar", "chest", (0.0, 71.0, 0.0)),
        ("left_leg", "pelvis", (-3.2, 10.0, -0.5)),
        ("right_leg", "pelvis", (3.2, 10.0, -0.5)),
        ("tendril", "pelvis", (-4.0, 40.0, 6.0)),
    ):
        builder.add_bone(name, parent, pivot)

    add_attached(
        box(
            "skirt_core",
            "pelvis",
            (0.0, 25.0, 0.0),
            (17.0, 37.0, 13.0),
            "deep black chef skirt core",
            "black_cloth",
        ),
        None,
        (0.0, 0.0, 0.0),
    )
    body_cubes = (
        (
            box(
                "apron_front",
                "pelvis",
                (0.0, 27.0, 7.1),
                (13.5, 33.0, 2.2),
                "forward blue-black apron plane with real thickness",
                "blue_sheen",
                rotation=(0.0, 0.0, -2.0),
            ),
            "skirt_core",
            (0.0, 40.0, 6.0),
        ),
        (
            segment_cube(
                "left_skirt_flare",
                "pelvis",
                (-4.5, 44.0, -0.5),
                (-9.0, 8.0, 0.0),
                (8.5, 12.0),
                "left flared skirt panel",
                "black_cloth",
                overlap=0.5,
            ),
            "skirt_core",
            (-4.5, 42.5, -0.5),
        ),
        (
            segment_cube(
                "right_skirt_flare",
                "pelvis",
                (4.5, 44.0, -0.5),
                (9.0, 8.0, 0.0),
                (8.5, 12.0),
                "right flared skirt panel",
                "black_shadow",
                overlap=0.5,
            ),
            "skirt_core",
            (4.5, 42.5, -0.5),
        ),
        (
            box(
                "left_torn_hem",
                "pelvis",
                (-7.2, 7.0, 1.0),
                (5.0, 8.0, 11.0),
                "left ragged hem tab",
                "black_shadow",
                rotation=(0.0, 0.0, -12.0),
            ),
            "left_skirt_flare",
            (-7.7, 10.0, 0.5),
        ),
        (
            box(
                "right_torn_hem",
                "pelvis",
                (7.0, 7.5, 0.5),
                (5.0, 8.0, 11.0),
                "right ragged hem tab",
                "black_cloth",
                rotation=(0.0, 0.0, 10.0),
            ),
            "right_skirt_flare",
            (7.5, 10.0, 0.5),
        ),
        (
            box(
                "pelvis_core",
                "pelvis",
                (0.0, 44.0, 0.0),
                (18.0, 9.0, 13.0),
                "deep gathered pelvis beneath apron",
                "black_cloth",
            ),
            "skirt_core",
            (0.0, 42.5, 0.0),
        ),
        (
            box(
                "waist_sash",
                "pelvis",
                (0.0, 49.3, 0.5),
                (18.5, 3.2, 13.5),
                "thick tied waist sash",
                "black_shadow",
            ),
            "pelvis_core",
            (0.0, 48.0, 0.0),
        ),
        (
            box(
                "sash_knot",
                "pelvis",
                (0.0, 48.5, 8.0),
                (4.0, 4.0, 3.0),
                "front apron knot",
                "black_cloth",
                rotation=(0.0, 0.0, 8.0),
            ),
            "waist_sash",
            (0.0, 49.0, 6.5),
        ),
        (
            segment_cube(
                "left_sash_tail",
                "pelvis",
                (-1.0, 48.0, 8.0),
                (-3.5, 39.0, 8.5),
                (2.2, 1.8),
                "left hanging apron tie",
                "black_shadow",
                overlap=0.35,
            ),
            "sash_knot",
            (-1.0, 48.0, 8.0),
        ),
        (
            segment_cube(
                "right_sash_tail",
                "pelvis",
                (1.0, 48.0, 8.0),
                (2.0, 38.0, 8.7),
                (2.2, 1.8),
                "right hanging apron tie",
                "black_cloth",
                overlap=0.35,
            ),
            "sash_knot",
            (1.0, 48.0, 8.0),
        ),
        (
            box(
                "abdomen_jacket",
                "torso",
                (0.0, 55.0, 0.0),
                (17.0, 10.0, 12.0),
                "fitted white double-breasted jacket waist",
                "white_shadow",
            ),
            "waist_sash",
            (0.0, 50.5, 0.0),
        ),
        (
            box(
                "chest_jacket",
                "chest",
                (0.0, 63.0, 0.0),
                (20.0, 10.0, 13.0),
                "deep white chef jacket chest",
                "white_cloth",
            ),
            "abdomen_jacket",
            (0.0, 59.0, 0.0),
        ),
        (
            box(
                "shoulder_bar",
                "chest",
                (0.0, 67.5, -0.3),
                (24.0, 4.5, 13.5),
                "broad multi-arm shoulder structure",
                "white_cloth",
            ),
            "chest_jacket",
            (0.0, 66.0, 0.0),
        ),
        (
            box(
                "left_short_sleeve",
                "chest",
                (-12.0, 64.0, 0.5),
                (5.5, 7.5, 11.5),
                "left white rolled chef sleeve",
                "white_shadow",
                rotation=(0.0, 0.0, -10.0),
            ),
            "shoulder_bar",
            (-11.5, 66.0, 0.0),
        ),
        (
            box(
                "right_short_sleeve",
                "chest",
                (12.0, 64.0, 0.5),
                (5.5, 7.5, 11.5),
                "right white rolled chef sleeve",
                "white_shadow",
                rotation=(0.0, 0.0, 10.0),
            ),
            "shoulder_bar",
            (11.5, 66.0, 0.0),
        ),
        (
            box(
                "neck_stump",
                "collar",
                (0.0, 71.2, 0.0),
                (7.0, 4.5, 8.0),
                "headless neck stump below the suspended head",
                "blood",
                faces={"south": {"material": "black_shadow"}},
            ),
            "shoulder_bar",
            (0.0, 69.5, 0.0),
        ),
        (
            box(
                "left_collar",
                "collar",
                (-4.2, 71.0, 4.8),
                (6.0, 4.0, 3.2),
                "left open chef collar",
                "white_cloth",
                rotation=(0.0, 0.0, -28.0),
            ),
            "neck_stump",
            (-2.5, 71.0, 3.4),
        ),
        (
            box(
                "right_collar",
                "collar",
                (4.2, 71.0, 4.8),
                (6.0, 4.0, 3.2),
                "right open chef collar",
                "white_cloth",
                rotation=(0.0, 0.0, 28.0),
            ),
            "neck_stump",
            (2.5, 71.0, 3.4),
        ),
    )
    for cube, parent, joint in body_cubes:
        add_attached(cube, parent, joint)

    # Narrow, largely occluded legs preserve a grounded volumetric asset without
    # pretending the source reveals footwear below its cropped bottom edge.
    for side in ("left", "right"):
        x = -3.2 if side == "left" else 3.2
        add_attached(
            box(
                f"{side}_lower_leg",
                f"{side}_leg",
                (x, 5.3, -0.5),
                (5.5, 10.5, 9.0),
                f"mostly occluded {side} lower leg",
                "black_shadow" if side == "left" else "black_cloth",
            ),
            "skirt_core",
            (x, 9.0, -0.5),
        )
        add_attached(
            box(
                f"{side}_foot",
                f"{side}_leg",
                (x, 0.75, 2.0),
                (6.2, 1.5, 11.0),
                f"grounded hidden {side} foot",
                "black_shadow",
            ),
            f"{side}_lower_leg",
            (x, 1.0, 0.0),
        )

    arm_records: list[dict[str, Any]] = []

    def add_arm_pair(
        pair: str,
        parent_cube: str,
        parent_bone: str,
        left_points: Sequence[Point],
        widths: Sequence[float],
        depths: Sequence[float],
        paints: Sequence[str],
        depth_layer: str,
        head_contact: bool,
    ) -> None:
        """Add one mirrored arm pair while retaining individual semantic chains."""
        for side in ("left", "right"):
            points = tuple(mirrored(point, side) for point in left_points)
            chain_name = f"{pair}_{side}_arm"
            chain = builder.add_chain(
                chain_name,
                parent_bone,
                points,
                widths,
                paints,
                f"{pair.replace('_', ' ')} {side} arm",
                overlap=0.45,
                depths=depths,
            )
            resolved_parent = parent_cube.format(side=side)
            attachments.append((resolved_parent, chain.cubes[0], points[0]))
            attachments.extend(chain.attachments)
            arm_records.append(
                {
                    "pair": pair,
                    "side": side,
                    "segments": list(chain.cubes),
                    "hand_cube": chain.cubes[-1],
                    "joints": [list(point) for point in points],
                    "depth_layer": depth_layer,
                    "head_contact": head_contact,
                    "mean_z": round(sum(point[2] for point in points) / len(points), 6),
                }
            )

    # Pair 1: a high rear sweep runs from the back to the upper sides of the head.
    add_arm_pair(
        "outer_head_support",
        "shoulder_bar",
        "chest",
        ((-8.0, 67.0, -5.0), (-19.0, 86.0, -5.5), (-7.0, 86.0, -1.5),
         (-4.25, 84.0, 1.0)),
        (3.8, 3.4, 3.7),
        (3.5, 3.2, 3.5),
        ("skin_shadow", "skin", "skin_light"),
        "rear_high_to_head",
        True,
    )
    # Pair 2: a second, visibly crossing support pair grips the lower face.
    add_arm_pair(
        "inner_head_support",
        "shoulder_bar",
        "chest",
        ((-7.5, 65.5, -1.5), (-16.0, 75.0, 1.0), (-7.0, 81.0, 2.5),
         (-4.25, 79.5, 3.0)),
        (3.7, 3.2, 3.5),
        (3.4, 3.0, 3.4),
        ("skin", "skin_light", "skin_light"),
        "middle_crossing_to_head",
        True,
    )
    # Pair 3: bare rear arms descend outside the torso to open hands.
    add_arm_pair(
        "rear_mid_bare",
        "shoulder_bar",
        "chest",
        ((-10.0, 65.5, -6.0), (-21.0, 66.0, -9.0), (-22.0, 48.0, -7.0),
         (-20.0, 43.0, -5.0)),
        (3.8, 3.2, 3.4),
        (3.5, 3.0, 3.2),
        ("skin_shadow", "skin", "skin_light"),
        "rear_mid",
        False,
    )

    # Black arm pairs remain distinct despite overlapping in the frontal source.
    # Their separated Z values make the two elbows legible in side/isometric views.
    add_arm_pair(
        "upper_black_sleeved",
        "{side}_short_sleeve",
        "chest",
        ((-12.2, 64.0, 3.5), (-18.0, 52.0, 5.5), (-10.0, 47.5, 8.0),
         (-5.5, 49.0, 8.5)),
        (4.3, 4.0, 3.8),
        (4.5, 4.2, 3.8),
        ("black_cloth", "black_cloth", "black_shadow"),
        "front_upper",
        False,
    )
    add_arm_pair(
        "lower_black_sleeved",
        "abdomen_jacket",
        "torso",
        ((-8.0, 57.0, 3.0), (-18.0, 47.0, 10.0), (-16.0, 34.0, 13.0),
         (-12.0, 31.5, 12.0)),
        (4.1, 3.8, 3.7),
        (4.3, 4.0, 3.8),
        ("black_cloth", "black_cloth", "black_shadow"),
        "front_lower",
        False,
    )
    # Pair 6 is the lowest rear bare pair behind the skirt and tendril.
    add_arm_pair(
        "rear_low_bare",
        "pelvis_core",
        "pelvis",
        ((-8.0, 46.0, -6.0), (-26.0, 44.0, -12.0), (-19.0, 31.0, -9.0),
         (-15.5, 32.5, -6.0)),
        (3.7, 3.1, 3.2),
        (3.4, 3.0, 3.0),
        ("skin_shadow", "skin", "skin_light"),
        "rear_low",
        False,
    )

    # The detached head is structurally supported by the outer-left hand, not by
    # a hidden neck. The other three contacts are recorded and audited separately.
    outer_left = next(
        record
        for record in arm_records
        if record["pair"] == "outer_head_support" and record["side"] == "left"
    )
    builder.add_bone("head", str(outer_left["segments"][-1]), (-4.25, 84.0, 1.0))
    builder.add_bone("face_detail", "head", (0.0, 82.0, 2.0))
    builder.add_bone("hat", "head", (0.0, 87.0, 0.0))
    add_attached(
        box(
            "head_face",
            "head",
            (0.0, 82.0, 2.0),
            (8.5, 10.0, 8.0),
            "suspended human face volume",
            "skin_light",
        ),
        str(outer_left["hand_cube"]),
        (-4.25, 84.0, 1.0),
    )
    head_parts = (
        (
            box(
                "chin",
                "face_detail",
                (0.0, 76.8, 2.0),
                (5.0, 3.5, 6.0),
                "pointed detached chin",
                "skin_light",
            ),
            (0.0, 77.3, 2.0),
        ),
        (
            box(
                "nose",
                "face_detail",
                (0.0, 81.3, 6.1),
                (1.4, 2.6, 1.2),
                "small projecting nose",
                "skin",
                rotation=(6.0, 0.0, 0.0),
            ),
            (0.0, 81.5, 5.9),
        ),
        (
            box(
                "left_ear",
                "face_detail",
                (-4.55, 82.3, 1.5),
                (1.2, 3.0, 2.4),
                "left ear under supporting hands",
                "skin",
            ),
            (-4.1, 82.3, 1.5),
        ),
        (
            box(
                "right_ear",
                "face_detail",
                (4.55, 82.3, 1.5),
                (1.2, 3.0, 2.4),
                "right ear under supporting hands",
                "skin",
            ),
            (4.1, 82.3, 1.5),
        ),
        (
            box(
                "hair_cap",
                "face_detail",
                (0.0, 86.2, 1.0),
                (8.4, 2.2, 7.6),
                "black hairline beneath hat",
                "hair",
            ),
            (0.0, 86.0, 2.0),
        ),
    )
    for cube, joint in head_parts:
        add_attached(cube, "head_face", joint)

    hat_parts = (
        (
            box(
                "hat_band",
                "hat",
                (0.0, 89.0, 1.0),
                (11.0, 4.0, 8.0),
                "wide toque band",
                "white_shadow",
            ),
            "head_face",
            (0.0, 87.0, 1.0),
            (0.0, 87.0, 1.0),
        ),
        (
            box(
                "hat_crown_lower",
                "hat",
                (0.0, 94.0, 1.0),
                (10.8, 7.0, 7.8),
                "tall fluted toque lower crown",
                "white_cloth",
            ),
            "hat_band",
            (0.0, 91.0, 1.0),
            (0.0, 91.0, 1.0),
        ),
        (
            box(
                "hat_crown_upper",
                "hat",
                (0.0, 98.5, 1.0),
                (10.0, 4.0, 7.0),
                "slightly tapered toque upper crown",
                "white_cloth",
            ),
            "hat_crown_lower",
            (0.0, 97.2, 1.0),
            (0.0, 97.0, 1.0),
        ),
        (
            box(
                "hat_top",
                "hat",
                (0.0, 101.0, 1.0),
                (9.2, 1.6, 6.5),
                "flat toque crown cap",
                "white_shadow",
            ),
            "hat_crown_upper",
            (0.0, 100.2, 1.0),
            (0.0, 100.2, 1.0),
        ),
    )
    for cube, parent, joint, _ in hat_parts:
        add_attached(cube, parent, joint)

    # Three raised pleats make the tall chef hat readable in untextured silhouettes.
    for index, x in enumerate((-3.2, 0.0, 3.2), start=1):
        add_attached(
            box(
                f"hat_pleat_{index}",
                "hat",
                (x, 95.8, 5.05),
                (0.55, 9.0, 0.7),
                "vertical toque pleat",
                "white_shadow",
            ),
            "hat_crown_lower",
            (x, 95.0, 4.8),
        )

    # The independent waist tendril is never counted as an arm and occupies the
    # foremost depth layer, matching the peach sweep across the lower apron.
    tendril_points: tuple[Point, ...] = (
        (-4.0, 40.0, 6.0),
        (-17.0, 35.5, 10.0),
        (-26.0, 31.5, 11.5),
        (-17.0, 28.5, 13.0),
        (3.0, 26.5, 14.0),
        (20.0, 27.5, 13.5),
        (21.0, 30.0, 12.0),
    )
    tendril_chain = builder.add_chain(
        "waist_tendril",
        "tendril",
        tendril_points,
        (3.0, 2.7, 2.4, 2.1, 1.7, 1.2),
        ("skin_shadow", "skin", "skin_light", "skin_light", "skin", "skin_shadow"),
        "separate serpentine waist tendril",
        overlap=0.35,
        depths=(2.8, 2.6, 2.4, 2.1, 1.7, 1.2),
    )
    attachments.append(("pelvis_core", tendril_chain.cubes[0], tendril_points[0]))
    attachments.extend(tendril_chain.attachments)

    head_support_contacts = []
    for record in arm_records:
        if not record["head_contact"]:
            continue
        point = tuple(float(value) for value in record["joints"][-1])
        head_support_contacts.append(
            {
                "pair": record["pair"],
                "side": record["side"],
                "hand_cube": record["hand_cube"],
                "head_cube": "head_face",
                "joint": list(point),
            }
        )

    landmarks: list[dict[str, Any]] = [
        {
            "name": "left_closed_eye",
            "cube": "head_face",
            "face": "south",
            "center_uv": [0.31, 0.40],
            "size": [3, 1],
            "color": "#2a1b21",
            "center_color": "#2a1b21",
        },
        {
            "name": "right_closed_eye",
            "cube": "head_face",
            "face": "south",
            "center_uv": [0.69, 0.40],
            "size": [3, 1],
            "color": "#2a1b21",
            "center_color": "#2a1b21",
        },
        {
            "name": "vertical_lip",
            "cube": "head_face",
            "face": "south",
            "center_uv": [0.50, 0.72],
            "size": [1, 3],
            "color": "#6f313c",
            "center_color": "#2b1118",
        },
        {
            "name": "nose_shadow",
            "cube": "nose",
            "face": "south",
            "center_uv": [0.50, 0.72],
            "size": [1, 1],
            "color": "#7a4a45",
            "center_color": "#3e2225",
        },
        {
            "name": "open_neck",
            "cube": "neck_stump",
            "face": "south",
            "center_uv": [0.50, 0.22],
            "size": [4, 2],
            "color": "#1a1017",
            "center_color": "#71212d",
        },
        {
            "name": "jacket_buttons_left",
            "cube": "chest_jacket",
            "face": "south",
            "center_uv": [0.40, 0.56],
            "size": [1, 5],
            "color": "#727575",
            "center_color": "#31353a",
        },
        {
            "name": "jacket_buttons_right",
            "cube": "chest_jacket",
            "face": "south",
            "center_uv": [0.60, 0.56],
            "size": [1, 5],
            "color": "#727575",
            "center_color": "#31353a",
        },
        {
            "name": "apron_center_highlight",
            "cube": "apron_front",
            "face": "south",
            "center_uv": [0.54, 0.46],
            "size": [5, 18],
            "color": "#3f4d91",
            "center_color": "#222a57",
        },
    ]
    for index, x in enumerate((-3.2, 0.0, 3.2), start=1):
        landmarks.append(
            {
                "name": f"hat_pleat_shadow_{index}",
                "cube": "hat_crown_lower",
                "face": "south",
                "center_uv": [(x + 5.4) / 10.8, 0.5],
                "size": [1, 8],
                "color": "#8d969b",
                "center_color": "#686f75",
            }
        )

    inventory = {
        "arm_pairs": 6,
        "individual_arms": 12,
        "arm_segments": sum(len(record["segments"]) for record in arm_records),
        "head_support_arm_pairs": 2,
        "head_support_hands": 4,
        "head_support_contacts": len(head_support_contacts),
        "black_sleeved_arm_pairs": 2,
        "bare_arm_pairs": 4,
        "distinct_arm_depth_bands": len({record["depth_layer"] for record in arm_records}),
        "waist_tendrils": 1,
        "tendril_segments": len(tendril_chain.cubes),
        "chef_hat_cuboids": 7,
        "detached_heads": 1,
        "grounded_feet": 2,
    }
    spec = {
        "schema_version": 1,
        "id": "falling_devil_twelve_armed_chef",
        "reference": {
            "image": Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix(),
            "sha256": EXPECTED_SHA256,
            "width": 399,
            "height": 501,
        },
        "subject": {
            "type": "character",
            "description": (
                "A headless chef-bodied Falling Devil with a separately supported head, "
                "tall toque, six visible arm pairs, black apron, and independent flesh tendril"
            ),
            "symmetry": "bilateral",
            "uncertainties": [
                "Only one frontal illustration is observed; rear markings and exact hidden "
                "arm-root ordering are conservative semantic inference",
                "The source crops the feet at the bottom edge, so footwear is intentionally plain",
                "Some overlapping elbows are partly occluded; arm count follows six traceable pairs",
                "Source rights are unknown and the ignored reference remains local only",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [70, 110],
            "identity_features": [
                "exactly six visible arm pairs and twelve individually articulated arms",
                "two distinct head-support pairs with four physical hand-to-head contacts",
                "detached human head with closed eyes beneath a tall fluted chef toque",
                "white double-breasted chef jacket over deep blue-black apron and skirt",
                "two overlapping black-sleeved arm pairs remain separable in depth",
                "independent flesh-colored waist tendril crossing the foreground",
                "substantial torso, skirt, head, and limb depth rather than a relief panel",
            ],
            "required_views": [
                "source-perspective", "front", "back", "left", "right", "top",
                "isometric", "head-support-closeup", "arm-layer-closeup",
                "tendril-closeup",
            ],
            "review_targets": [
                "six arm-pair count", "four hand-to-head contacts", "detached head gap",
                "arm depth separation", "tendril classification", "chef silhouette",
                "facial expression", "torso volume", "joint continuity",
            ],
        },
        "geometry": {"precision": 20},
        "texture": {
            "density": 2,
            "palette_size": 24,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": landmarks,
        "collision": {"width": 1.1, "height": 3.6, "eye_height": 3.15},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "depth-layered-twelve-arm-character-v1",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "single_view_hidden_geometry": "inferred_conservatively_not_observed",
            "frame_clipping": ["bottom"],
            "feature_inventory": inventory,
            "arm_chains": arm_records,
            "head_support_contacts": head_support_contacts,
            "tendril": {
                "classification": "independent_non_arm_appendage",
                "segments": list(tendril_chain.cubes),
                "joints": [list(point) for point in tendril_points],
                "depth_layer": "frontmost",
            },
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        },
    }

    if len(attachments) != len(builder.cubes) - 1:
        raise AssertionError("declared structural contacts must form an N-1 tree")
    structural_audit = audit_attachments(spec, attachments)
    if not structural_audit["all_connected"]:
        raise AssertionError(structural_audit)
    support_links = [
        (record["hand_cube"], record["head_cube"], record["joint"])
        for record in head_support_contacts
    ]
    support_audit = audit_attachments(spec, support_links)
    if not support_audit["all_connected"]:
        raise AssertionError(support_audit)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
