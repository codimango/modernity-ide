#!/usr/bin/env python3
"""Author the Round 2 Centaur as a pilot nested in a powered exoskeleton."""

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
OUTPUT = CYCLE / "model-spec.json"
REFERENCES = (
    (ROOT / "image-6.png", "4182ef6f34f6c701322d39b3ca07e5acf824a5b0b2804a48c6e2182c1698bf92"),
    (ROOT / "image-7.png", "c1286f3eb14a6a4642d1c55c73e0edaf3c59f9f3c7b264469d3c8e0d1997f799"),
    (ROOT / "image-8.png", "fa98828914ac3d04907d2452ff5627511ce877608c8273c007f7ae167723411c"),
)

Point = tuple[float, float, float]
SHIELD_ROTATION = (0.0, 35.0, -28.0)


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "solid",
    scale: int = 3,
) -> dict[str, Any]:
    """Create one deterministic hard-surface pixel material."""
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
    center: Sequence[float],
    size: Sequence[float],
    role: str,
    material_name: str,
    *,
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    origin: Sequence[float] | None = None,
    faces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one semantically named native cuboid."""
    return {
        "name": name,
        "bone": bone,
        "center": [float(value) for value in center],
        "size": [float(value) for value in size],
        "rotation": [float(value) for value in rotation],
        "origin": [float(value) for value in (origin or center)],
        "role": role,
        "material": material_name,
        "faces": dict(faces or {}),
    }


def midpoint(first: Sequence[float], second: Sequence[float]) -> Point:
    """Return the midpoint of two points."""
    return tuple((float(first[index]) + float(second[index])) / 2 for index in range(3))


def shield_point(local_x: float, local_y: float, z_value: float = 16.0) -> Point:
    """Transform a shield-local planar point into world coordinates."""
    center_x, center_y, center_z = 25.0, 82.0, 23.0
    angle_y = math.radians(SHIELD_ROTATION[1])
    angle_z = math.radians(SHIELD_ROTATION[2])
    # Existing callers specify surface depth relative to the authored shield
    # plane at Z=16; the whole shield is carried seven units forward.
    local_z = z_value - 16.0
    rotated_x = math.cos(angle_y) * local_x + math.sin(angle_y) * local_z
    rotated_z = -math.sin(angle_y) * local_x + math.cos(angle_y) * local_z
    return (
        center_x + math.cos(angle_z) * rotated_x - math.sin(angle_z) * local_y,
        center_y + math.sin(angle_z) * rotated_x + math.cos(angle_z) * local_y,
        center_z + rotated_z,
    )


def main() -> None:
    """Write the detailed pilot, exoframe, shield, booms, and paired powered legs."""
    for path, expected_hash in REFERENCES:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f"unexpected Centaur reference hash: {path.name}")
        with Image.open(path) as opened:
            if opened.mode != "RGB" or opened.size != (1000, 1023):
                raise ValueError(f"unexpected Centaur reference: {path.name} {opened.mode} {opened.size}")

    materials = {
        "frame_black": material("#151c20", "#080c0f", "#38434a", "solid", 4),
        "frame_dark": material("#222d33", "#0d1418", "#4d5c64", "solid", 3),
        "frame_blue": material("#2d424d", "#15242c", "#58717b", "solid", 4),
        "edge_steel": material("#69767b", "#343e43", "#a9b4b6", "stripes", 3),
        "bright_steel": material("#b9c1bd", "#666f70", "#edf1e8", "gradient", 3),
        "brass": material("#a47b47", "#503921", "#dbb66d", "stripes", 2),
        "warning": material("#d0a11f", "#654907", "#f2d75d", "stripes", 2),
        "rubber": material("#17191b", "#060708", "#393d3e", "solid", 5),
        "cloth": material("#263a4d", "#111e2b", "#536f88", "solid", 4),
        "cloth_light": material("#49677f", "#23394c", "#7896ae", "solid", 3),
        "trouser_blue": material("#3c5a72", "#1c3144", "#7190a8", "solid", 3),
        "skin": material("#9e665d", "#53312f", "#d99a84", "solid", 3),
        "skin_light": material("#bd7b6d", "#6c3d38", "#e9aa90", "solid", 2),
        "implant": material("#3e4648", "#161b1d", "#798084", "stripes", 2),
        "optic_red": material("#e13a21", "#5b0b08", "#ff7b3d", "solid", 1),
        "hose": material("#30383b", "#101416", "#596367", "stripes", 2),
        "hose_yellow": material("#b78b24", "#533c08", "#e3c255", "stripes", 2),
        "heat_rose": material("#ad786f", "#583c39", "#dda69a", "stripes", 2),
        "shield": material("#713516", "#2d140b", "#b4662d", "solid", 4),
        "shield_light": material("#9b5223", "#4b2010", "#d8843e", "stripes", 3),
        "shield_dark": material("#49200f", "#1c0c08", "#7c3b1d", "solid", 5),
        "label": material("#d8ddd5", "#747b78", "#f7f8ee", "solid", 1),
    }

    builder = SemanticModelBuilder()
    attachments: list[tuple[str, str, Point]] = []
    contact_constraints: list[tuple[str, str, Point]] = []

    for name, parent, pivot in (
        ("exo_pelvis", "root", (0, 58, 0)),
        ("torso_frame", "exo_pelvis", (0, 66, -1)),
        ("backpack", "torso_frame", (0, 76, -7)),
        ("pilot_pelvis", "exo_pelvis", (0, 57, 3)),
        ("pilot_torso", "pilot_pelvis", (0, 69, 3)),
        ("pilot_head", "pilot_torso", (0, 90, 4)),
        ("pilot_left_arm", "pilot_torso", (-6, 75, 4)),
        ("pilot_right_arm", "pilot_torso", (6, 75, 4)),
        ("pilot_left_leg", "pilot_pelvis", (-4, 56, 2)),
        ("pilot_right_leg", "pilot_pelvis", (4, 56, 2)),
        ("left_exo_hip", "exo_pelvis", (-10, 57, 0)),
        ("left_exo_thigh", "left_exo_hip", (-11, 55, 0)),
        ("left_exo_knee", "left_exo_thigh", (-22, 33, 10)),
        ("left_exo_shin", "left_exo_knee", (-22, 31, 10)),
        ("left_exo_ankle", "left_exo_shin", (-20, 9, 0)),
        ("left_exo_foot", "left_exo_ankle", (-22, 5, 3)),
        ("right_exo_hip", "exo_pelvis", (10, 57, 0)),
        ("right_exo_thigh", "right_exo_hip", (11, 55, 0)),
        ("right_exo_knee", "right_exo_thigh", (22, 33, 10)),
        ("right_exo_shin", "right_exo_knee", (22, 31, 10)),
        ("right_exo_ankle", "right_exo_shin", (20, 9, 0)),
        ("right_exo_foot", "right_exo_ankle", (22, 5, 3)),
        ("shield_boom", "backpack", (7, 80, -6)),
        ("shield", "shield_boom", shield_point(0, 16, 15)),
        ("shield_lower_actuator", "torso_frame", (8, 70, 2)),
        ("tool_boom", "backpack", (-7, 79, -6)),
        ("thermal_weapon", "tool_boom", (-27, 71, 8)),
    ):
        builder.add_bone(name, parent, pivot)

    def add(cube: dict[str, Any], parent: str | None, joint: Sequence[float]) -> str:
        """Add a cuboid and exactly one structural-tree contact."""
        builder.add_cube(cube)
        if parent is not None:
            attachments.append((parent, str(cube["name"]), tuple(float(v) for v in joint)))
        return str(cube["name"])

    # Load-bearing pelvis and torso frame. These volumes are deliberately wider
    # than the operator, making the human-within-machine relationship legible.
    add(box("pelvis_frame_core", "exo_pelvis", (0, 58, -5.5), (22, 7, 3),
            "open-frame rear pelvis bridge behind the replaceable wearer", "frame_dark"),
        None, (0, 58, -5.5))
    add(box("pelvis_front_armor", "exo_pelvis", (0, 58, 7.5), (18, 4, 2.2),
            "narrow front waist restraint leaving the torso cavity open", "frame_blue",
            rotation=(8, 0, 0)),
        "left_pelvis_cheek", (-9.0, 58, 6.7))
    add(box("pelvis_rear_crossbar", "exo_pelvis", (0, 59, -7.0), (25, 4.5, 3.0),
            "rear hip load crossbar", "frame_black"),
        "pelvis_frame_core", (0, 59, -6.5))
    add(box("saddle_core", "exo_pelvis", (0, 60.5, -2.5), (10, 5, 3),
            "rear lumbar saddle pad behind the replaceable wearer", "rubber"),
        "pelvis_frame_core", (0, 60, -4.0))
    add(box("torso_frame_spine", "torso_frame", (0, 70, -4.8), (5, 19, 5),
            "central exoframe spine behind operator", "frame_black"),
        "pelvis_frame_core", (0, 61, -5.0))
    add(box("shoulder_frame_crossbar", "torso_frame", (0, 77, -5.5), (24, 5, 4),
            "rear equipment shoulder frame leaving the wearer cavity open", "frame_dark"),
        "torso_frame_spine", (0, 76, -4))
    for side, sign in (("left", -1.0), ("right", 1.0)):
        add(box(f"{side}_pelvis_cheek", "exo_pelvis", (sign * 10.7, 58, 0), (4, 8, 14),
                f"{side} layered hip cheek", "frame_blue"),
            "pelvis_frame_core", (sign * 10.0, 58, -5.5))
        add(box(f"{side}_waist_brace", "torso_frame", (sign * 8.0, 66, -3), (4, 11, 4),
                f"{side} open torso-frame waist rail", "frame_dark"),
            f"{side}_pelvis_cheek", (sign * 9.5, 61, -3))

    # Human pilot: clothing and flesh are separate from all mechanical frame
    # materials, and the pilot's legs sit inside rather than replacing the exo legs.
    add(box("pilot_pelvis_core", "pilot_pelvis", (0, 57.5, 3), (11, 8, 9),
            "operator pelvis inside exoframe", "cloth"),
        "saddle_core", (0, 59, -1.25))
    add(box("pilot_abdomen", "pilot_torso", (0, 66, 3), (12, 11, 9),
            "operator lower torso", "cloth"),
        "pilot_pelvis_core", (0, 61, 3))
    add(box("pilot_chest", "pilot_torso", (0, 76, 3), (15, 11, 10),
            "operator broad chest", "cloth_light", rotation=(-3, 0, 0)),
        "pilot_abdomen", (0, 70.5, 3))
    add(box("pilot_neck", "pilot_head", (0, 86.0, 4), (4.5, 10, 4.5),
            "exposed operator neck", "skin"),
        "pilot_chest", (0, 81.0, 4))
    add(box("pilot_head_core", "pilot_head", (0, 94.0, 4.6), (9, 10, 8.5),
            "bald operator head", "skin", rotation=(-4, 0, 0)),
        "pilot_neck", (0, 90.0, 4.2))
    add(box("pilot_brow", "pilot_head", (0, 95.2, 9.0), (8, 2, 1.1),
            "heavy augmented brow", "skin_light"),
        "pilot_head_core", (0, 95.2, 8.7))
    add(box("pilot_jaw", "pilot_head", (0, 90.8, 8.2), (7, 3.5, 2.2),
            "square bearded jaw", "skin"),
        "pilot_head_core", (0, 91.5, 8.1))
    add(box("pilot_nose", "pilot_head", (0, 93.2, 9.4), (2.0, 3.0, 1.6),
            "projecting scarred operator nose", "skin_light"),
        "pilot_head_core", (0, 93.2, 8.7))
    for side, sign in (("left", -1.0), ("right", 1.0)):
        add(box(f"pilot_{side}_temple_implant", "pilot_head", (sign * 4.35, 94.5, 5.5),
                (1.1, 5, 4), f"{side} cranial implant plate", "implant"),
            "pilot_head_core", (sign * 4.0, 94.5, 5.5))
        add(box(f"pilot_{side}_optic", "pilot_head", (sign * 2.0, 95.2, 9.45),
                (1.4, 1.2, 0.9), f"{side} glowing cyber-optic", "optic_red"),
            "pilot_brow", (sign * 2.0, 95.2, 9.0))

    # Pilot arms bend forward to machine controls. Four distinct segments and
    # grips prevent the operator from reading as an armor-texture decal.
    for side, sign in (("left", -1.0), ("right", 1.0)):
        shoulder = (sign * 6.2, 78, 4)
        elbow = (sign * 10.0, 69, 8)
        hand = (sign * 7.0, 66, 12)
        upper = add(segment_cube(f"pilot_{side}_upper_arm", f"pilot_{side}_arm",
                                 shoulder, elbow, (4.4, 4.8),
                                 f"operator {side} sleeved upper arm", "cloth_light",
                                 overlap=0.5),
                    "pilot_chest", shoulder)
        fore = add(segment_cube(f"pilot_{side}_forearm", f"pilot_{side}_arm",
                                elbow, hand, (3.6, 3.8),
                                f"operator {side} forearm", "skin", overlap=0.45),
                   upper, elbow)
        add(box(f"pilot_{side}_control_grip", f"pilot_{side}_arm", hand,
                (3.3, 3.3, 4.5), f"operator {side} hand around control", "skin_light"),
            fore, hand)
        add(box(f"{side}_hand_control_stick", "torso_frame",
                (sign * 7.0, 62.5, 10.5), (2.0, 7, 7.0),
                f"{side} exoframe control stick", "frame_black", rotation=(8, 0, sign * 5)),
            "pelvis_front_armor", (sign * 7.0, 59.5, 7.2))

    # The human legs remain visible inside the powered struts.
    pilot_boots: dict[str, str] = {}
    pilot_leg_records: list[dict[str, Any]] = []
    for side, sign in (("left", -1.0), ("right", 1.0)):
        hip = (sign * 4.0, 56, 2.5)
        knee = (sign * 10.0, 36, 8.0)
        ankle = (sign * 13.0, 18, 4.0)
        thigh = add(segment_cube(f"pilot_{side}_thigh", f"pilot_{side}_leg", hip, knee,
                                 (5.5, 5.8), f"operator {side} trouser thigh", "trouser_blue",
                                 overlap=0.55),
                    "pilot_pelvis_core", hip)
        calf = add(segment_cube(f"pilot_{side}_calf", f"pilot_{side}_leg", knee, ankle,
                                (4.3, 4.8), f"operator {side} trouser calf", "trouser_blue",
                                overlap=0.5),
                   thigh, knee)
        pilot_boots[side] = add(
            box(f"pilot_{side}_boot", f"pilot_{side}_leg", (sign * 13.0, 17.0, 5.0),
                (5.5, 6, 7), f"operator {side} boot retained inside exoframe ankle", "rubber"),
            calf, ankle,
        )
        pilot_leg_records.append(
            {
                "side": side,
                "joints": [list(hip), list(knee), list(ankle)],
                "segments": [thigh, calf],
                "boot": pilot_boots[side],
            }
        )

    # Two independent massive powered leg chains. Each includes armor shells,
    # open rails, hinge drums, a visible piston, grounded foot, heel, and toes.
    exo_leg_records: list[dict[str, Any]] = []
    for side, sign in (("left", -1.0), ("right", 1.0)):
        hip = (sign * 11.0, 56.0, 0.0)
        knee = (sign * 22.0, 33.0, 10.0)
        ankle = (sign * 20.0, 9.0, 0.0)
        hip_block = add(box(f"{side}_exo_hip_block", f"{side}_exo_hip", hip, (11.5, 11, 13.5),
                            f"{side} massive powered hip housing", "frame_dark"),
                        f"{side}_pelvis_cheek", (sign * 10.0, 57.0, 0.0))
        for face, z_value in (("front", 5.7), ("rear", -5.7)):
            add(box(f"{side}_hip_{face}_drum", f"{side}_exo_hip",
                    (hip[0], hip[1], z_value), (8.0, 8.0, 2.2),
                    f"{side} hip {face} drive drum", "brass" if face == "front" else "edge_steel"),
                hip_block, (hip[0], hip[1], 5.0 if z_value > 0 else -5.0))

        thigh_cube = segment_cube(f"{side}_exo_thigh_beam", f"{side}_exo_thigh",
                                  hip, knee, (7.2, 8.2), f"{side} primary powered thigh beam",
                                  "frame_blue", overlap=0.8)
        thigh = add(thigh_cube, hip_block, hip)
        thigh_mid = midpoint(hip, knee)
        thigh_rotation = thigh_cube["rotation"]
        add(box(f"{side}_thigh_outer_armor", f"{side}_exo_thigh",
                (thigh_mid[0] + sign * 4.1, thigh_mid[1], thigh_mid[2]), (5.0, 19, 10.0),
                f"{side} massive outer thigh armor plate", "frame_dark",
                rotation=thigh_rotation),
            thigh, (thigh_mid[0] + sign * 2.8, thigh_mid[1], thigh_mid[2]))
        add(box(f"{side}_thigh_warning_panel", f"{side}_exo_thigh",
                (thigh_mid[0] + sign * 6.2, thigh_mid[1], thigh_mid[2] + 0.5),
                (1.4, 10.0, 6.0), f"{side} thigh identification panel", "warning",
                rotation=thigh_rotation),
            f"{side}_thigh_outer_armor", (thigh_mid[0] + sign * 5.5, thigh_mid[1], thigh_mid[2] + 0.5))
        brace_mid = (thigh_mid[0] - sign * 3.5, thigh_mid[1], thigh_mid[2] - 3.2)
        add(box(f"{side}_thigh_inner_rail", f"{side}_exo_thigh", brace_mid, (3.2, 19, 3.4),
                f"{side} exposed inner thigh rail", "edge_steel", rotation=thigh_rotation),
            thigh, (thigh_mid[0] - sign * 2.7, thigh_mid[1], thigh_mid[2] - 2.2))

        knee_block = add(box(f"{side}_exo_knee_core", f"{side}_exo_knee", knee,
                             (10, 10, 10), f"{side} massive knee hinge inside open tread guard", "frame_black"),
                         thigh, knee)
        for face, z_value in (("front", knee[2] + 3.8), ("rear", knee[2] - 3.8)):
            add(box(f"{side}_knee_{face}_drum", f"{side}_exo_knee",
                    (knee[0], knee[1], z_value), (7.5, 7.5, 2.2),
                    f"{side} knee {face} hinge drum", "brass" if face == "front" else "edge_steel"),
                knee_block, (knee[0], knee[1], knee[2] + (3.0 if face == "front" else -3.0)))
        add(box(f"{side}_knee_upper_fairing", f"{side}_exo_knee",
                (knee[0] + sign * 1.0, knee[1] + 5.0, knee[2]), (9.0, 3.5, 10),
                f"{side} angular upper knee fairing", "frame_blue", rotation=(0, 0, -sign * 8)),
            knee_block, (knee[0] + sign * 1.0, knee[1] + 5.0, knee[2]))
        guard_top = add(
            box(f"{side}_knee_tread_guard_top", f"{side}_exo_knee",
                (knee[0], knee[1] + 6.5, knee[2] + 5.5), (15.0, 3.2, 5.0),
                f"{side} projecting open U-guard top", "edge_steel"),
            f"{side}_knee_upper_fairing",
            (knee[0] + sign * 1.0, knee[1] + 5.0, knee[2] + 3.0),
        )
        guard_outer = add(
            box(f"{side}_knee_tread_guard_outer", f"{side}_exo_knee",
                (knee[0] + sign * 6.5, knee[1], knee[2] + 5.5), (3.2, 13.0, 5.0),
                f"{side} projecting open U-guard outer rail", "edge_steel"),
            guard_top,
            (knee[0] + sign * 5.0, knee[1] + 5.5, knee[2] + 5.5),
        )
        add(
            box(f"{side}_knee_tread_guard_bottom", f"{side}_exo_knee",
                (knee[0], knee[1] - 6.5, knee[2] + 5.5), (15.0, 3.2, 5.0),
                f"{side} projecting open U-guard bottom", "edge_steel"),
            guard_outer,
            (knee[0] + sign * 5.0, knee[1] - 5.5, knee[2] + 5.5),
        )
        rear_brace_start = (knee[0] - sign * 2.0, knee[1], knee[2] - 2.5)
        rear_brace_end = (ankle[0] - sign * 2.0, ankle[1] + 5.0, ankle[2] - 3.0)
        add(segment_cube(f"{side}_shin_rear_brace", f"{side}_exo_shin",
                         rear_brace_start, rear_brace_end, (2.7, 3.0),
                         f"{side} open triangular rear shin linkage", "edge_steel",
                         overlap=0.35),
            knee_block, rear_brace_start)

        shin_cube = segment_cube(f"{side}_exo_shin_beam", f"{side}_exo_shin",
                                 knee, ankle, (7.0, 8.0), f"{side} lower powered shin beam",
                                 "frame_dark", overlap=0.8)
        shin = add(shin_cube, knee_block, knee)
        shin_mid = midpoint(knee, ankle)
        shin_rotation = shin_cube["rotation"]
        add(box(f"{side}_shin_outer_armor", f"{side}_exo_shin",
                (shin_mid[0] + sign * 4.0, shin_mid[1], shin_mid[2]), (5.0, 23, 10.0),
                f"{side} massive outer shin armor", "frame_blue", rotation=shin_rotation),
            shin, (shin_mid[0] + sign * 2.8, shin_mid[1], shin_mid[2]))
        add(box(f"{side}_shin_inner_rail", f"{side}_exo_shin",
                (shin_mid[0] - sign * 3.5, shin_mid[1], shin_mid[2] - 3.0), (3.0, 22, 3.5),
                f"{side} open inner shin rail", "edge_steel", rotation=shin_rotation),
            shin, (shin_mid[0] - sign * 2.0, shin_mid[1], shin_mid[2] - 1.8))
        piston_start = (sign * 20.0, 31.0, 7.0)
        piston_mid = (sign * 19.5, 21.0, 0.5)
        piston_end = (sign * 20.0, 11.0, -0.5)
        casing = add(segment_cube(f"{side}_shin_piston_casing", f"{side}_exo_shin",
                                  piston_start, piston_mid, (4.0, 4.0),
                                  f"{side} hydraulic shin piston casing", "frame_black",
                                  overlap=0.45),
                     knee_block, piston_start)
        rod = add(segment_cube(f"{side}_shin_piston_rod", f"{side}_exo_shin",
                               piston_mid, piston_end, (2.3, 2.3),
                               f"{side} exposed hydraulic shin rod", "bright_steel",
                               overlap=0.4),
                  casing, piston_mid)
        ankle_block = add(box(f"{side}_exo_ankle_core", f"{side}_exo_ankle", ankle,
                              (9, 7, 10), f"{side} massive ankle hinge block", "frame_black"),
                          shin, ankle)
        contact_constraints.append((rod, ankle_block, piston_end))
        for face, z_value in (("front", ankle[2] + 3.7), ("rear", ankle[2] - 3.7)):
            add(box(f"{side}_ankle_{face}_drum", f"{side}_exo_ankle",
                    (ankle[0], ankle[1], z_value), (6.5, 6.5, 2.0),
                    f"{side} ankle {face} hinge", "edge_steel"),
                ankle_block, (ankle[0], ankle[1], ankle[2] + (3.0 if face == "front" else -3.0)))
        ankle_upper = add(box(f"{side}_ankle_upper_segment", f"{side}_exo_ankle",
                              (ankle[0], 12.0, ankle[2]), (10, 4, 10),
                              f"{side} upper segmented ankle collar", "edge_steel"),
                          ankle_block, (ankle[0], 10.5, ankle[2]))
        ankle_lower = add(box(f"{side}_ankle_lower_segment", f"{side}_exo_ankle",
                              (ankle[0], 6.0, ankle[2] + 1.0), (10, 4, 11),
                              f"{side} lower segmented ankle collar", "frame_blue"),
                          ankle_block, (ankle[0], 7.5, ankle[2] + 0.5))
        restraint = add(box(f"{side}_boot_stirrup", f"{side}_exo_ankle",
                            (sign * 16.5, 14.0, 2.5), (8.0, 2.4, 3.5),
                            f"{side} player boot stirrup coupled to powered ankle",
                            "brass"),
                        pilot_boots[side], (sign * 14.5, 14.5, 3.0))
        contact_constraints.append(
            (restraint, ankle_upper, (sign * 17.0, 13.25, 2.0))
        )
        foot = add(box(f"{side}_exo_ground_foot", f"{side}_exo_foot",
                       (sign * 22.0, 3.5, 6.0), (16, 7, 22),
                       f"{side} broad grounded powered foot", "rubber"),
                   ankle_lower, (sign * 20.0, 4.6, 1.0))
        add(box(f"{side}_foot_top_armor", f"{side}_exo_foot",
                (sign * 22.0, 6.0, 8.0), (14.0, 4.0, 14),
                f"{side} sloped foot top armor", "frame_blue", rotation=(-8, 0, 0)),
            foot, (sign * 22.0, 4.2, 7.0))
        add(box(f"{side}_heel_spur", f"{side}_exo_foot", (sign * 22.0, 3.0, -5.5),
                (10, 6, 7), f"{side} rear heel stabilizer", "frame_dark"),
            foot, (sign * 22.0, 2.5, -3.5))
        toe_names = []
        for toe_index, offset_x in enumerate((-4.0, 0.0, 4.0), start=1):
            toe_name = add(box(f"{side}_toe_{toe_index}", f"{side}_exo_foot",
                               (sign * 22.0 + offset_x, 2.0, 17.0), (3.2, 4.0, 10),
                               f"{side} articulated gripping toe {toe_index}", "frame_black",
                               rotation=(-12, sign * (toe_index - 2) * 10, 0),
                               faces={"south": {"material": "bright_steel"}}),
                           foot, (sign * 22.0 + offset_x, 2.2, 12.5))
            toe_names.append(toe_name)
        exo_leg_records.append(
            {
                "side": side,
                "joints": [list(hip), list(knee), list(ankle)],
                "ground_foot": foot,
                "ground_minimum_y": 0.0,
                "primary_segments": [thigh, shin],
                "piston": [casing, rod],
                "ankle_segments": [ankle_upper, ankle_block, ankle_lower],
                "boot_restraint": restraint,
                "toes": toe_names,
            }
        )

    # Rear equipment: twin canisters, electronics, spine and visible hoses.
    add(box("backpack_main", "backpack", (0, 78, -9), (18, 18, 9),
            "central electronics spine between twin power cylinders", "frame_dark"),
        "shoulder_frame_crossbar", (0, 77, -5.5))
    add(box("backpack_control_panel", "backpack", (0, 79, -12.9), (9, 10, 1.5),
            "rear electronics control panel", "frame_blue"),
        "backpack_main", (0, 79, -12.4))
    for side, sign in (("left", -1.0), ("right", 1.0)):
        add(box(f"backpack_{side}_canister", "backpack", (sign * 10.0, 76, -12),
                (7.5, 22, 10), f"{side} distinct tall power cylinder", "frame_black"),
            "backpack_main", (sign * 7.5, 76, -10))
        add(box(f"backpack_{side}_cap_top", "backpack", (sign * 10.0, 87.2, -12),
                (8.5, 3.0, 11.0), f"{side} canister upper collar", "edge_steel"),
            f"backpack_{side}_canister", (sign * 10.0, 86.0, -12))
        add(box(f"backpack_{side}_cap_bottom", "backpack", (sign * 10.0, 64.8, -12),
                (8.5, 3.0, 11.0), f"{side} canister lower collar", "edge_steel"),
            f"backpack_{side}_canister", (sign * 10.0, 65.5, -12))
        add(box(f"backpack_{side}_mid_collar", "backpack", (sign * 10.0, 76, -12),
                (8.5, 2.6, 11.0), f"{side} power-cylinder center band", "brass"),
            f"backpack_{side}_canister", (sign * 9.5, 76, -12))
    for cable_index, x_value in enumerate((-6.0, 6.0), start=1):
        start = (x_value, 84.0, -10.0)
        end = (x_value * 0.7, 93.0, -4.0)
        add(segment_cube(f"backpack_hose_{cable_index}", "backpack", start, end,
                         (1.25, 1.25), "arched backpack coolant hose", "hose",
                         overlap=0.3),
            "backpack_main", start)
    add(box("backpack_horizontal_actuator", "backpack", (14, 80, -9), (15, 7, 7),
            "right horizontal shoulder actuator", "frame_blue"),
        "backpack_main", (7.8, 80, -9))
    add(box("backpack_actuator_endcap", "backpack", (22, 80, -9), (3, 8, 8),
            "right shoulder actuator end cap", "bright_steel"),
        "backpack_horizontal_actuator", (20.5, 80, -9))

    # Shield carrier: a three-link overhead boom and a separate lower hydraulic
    # actuator terminate in two independently audited contacts on the shield.
    boom_points: tuple[Point, ...] = (
        (7, 82, -6), (10, 102, -4), (18, 112, 4), shield_point(0, 16, 14.6)
    )
    boom_parent = "backpack_main"
    boom_names = []
    for index in range(3):
        name = add(segment_cube(f"shield_boom_{index + 1}", "shield_boom",
                                boom_points[index], boom_points[index + 1],
                                (5.7 - index * 0.7, 6.5 - index * 0.7),
                                "overhead shield support boom", "frame_dark",
                                overlap=0.65),
                   boom_parent, boom_points[index])
        boom_names.append(name)
        boom_parent = name
        if index < 2:
            add(box(f"shield_boom_hinge_{index + 1}", "shield_boom", boom_points[index + 1],
                    (7, 7, 7), "shield boom hinge drum", "brass"),
                name, boom_points[index + 1])
    upper_contact = boom_points[-1]
    upper_pad = add(box("shield_upper_rear_pad", "shield", upper_contact, (6, 6, 3.0),
                        "upper mechanical shield contact pad", "frame_black",
                        rotation=SHIELD_ROTATION),
                    boom_names[-1], upper_contact)

    shield_core = add(box("shield_core", "shield", shield_point(0, 0, 16), (4.2, 49, 2.5),
                          "central load spine of open orange cellular shield", "shield_light",
                          rotation=SHIELD_ROTATION),
                      upper_pad, shield_point(0, 16, 15.0))
    # The shield is an actual cellular frame: perimeter rails and separated
    # narrow bays leave negative gaps rather than hiding an opaque backing slab.
    edge_names: dict[str, str] = {}
    for edge, local_y in (("top", 25.5), ("bottom", -25.5)):
        point = shield_point(0, local_y, 17.0)
        edge_names[edge] = add(
            box(f"shield_{edge}_edge_rail", "shield", point, (33, 3.5, 2.0),
                f"{edge} shield structural edge rail", "shield_light",
                rotation=SHIELD_ROTATION),
            shield_core,
            shield_point(0, 24.0 if edge == "top" else -24.0, 16.7),
        )
    for side, local_x in (("left", -15.7), ("right", 15.7)):
        point = shield_point(local_x, 0, 17.0)
        edge_names[side] = add(
            box(f"shield_{side}_edge_rail", "shield", point, (3.2, 50, 2.0),
                f"{side} shield structural edge rail", "shield_light",
                rotation=SHIELD_ROTATION),
            edge_names["top"],
            shield_point(local_x * 0.97, 24.5, 17.0),
        )
    for bay_index, local_x in enumerate((-10.8, -3.6, 3.6, 10.8), start=1):
        point = shield_point(local_x, 0.0, 17.2)
        bay = add(box(f"shield_grille_bay_{bay_index}", "shield", point, (5.3, 50, 1.6),
                      f"separated cellular shield spar {bay_index}", "shield_dark",
                      rotation=SHIELD_ROTATION),
                  edge_names["top"], shield_point(local_x, 24.5, 17.0))
        for rib_index, local_y in enumerate((-12, 0, 12), start=1):
            rib_point = shield_point(local_x, local_y - 1.0, 18.1)
            add(box(f"shield_bay_{bay_index}_rib_{rib_index}", "shield", rib_point,
                    (6.2, 1.6, 0.8), f"shield bay {bay_index} cellular cross rib {rib_index}",
                    "shield_light", rotation=SHIELD_ROTATION),
                bay, shield_point(local_x, local_y - 1.0, 17.75))
    for bolt_index, (side, local_x) in enumerate((("left", -15.7), ("right", 15.7)), start=1):
        local_y = 0.0
        point = shield_point(local_x, local_y, 17.9)
        add(box(f"shield_bolt_{bolt_index}", "shield", point, (1.4, 1.4, 2.0),
                f"shield face fastener {bolt_index}", "bright_steel",
                rotation=SHIELD_ROTATION),
            edge_names[side], shield_point(local_x, local_y, 17.15))
    # Block-letter identity mark, kept as raised label geometry because the
    # original is a large physical face marking rather than a tiny seam.
    for label_index, (bay_index, local_x, local_y) in enumerate(
        ((2, -3.6, 14.0), (3, 3.6, 12.0)), start=1
    ):
        point = shield_point(local_x, local_y, 17.9)
        add(box(f"shield_militech_mark_{label_index}", "shield", point,
                (3.6, 2.0, 1.8), "raised pale shield identification mark", "label",
                rotation=SHIELD_ROTATION),
            f"shield_grille_bay_{bay_index}", shield_point(local_x, local_y, 17.15))

    lower_points: tuple[Point, ...] = (
        (7, 69, -1), (12, 76, 7), shield_point(0, -10, 14.6)
    )
    lower_first = add(segment_cube("shield_lower_actuator_casing", "shield_lower_actuator",
                                   lower_points[0], lower_points[1], (4.0, 4.0),
                                   "lower shield hydraulic casing", "frame_black", overlap=0.5),
                      "right_waist_brace", lower_points[0])
    lower_second = add(segment_cube("shield_lower_actuator_rod", "shield_lower_actuator",
                                    lower_points[1], lower_points[2], (2.3, 2.3),
                                    "lower shield exposed hydraulic rod", "bright_steel",
                                    overlap=0.45),
                       lower_first, lower_points[1])
    lower_pad = add(box("shield_lower_rear_pad", "shield_lower_actuator", lower_points[2],
                        (5, 5, 3.0), "lower mechanical shield contact pad", "frame_black",
                        rotation=SHIELD_ROTATION),
                    lower_second, lower_points[2])
    contact_constraints.extend(
        [
            (upper_pad, shield_core, shield_point(0, 16, 15.0)),
            (lower_pad, shield_core, shield_point(0, -10, 15.0)),
        ]
    )

    # Opposite-side auxiliary manipulator/counterweight visible in front and rear.
    tool_points: tuple[Point, ...] = (
        (-7, 82, -6), (-15, 102, -3), (-24, 110, 3), (-30, 76, 10)
    )
    tool_parent = "backpack_main"
    tool_names = []
    for index in range(3):
        name = add(segment_cube(f"tool_boom_{index + 1}", "tool_boom",
                                tool_points[index], tool_points[index + 1],
                                (5.6 - index * 0.6, 6.2 - index * 0.6),
                                "left auxiliary articulated boom", "frame_dark",
                                overlap=0.6),
                   tool_parent, tool_points[index])
        tool_names.append(name)
        tool_parent = name
        add(box(f"tool_boom_hinge_{index + 1}", "tool_boom", tool_points[index + 1],
                (6.2, 6.2, 6.2), "auxiliary boom hinge housing", "edge_steel"),
            name, tool_points[index + 1])
    add(box("tool_receiver", "tool_boom", (-31, 72, 11), (12, 12, 14),
            "deep powered thermal-weapon receiver", "frame_black", rotation=(0, -8, 6)),
        tool_names[-1], tool_points[-1])
    for tine_index, offset_x in enumerate((-3.0, 0.0, 3.0), start=1):
        add(box(f"tool_gripper_tine_{tine_index}", "tool_boom",
                (-31 + offset_x, 64, 15), (2.0, 8, 6),
                f"auxiliary gripper tine {tine_index}", "edge_steel",
                rotation=(12, 0, (tine_index - 2) * 8)),
            "tool_receiver", (-31 + offset_x, 66.5, 13.5))

    # The front reference is dominated by a long thermal weapon crossing the
    # pilot's chest. It is a separate assembly carried by the auxiliary boom:
    # four grille bays, a rose heat-tube bank, pale muzzle, and top pipe guard.
    thermal_core = add(box("thermal_weapon_core", "thermal_weapon", (-3, 72, 14),
                           (60, 17, 16), "deep long chest-crossing thermal weapon chassis",
                           "frame_blue"),
                       "tool_receiver", (-28, 72, 11))
    add(box("thermal_weapon_top_cover", "thermal_weapon", (-2, 81.0, 14),
            (55, 3.0, 13), "stepped thermal weapon top armor", "frame_dark"),
        thermal_core, (-2, 80.0, 14))
    add(box("thermal_weapon_lower_rail", "thermal_weapon", (-1, 63.3, 14),
            (52, 3.0, 12), "deep thermal weapon lower reinforcement rail", "frame_black"),
        thermal_core, (-1, 64.0, 14))
    add(box("thermal_weapon_muzzle", "thermal_weapon", (-35.5, 72, 14),
            (7, 18, 17), "large pale stepped thermal emitter muzzle", "edge_steel"),
        thermal_core, (-32.5, 72, 14))
    add(box("thermal_weapon_rear_receiver", "thermal_weapon", (29, 72, 14),
            (6, 18, 17), "deep rear power receiver and shield-side endcap", "frame_dark"),
        thermal_core, (26.5, 72, 14))
    for bay_index, x_value in enumerate((-5.0, 3.0, 11.0, 19.0), start=1):
        bay = add(box(f"thermal_grille_bay_{bay_index}", "thermal_weapon",
                      (x_value, 72, 22.3), (6.5, 12.5, 2.0),
                      f"thermal radiator grille bay {bay_index}", "frame_black"),
                  thermal_core, (x_value, 72, 21.8))
        for rib_index, y_value in enumerate((68.5, 75.5), start=1):
            add(box(f"thermal_grille_{bay_index}_rib_{rib_index}", "thermal_weapon",
                    (x_value, y_value, 23.1), (6.0, 1.0, 1.0),
                    f"radiator bay {bay_index} cross rib {rib_index}", "edge_steel"),
                bay, (x_value, y_value, 22.7))
    for tube_index, x_value in enumerate((-27.0, -24.2, -21.4, -18.6, -15.8), start=1):
        add(box(f"thermal_heat_tube_{tube_index}", "thermal_weapon",
                (x_value, 72, 22.5), (1.6, 12.0, 2.0),
                f"rose thermal exchanger tube {tube_index}", "heat_rose"),
            thermal_core, (x_value, 72, 21.9))
    pipe_first = add(segment_cube("thermal_top_pipe_1", "thermal_weapon",
                                  (-28, 81.5, 19), (-5, 84, 19), (2.0, 2.0),
                                  "upper tubular thermal guard", "edge_steel", overlap=0.35,
                                  longitudinal_axis="z"),
                     "thermal_weapon_top_cover", (-28, 81.5, 19))
    add(segment_cube("thermal_top_pipe_2", "thermal_weapon",
                     (-5, 84, 19), (22, 81.5, 19), (2.0, 2.0),
                     "upper tubular thermal guard return", "edge_steel", overlap=0.35,
                     longitudinal_axis="z"),
        pipe_first, (-5, 84, 19))

    # Small explicit surface details: mechanically plausible seams, labels, and
    # hose runs are retained without turning the subject into voxel soup.
    for index, x_value in enumerate((-7.5, -2.5, 2.5, 7.5), start=1):
        add(box(f"pelvis_service_panel_{index}", "exo_pelvis", (x_value, 58.0, 7.9),
                (3.4, 3.2, 0.8), f"pelvis front service panel {index}", "edge_steel"),
            "pelvis_front_armor", (x_value, 58.0, 7.5))
    for side, sign in (("left", -1.0), ("right", 1.0)):
        cable_points = (
            (sign * 7.5, 64, -5), (sign * 12, 55, -5),
            (sign * 16, 39, -4), (sign * 16, 20, -3),
        )
        cable_parent = f"{side}_waist_brace"
        for index in range(3):
            cable_name = add(segment_cube(f"{side}_hydraulic_hose_{index + 1}", "torso_frame",
                                          cable_points[index], cable_points[index + 1],
                                          (1.15, 1.15), f"{side} continuous hydraulic hose",
                                          "hose_yellow" if index == 0 else "hose", overlap=0.28),
                             cable_parent, cable_points[index])
            cable_parent = cable_name

    landmarks: list[dict[str, Any]] = [
        {
            "name": "pilot_left_eye_glow",
            "cube": "pilot_head_core",
            "face": "south",
            "center_uv": [0.31, 0.39],
            "size": [2, 2],
            "color": "#ff482a",
            "center_color": "#fff0b0",
        },
        {
            "name": "pilot_right_eye_glow",
            "cube": "pilot_head_core",
            "face": "south",
            "center_uv": [0.69, 0.39],
            "size": [2, 2],
            "color": "#ff482a",
            "center_color": "#fff0b0",
        },
        {
            "name": "backpack_warning_triangle",
            "cube": "backpack_control_panel",
            "face": "north",
            "center_uv": [0.5, 0.48],
            "size": [4, 4],
            "color": "#d0a11f",
            "center_color": "#17191b",
        },
    ]

    feature_inventory = {
        "human_pilots": 1,
        "powered_exo_legs": len(exo_leg_records),
        "exo_primary_leg_segments": sum(len(record["primary_segments"]) for record in exo_leg_records),
        "grounded_exo_feet": len(exo_leg_records),
        "articulated_toes": sum(len(record["toes"]) for record in exo_leg_records),
        "human_leg_chains": 2,
        "human_arm_chains": 2,
        "boot_restraints": 2,
        "segmented_ankle_cuboids": 6,
        "shield_support_boom_segments": len(boom_names),
        "shield_physical_contacts": 2,
        "shield_grille_bays": 4,
        "shield_grille_ribs": 12,
        "knee_tread_guard_cuboids": 6,
        "shin_rear_braces": 2,
        "backpack_canisters": 2,
        "backpack_canister_collars": 6,
        "backpack_hoses": 2,
        "auxiliary_boom_segments": len(tool_names),
        "thermal_weapon_grille_bays": 4,
        "thermal_weapon_heat_tubes": 5,
        "hydraulic_hose_segments": 6,
    }
    spec = {
        "schema_version": 1,
        "id": "militech_centaur_piloted_exoskeleton",
        "reference": {
            "image": Path(os.path.relpath(REFERENCES[0][0].resolve(), OUTPUT.parent.resolve())).as_posix(),
            "sha256": REFERENCES[0][1],
            "width": 1000,
            "height": 1023,
        },
        "subject": {
            "type": "character",
            "description": (
                "A bald augmented Militech operator visibly nested in a two-legged powered "
                "exoskeleton, carrying a giant orange blast shield through an overhead boom"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "The three studio renders are uncalibrated and partially self-occluding",
                "The shield obscures the operator's front-right controls in two views",
                "Small rear labels and exact cable routing are conservatively inferred",
                "No visual-hull or hidden-geometry recovery is claimed from these views",
                "Source rights are unknown; all three references remain ignored and local",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [140, 192],
            "identity_features": [
                "one visible human pilot distinct from the surrounding machine",
                "exactly two massive articulated powered leg chains around two human legs",
                "large diagonally carried orange shield with grille bays and edge rails",
                "overhead shield boom plus independent lower actuator making two real contacts",
                "twin-canister electronics backpack and exposed hydraulic hoses",
                "opposite-side articulated auxiliary tool boom and gripper",
                "bald cybernetic head with paired red optics",
                "broad grounded feet with three gripping toes each",
            ],
            "required_views": [
                "source-6-perspective", "source-7-perspective", "source-8-perspective",
                "front", "back", "left", "right", "top", "isometric",
                "pilot-closeup", "leg-closeup", "shield-contact-closeup", "backpack-closeup",
                "thermal-weapon-closeup",
            ],
            "review_targets": [
                "pilot-versus-frame separation", "two-leg count", "human legs within frame",
                "shield scale and diagonal", "dual shield contacts", "leg articulation",
                "backpack volume", "auxiliary boom", "ground contacts", "multiview consistency",
            ],
        },
        "geometry": {"precision": 20},
        "texture": {
            "density": 1,
            "palette_size": 32,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": landmarks,
        "collision": {"width": 2.2, "height": 4.6, "eye_height": 4.0},
        "wearable": {
            "target": "minecraft_player",
            "player_variant": "classic",
            "occupant_mode": "replaceable",
            "occupant_bones": [
                "pilot_pelvis",
                "pilot_torso",
                "pilot_head",
                "pilot_left_arm",
                "pilot_right_arm",
                "pilot_left_leg",
                "pilot_right_leg",
            ],
            "shell_root_bone": "exo_pelvis",
            "attachable_identifier": "img2blockbench:militech_centaur_exoskeleton",
            "shell_identity_features": [
                "open central cavity sized around a classic Minecraft player",
                "paired powered hip, knee, ankle, and grounded foot chains",
                "large diagonal amber shield on two independent supports",
                "opposed long thermal weapon and external spine power pack",
                "waist harness, hand controls, and two boot stirrups",
            ],
            "shell_review_targets": [
                "player clearance",
                "six wearable attachment anchors",
                "powered leg separation",
                "shield and thermal weapon silhouette",
                "direct-source texture fidelity",
            ],
            "fit": {
                "scale": 0.4,
                "offset": [0.0, -5.6, -1.2],
                "player_anchor": [0.0, 14.0, 3.0],
                "player_height": 85.0,
            },
            "collision": {"width": 1.6, "height": 2.8, "eye_height": 2.3},
            "attachment_points": [
                {
                    "name": "waist_harness",
                    "bone": "exo_pelvis",
                    "position": [0, 58, 1],
                },
                {
                    "name": "back_harness",
                    "bone": "torso_frame",
                    "position": [0, 72, -2],
                },
                {
                    "name": "left_boot_stirrup",
                    "bone": "left_exo_ankle",
                    "position": [-16.5, 14, 2.5],
                },
                {
                    "name": "right_boot_stirrup",
                    "bone": "right_exo_ankle",
                    "position": [16.5, 14, 2.5],
                },
                {
                    "name": "left_hand_control",
                    "bone": "torso_frame",
                    "position": [-7, 66, 12],
                },
                {
                    "name": "right_hand_control",
                    "bone": "torso_frame",
                    "position": [7, 66, 12],
                },
            ],
        },
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "multiview-replaceable-player-exoframe-v2",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "view_count": 3,
            "visual_hull_used": False,
            "hidden_geometry_established": False,
            "single_view_hidden_geometry": "not_applicable_three_uncalibrated_views",
            "view_limitations": {
                "image-6.png": "front three-quarter; shield hides right-side mechanisms",
                "image-7.png": "side three-quarter; shield hides much of operator front",
                "image-8.png": "rear three-quarter; exposes backpack but hides face and controls",
            },
            "feature_inventory": feature_inventory,
            "exo_leg_chains": exo_leg_records,
            "pilot_leg_chains": pilot_leg_records,
            "shield_contacts": [
                {"name": "upper_boom", "first": upper_pad, "second": shield_core,
                 "joint": list(shield_point(0, 16, 15.0))},
                {"name": "lower_actuator", "first": lower_pad, "second": shield_core,
                 "joint": list(shield_point(0, -10, 15.0))},
            ],
            "pilot_exoframe_contacts": [
                {
                    "side": side,
                    "first": f"{side}_boot_stirrup",
                    "second": f"{side}_ankle_upper_segment",
                    "joint": [(-17.0 if side == "left" else 17.0), 13.25, 2.0],
                }
                for side in ("left", "right")
            ],
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        },
    }

    if len(attachments) != len(builder.cubes) - 1:
        raise AssertionError(
            f"declared structural contacts must form an N-1 tree: {len(attachments)} links, "
            f"{len(builder.cubes)} cubes"
        )
    structural = audit_attachments(spec, attachments)
    if not structural["all_connected"]:
        failures = [record for record in structural["attachments"] if not record["connected"]]
        raise AssertionError(failures[:8])
    contacts = audit_attachments(spec, contact_constraints)
    if not contacts["all_connected"]:
        failures = [record for record in contacts["attachments"] if not record["connected"]]
        raise AssertionError(failures)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
