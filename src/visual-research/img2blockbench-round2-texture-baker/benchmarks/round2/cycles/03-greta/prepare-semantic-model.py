#!/usr/bin/env python3
"""Author Greta as a native volumetric shark-headed humanoid."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from PIL import Image

from semantic_geometry import (
    BranchEdge,
    BranchNode,
    SemanticModelBuilder,
    segment_cube,
)


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "image-9.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "a0519be7ef788e3ea2d01b3fa1dcd310912c5489a58b3cb675fa8b4962626178"


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "solid",
    scale: int = 1,
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


def mouth_landmarks(cube: str, prefix: str, width: int) -> list[dict[str, Any]]:
    """Return two pixel tooth rows for one dark mouth cavity."""
    return [
        {
            "name": f"{prefix}_upper_teeth",
            "cube": cube,
            "face": "south",
            "center_uv": [0.5, 0.27],
            "size": [width, 1],
            "color": "#e9e4d5",
            "center_color": "#5a2023",
        },
        {
            "name": f"{prefix}_lower_teeth",
            "cube": cube,
            "face": "south",
            "center_uv": [0.5, 0.73],
            "size": [width, 1],
            "color": "#e9e4d5",
            "center_color": "#5a2023",
        },
    ]


def main() -> None:
    """Write a deep biped with four mouths, an articulated tail, and held axe."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Greta reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.mode != "RGBA" or opened.size != (600, 766):
            raise ValueError(f"unexpected Greta reference: {opened.mode} {opened.size}")

    materials = {
        "suit": material("#17191d", "#090a0d", "#343840", "solid", 1),
        "suit_mid": material("#252931", "#101217", "#464b55", "solid", 1),
        "suit_shadow": material("#0d0f13", "#050608", "#252930", "solid", 1),
        "shirt": material("#e0e0db", "#9b9d9a", "#f8f7ef", "solid", 1),
        "tie": material("#273b64", "#111a31", "#5279b6", "stripes", 2),
        "skin": material("#dadad5", "#929493", "#f6f4ec", "solid", 1),
        "skin_blood": material("#cecec8", "#898b89", "#eee9df", "solid", 1),
        "mouth": material("#631923", "#16080d", "#a8323e", "solid", 1),
        "eye": material("#c82b32", "#541017", "#ff625c", "solid", 1),
        "tooth": material("#f3efe2", "#b7b5ad", "#ffffff", "solid", 1),
        "blue": material("#285aaa", "#102856", "#4d8ee3", "solid", 1),
        "blood": material("#842d31", "#331217", "#c0504e", "solid", 1),
        "steel": material("#767a7c", "#303438", "#c2c5c3", "solid", 1),
        "steel_blood": material("#75666a", "#30272b", "#b18b8c", "solid", 1),
        "handle": material("#352d2b", "#151212", "#665651", "stripes", 3),
        "tail_band": material("#18191d", "#08090b", "#383a40", "solid", 1),
    }

    builder = SemanticModelBuilder()
    for name, parent, pivot in (
        ("pelvis", "root", (0.0, 29.0, 0.0)),
        ("torso", "pelvis", (0.0, 37.0, 0.0)),
        ("chest", "torso", (0.0, 47.0, 0.0)),
        ("neck", "chest", (0.0, 53.0, 0.0)),
        ("head", "neck", (0.0, 58.0, 0.0)),
        ("jaw", "head", (-1.0, 56.0, 1.0)),
        ("hat", "head", (0.0, 63.0, 0.0)),
    ):
        builder.add_bone(name, parent, pivot)

    attachments: list[tuple[str, str, tuple[float, float, float]]] = []

    def add_alternating_teeth(
        prefix: str,
        bone: str,
        cavity: str,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        count: int,
        size: float,
        vertical_offset: float,
        front_offset: float,
    ) -> None:
        """Place a readable alternating tooth row while retaining cavity contact."""
        angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
        for index in range(count):
            amount = (index + 1) / (count + 1)
            joint = tuple(
                start[axis] + (end[axis] - start[axis]) * amount
                for axis in range(3)
            )
            offset = vertical_offset if index % 2 == 0 else -vertical_offset
            name = f"{prefix}_tooth_{index + 1}"
            builder.add_cube(
                box(
                    name,
                    bone,
                    (joint[0], joint[1] + offset, joint[2] + front_offset),
                    (size, size, front_offset * 2 + 0.2),
                    f"alternating visible tooth for {prefix}",
                    "tooth",
                    rotation=(0, 0, angle),
                    origin=joint,
                )
            )
            attachments.append((cavity, name, joint))

    body = (
        box("pelvis_core", "pelvis", (0, 29, 0), (16, 9, 14),
            "deep suited pelvis", "suit_shadow"),
        box("abdomen_core", "torso", (0, 36.5, 0), (18, 8, 14),
            "deep fitted lower jacket", "suit"),
        box("chest_core", "chest", (0, 45.5, 0), (20, 11, 15),
            "broad deep tailored chest", "suit"),
        box("shoulder_core", "chest", (0, 50.2, -0.2), (23, 4.5, 15),
            "wide load-bearing shoulders", "suit_mid"),
        box("shark_throat", "neck", (0, 53.4, 0.3), (10.5, 8.5, 12),
            "white shark throat joining collar", "skin_blood"),
        box("head_cranium", "head", (-0.4, 59.0, 0.0), (11, 10, 12),
            "deep rear shark cranium", "skin"),
    )
    for cube in body:
        builder.add_cube(cube)
    attachments.extend(
        [
            ("pelvis_core", "abdomen_core", (0, 33.2, 0)),
            ("abdomen_core", "chest_core", (0, 40.2, 0)),
            ("chest_core", "shoulder_core", (0, 49.5, 0)),
            ("shoulder_core", "shark_throat", (0, 51.5, 0)),
            ("shark_throat", "head_cranium", (0, 56.0, 0)),
        ]
    )

    # The head is intentionally yawed almost in profile. Its long axis is real
    # geometry, while the visible eye and tooth rows remain texture landmarks.
    snout = builder.add_branch_graph(
        "head_snout",
        "head",
        "snout_root",
        (
            BranchNode("snout_root", (0.0, 59.2, 1.0)),
            BranchNode("snout_mid", (-9.0, 58.5, 1.0)),
            BranchNode("snout_tip", (-17.5, 57.5, 1.0)),
        ),
        (
            BranchEdge("base", "snout_root", "snout_mid", 10.5, 8.5,
                       "skin_blood", "broad rear shark snout", 2, 13.0, 10.5),
            BranchEdge("tip", "snout_mid", "snout_tip", 8.5, 5.0,
                       "skin_blood", "tapered shark nose", 2, 10.5, 7.0),
        ),
        overlap=0.45,
        parent_cube="head_cranium",
    )
    attachments.extend(snout.attachments)
    builder.add_cube(
        segment_cube(
            "lower_jaw",
            "jaw",
            (-0.5, 56.0, 1.0),
            (-16.3, 54.8, 1.0),
            (4.8, 11.0),
            "separate heavy lower shark jaw",
            "skin_blood",
            overlap=0.5,
        )
    )
    builder.add_cube(
        segment_cube(
            "mouth_head",
            "jaw",
            (-1.0, 56.4, 7.1),
            (-16.4, 55.0, 4.55),
            (2.0, 1.0),
            "toothed main shark mouth cavity",
            "mouth",
            overlap=0.15,
        )
    )
    attachments.extend(
        [
            ("head_cranium", "lower_jaw", (-0.5, 56.0, 1.0)),
            ("head_snout_base_1", "mouth_head", (-1.0, 56.4, 7.1)),
        ]
    )
    add_alternating_teeth(
        "head_mouth", "jaw", "mouth_head",
        (-1.0, 56.4, 7.1), (-16.4, 55.0, 4.55),
        10, 1.25, 0.5, 0.35,
    )

    hat_cubes = (
        box("hat_band", "hat", (-2.2, 63.2, 0), (13.0, 2.8, 9.0),
            "chef hat lower band", "shirt", rotation=(0, 0, -2)),
        box("hat_crown", "hat", (-2.3, 65.3, 0), (12.0, 3.6, 8.0),
            "tall chef hat crown", "shirt"),
        box("hat_puff_left", "hat", (-7.0, 67.4, 0), (8.0, 3.2, 8.2),
            "left chef hat puff", "shirt", rotation=(0, 0, -8)),
        box("hat_puff_center", "hat", (-2.3, 67.6, 0), (8.0, 3.5, 8.5),
            "center chef hat puff", "shirt"),
        box("hat_puff_right", "hat", (2.4, 67.4, 0), (8.0, 3.2, 8.2),
            "right chef hat puff", "shirt", rotation=(0, 0, 8)),
    )
    for cube in hat_cubes:
        builder.add_cube(cube)
    attachments.extend(
        [
            ("head_cranium", "hat_band", (-2.0, 62.5, 0)),
            ("hat_band", "hat_crown", (-2.2, 64.2, 0)),
            ("hat_crown", "hat_puff_left", (-4.0, 66.2, 0)),
            ("hat_crown", "hat_puff_center", (-2.3, 66.2, 0)),
            ("hat_crown", "hat_puff_right", (-0.2, 66.2, 0)),
        ]
    )

    # The fin is a tapered semantic chain behind the tattooed shoulder.
    fin = builder.add_branch_graph(
        "dorsal_fin",
        "chest",
        "fin_root",
        (
            BranchNode("fin_root", (9.0, 51.0, -3.5)),
            BranchNode("fin_mid", (11.0, 54.0, -3.8)),
            BranchNode("fin_tip", (13.5, 56.2, -4.0)),
        ),
        (
            BranchEdge("base", "fin_root", "fin_mid", 5.5, 3.6,
                       "skin", "rear shoulder dorsal fin", 1, 1.4, 1.0),
            BranchEdge("tip", "fin_mid", "fin_tip", 3.4, 0.8,
                       "skin_blood", "pointed dorsal fin tip", 1, 0.9, 0.5),
        ),
        overlap=0.3,
        parent_cube="shoulder_core",
    )
    attachments.extend(fin.attachments)

    arm_records = []
    for side, sign, points in (
        ("left", -1, ((-9.5, 50.0, 0.0), (-13.0, 41.0, 0.6), (-12.5, 32.0, 1.2))),
        ("right", 1, ((9.5, 50.0, 0.0), (13.2, 42.0, 0.7), (12.5, 33.0, 1.2))),
    ):
        chain = builder.add_chain(
            f"{side}_arm",
            "chest",
            points,
            (6.5, 5.2),
            ("suit_mid", "suit"),
            f"{side} suited arm",
            overlap=0.45,
            depths=(7.0, 6.0),
        )
        hand_name = f"{side}_hand"
        builder.add_bone(hand_name, chain.bones[-1], points[-1])
        builder.add_cube(
            box(
                hand_name,
                hand_name,
                (points[-1][0], points[-1][1] - 1.2, 1.8),
                (6.2 if sign < 0 else 7.0, 6.0, 6.5),
                f"{side} blood-marked shark hand",
                "skin_blood",
                rotation=(0, 0, -5 * sign),
                origin=points[-1],
            )
        )
        attachments.append(("shoulder_core", chain.cubes[0], points[0]))
        attachments.extend(chain.attachments)
        attachments.append((chain.cubes[-1], hand_name, points[-1]))
        arm_records.append(
            {"name": side, "joints": [list(point) for point in points],
             "segments": list(chain.cubes), "hand": hand_name}
        )

    builder.add_cube(
        segment_cube(
            "mouth_hand",
            "right_hand",
            (10.1, 32.4, 5.05),
            (14.7, 31.2, 5.05),
            (1.35, 0.8),
            "toothed mouth in right shark hand",
            "mouth",
            overlap=0.12,
        )
    )
    attachments.append(("right_hand", "mouth_hand", (10.1, 32.4, 5.05)))
    add_alternating_teeth(
        "hand_mouth", "right_hand", "mouth_hand",
        (10.1, 32.4, 5.05), (14.7, 31.2, 5.05),
        4, 0.9, 0.32, 0.28,
    )

    # Three pointed right-hand digits preserve the source's claw silhouette.
    for index, x_offset in enumerate((-1.7, 0.0, 1.7), start=1):
        name = f"right_finger_{index}"
        start = (12.5 + x_offset, 30.5, 1.8)
        end = (12.5 + x_offset * 1.2, 27.5 - 0.35 * abs(x_offset), 2.1)
        builder.add_cube(
            segment_cube(name, "right_hand", start, end, (1.1, 1.2),
                         "pointed shark hand digit", "skin_blood", overlap=0.18)
        )
        attachments.append(("right_hand", name, start))

    leg_records = []
    for side, points in (
        ("left", ((-4.2, 30.0, 0.0), (-5.2, 17.0, 0.3), (-6.5, 3.0, 1.0))),
        ("right", ((4.2, 30.0, 0.0), (5.4, 16.0, 0.4), (7.0, 3.0, 1.1))),
    ):
        chain = builder.add_chain(
            f"{side}_leg",
            "pelvis",
            points,
            (7.5, 6.6),
            ("suit", "suit_shadow"),
            f"{side} tailored trouser leg",
            overlap=0.5,
            depths=(8.5, 7.5),
        )
        foot_name = f"{side}_foot"
        foot_center_x = -8.0 if side == "left" else 8.0
        foot_center_y = 1.5
        foot_width = 13.0 if side == "left" else 9.0
        builder.add_bone(foot_name, chain.bones[-1], points[-1])
        builder.add_cube(
            box(foot_name, foot_name, (foot_center_x, foot_center_y, 4.2),
                (foot_width, 3.0, 10.5),
                f"grounded {side} dress shoe", "suit_shadow")
        )
        attachments.append(("pelvis_core", chain.cubes[0], points[0]))
        attachments.extend(chain.attachments)
        attachments.append((chain.cubes[-1], foot_name, points[-1]))
        leg_records.append(
            {"name": side, "joints": [list(point) for point in points],
             "segments": list(chain.cubes), "foot": foot_name}
        )

    tail = builder.add_branch_graph(
        "tail",
        "pelvis",
        "tail_root",
        (
            BranchNode("tail_root", (1.0, 25.0, -5.0)),
            BranchNode("tail_base", (10.0, 19.5, -5.0)),
            BranchNode("tail_mid", (21.0, 19.0, -4.5)),
            BranchNode("tail_fork", (26.0, 15.0, -4.0)),
            BranchNode("tail_upper_tip", (35.0, 23.0, -3.5)),
            BranchNode("tail_lower_tip", (36.0, 6.0, -3.5)),
        ),
        (
            BranchEdge("base", "tail_root", "tail_base", 11.5, 10.5,
                       "skin_blood", "thick rear shark tail root", 2, 11.0, 10.5),
            BranchEdge("mid", "tail_base", "tail_mid", 10.5, 7.5,
                       "skin_blood", "single broad tapered shark tail", 3, 10.5, 8.0),
            BranchEdge("band", "tail_mid", "tail_fork", 7.2, 5.5,
                       "tail_band", "dark caudal tail band", 1, 8.0, 6.5),
            BranchEdge("upper_fin", "tail_fork", "tail_upper_tip", 14.0, 1.5,
                       "skin_blood", "upper caudal fin lobe", 1, 3.5, 1.0),
            BranchEdge("lower_fin", "tail_fork", "tail_lower_tip", 16.0, 1.5,
                       "skin_blood", "lower caudal fin lobe", 1, 3.5, 1.0),
        ),
        overlap=0.45,
        parent_cube="pelvis_core",
    )
    attachments.extend(tail.attachments)
    builder.add_cube(
        box(
            "tail_fork_hub",
            "tail_band_1",
            (26.0, 15.0, -4.0),
            (8.0, 8.0, 7.0),
            "single connected caudal fin hub",
            "skin_blood",
            rotation=(0, 0, -8),
        )
    )
    attachments.append(("tail_band_1", "tail_fork_hub", (26.0, 15.0, -4.0)))

    builder.add_cube(
        segment_cube(
            "mouth_tail_base",
            "tail_base_1",
            (3.2, 23.8, 0.1),
            (8.2, 20.6, 0.05),
            (1.6, 0.85),
            "first toothed mouth embedded in shark tail root",
            "mouth",
            overlap=0.12,
        )
    )
    builder.add_cube(
        segment_cube(
            "mouth_tail_mid",
            "tail_mid_1",
            (13.0, 19.8, -0.25),
            (19.2, 19.1, -0.35),
            (1.6, 0.85),
            "toothed mouth along main shark tail",
            "mouth",
            overlap=0.12,
        )
    )
    attachments.extend(
        [
            ("tail_base_1", "mouth_tail_base", (3.2, 23.8, 0.1)),
            ("tail_mid_1", "mouth_tail_mid", (13.0, 19.8, -0.25)),
        ]
    )
    add_alternating_teeth(
        "tail_base_mouth", "tail_base_1", "mouth_tail_base",
        (3.2, 23.8, 0.1), (8.2, 20.6, 0.05),
        4, 0.92, 0.34, 0.3,
    )
    add_alternating_teeth(
        "tail_mid_mouth", "tail_mid_1", "mouth_tail_mid",
        (13.0, 19.8, -0.25), (19.2, 19.1, -0.35),
        4, 0.92, 0.34, 0.3,
    )

    # The axe is one held prop with a stepped asymmetric hooked blade, not a
    # detached square silhouette ornament.
    builder.add_bone("axe", "left_hand", (-12.5, 30.0, 1.8))
    axe_handle = segment_cube(
        "axe_handle",
        "axe",
        (-12.5, 30.0, 1.8),
        (-21.5, 19.0, 2.0),
        (1.0, 1.0),
        "long one-handed butcher axe handle",
        "handle",
        overlap=0.25,
    )
    builder.add_cube(axe_handle)
    builder.add_cube(
        segment_cube(
            "axe_head", "axe", (-21.5, 19.0, 2.0), (-26.0, 20.5, 2.0),
            (5.5, 3.0), "wide upper cleaver wedge", "steel_blood", overlap=0.5,
        )
    )
    builder.add_cube(
        segment_cube(
            "axe_cheek", "axe", (-26.0, 20.5, 2.0), (-28.0, 16.5, 2.0),
            (5.0, 3.0), "descending outer cleaver cheek", "steel_blood", overlap=0.5,
        )
    )
    builder.add_cube(
        segment_cube("axe_hook", "axe", (-28.0, 16.5, 2.0),
                     (-24.5, 13.0, 2.0), (3.5, 3.0),
                     "inward hooked lower axe beak", "steel_blood", overlap=0.35)
    )
    attachments.extend(
        [
            ("left_hand", "axe_handle", (-12.5, 30.0, 1.8)),
            ("axe_handle", "axe_head", (-21.5, 19.0, 2.0)),
            ("axe_head", "axe_cheek", (-26.0, 20.5, 2.0)),
            ("axe_cheek", "axe_hook", (-28.0, 16.5, 2.0)),
        ]
    )

    landmarks: list[dict[str, Any]] = []
    landmarks.extend(mouth_landmarks("mouth_head", "head_mouth", 10))
    landmarks.extend(mouth_landmarks("mouth_hand", "hand_mouth", 4))
    landmarks.extend(mouth_landmarks("mouth_tail_base", "tail_base_mouth", 4))
    landmarks.extend(mouth_landmarks("mouth_tail_mid", "tail_mid_mouth", 5))
    landmarks.append(
        {
            "name": "single_red_eye",
            "cube": "head_snout_base_2",
            "face": "south",
            "center_uv": [0.43, 0.32],
            "size": [2, 2],
            "color": "#e33139",
            "center_color": "#4a090d",
        }
    )
    # Two stepped curls and one diagonal slash read as a flowing shoulder
    # tattoo at pixel scale instead of collapsing into a block letter.
    tattoo_marks = (
        (0.12, 0.16, 4, 1),
        (0.24, 0.26, 4, 1),
        (0.36, 0.36, 4, 1),
        (0.48, 0.46, 4, 1),
        (0.60, 0.56, 4, 1),
        (0.72, 0.66, 4, 1),
        (0.82, 0.76, 3, 1),
        (0.75, 0.18, 3, 1),
        (0.63, 0.30, 3, 1),
        (0.55, 0.43, 3, 1),
        (0.63, 0.56, 3, 1),
        (0.77, 0.68, 3, 1),
    )
    for index, (u, v, width, height) in enumerate(
        tattoo_marks,
        start=1,
    ):
        landmarks.append(
            {
                "name": f"right_shoulder_blue_tattoo_{index}",
                "cube": "right_arm_1",
                "face": "south",
                "center_uv": [u, v],
                "size": [width, height],
                "color": "#2f6fcc",
                "center_color": "#2f6fcc",
            }
        )
    landmarks.extend(
        [
            {
                "name": "white_shirt_front",
                "cube": "chest_core",
                "face": "south",
                "center_uv": [0.5, 0.22],
                "size": [8, 5],
                "color": "#deded8",
                "center_color": "#a3a5a2",
            },
            {
                "name": "navy_tie",
                "cube": "chest_core",
                "face": "south",
                "center_uv": [0.5, 0.43],
                "size": [3, 8],
                "color": "#28406c",
                "center_color": "#14213d",
            },
            {
                "name": "jacket_buttons",
                "cube": "abdomen_core",
                "face": "south",
                "center_uv": [0.5, 0.48],
                "size": [1, 4],
                "color": "#52565b",
                "center_color": "#111318",
            },
        ]
    )

    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    feature_inventory = {
        "toothed_mouth_assemblies": 4,
        "head_mouths": 1,
        "hand_mouths": 1,
        "tail_mouths": 2,
        "tooth_row_landmarks": 8,
        "red_eye_landmarks": 1,
        "blue_tattoo_landmarks": len(tattoo_marks),
        "chef_hat_cuboids": 5,
        "dorsal_fin_segments": len(fin.cubes),
        "humanoid_arm_chains": len(arm_records),
        "biped_leg_chains": len(leg_records),
        "grounded_feet": len(leg_records),
        "tail_segments": len(tail.cubes),
        "caudal_fin_branches": 2,
        "held_axes": 1,
    }
    spec = {
        "schema_version": 1,
        "id": "greta_shark_chef",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 600,
            "height": 766,
        },
        "subject": {
            "type": "character",
            "description": (
                "A broad suited shark chef with a yawed head, four toothed mouths, "
                "blue shoulder tattoo, held axe, dorsal fin, and articulated rear tail"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "Only one illustrated view is observed; rear markings and exact tail depth "
                "are conservative semantic inference",
                "The rear tail is partly occluded by the legs, so its hidden root is inferred",
                "Source rights are unknown and the ignored reference is retained locally only",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [45, 100],
            "identity_features": [
                "yawed white shark head with red eye and toothed jaw",
                "chef hat, black suit, white shirt, navy tie, and blue shoulder tattoo",
                "exactly four toothed mouths: head, right hand, and two tail mouths",
                "large attached articulated rear shark tail with forked caudal fin",
                "grounded biped stance and attached blood-marked axe",
                "substantial torso and head depth rather than a relief panel",
            ],
            "required_views": [
                "reference-angle", "front", "back", "left", "right", "top",
                "isometric", "head-mouth", "hand-mouth", "tail-mouths", "axe-contact",
            ],
            "review_targets": [
                "alpha silhouette", "shark head yaw", "four mouth count", "tail topology",
                "axe contact", "grounding", "tattoo", "torso depth", "joint continuity",
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
            "algorithm": "anatomy-rigged-shark-chef-v1",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "single_view_hidden_geometry": "inferred_conservatively_not_observed",
            "feature_inventory": feature_inventory,
            "arm_chains": arm_records,
            "leg_chains": leg_records,
            "tail_graph": tail.manifest,
            "head_snout_graph": snout.manifest,
            "dorsal_fin_graph": fin.manifest,
            "held_prop_contacts": [
                {"prop": "axe", "hand_cube": "left_hand", "prop_cube": "axe_handle",
                 "joint": [-12.5, 30.0, 1.8]},
            ],
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
