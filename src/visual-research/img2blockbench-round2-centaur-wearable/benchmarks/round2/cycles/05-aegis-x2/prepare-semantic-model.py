#!/usr/bin/env python3
"""Author the Round 2 Aegis X2 as a native articulated hard-surface turret."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from semantic_geometry import SemanticModelBuilder, segment_cube


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
OUTPUT = CYCLE / "model-spec.json"
REFERENCES = (
    (ROOT / "image-3.png", "31bb69536ce0f26540034096402cebc6e006ee9cb7ec56b38deb5bf04afb2e23"),
    (ROOT / "image-4.png", "d53b51bd62a7f64f1a4c792f1bd1005de204ed1ba0475ca4fb527784163ade4b"),
    (ROOT / "image-5.png", "83f83385de5d68c3b4b1f8bc7d371dc086780f4388754a8414b07f0294cfe7a6"),
)
UPPER_LIFT = 20.0
WEAPON_X_SCALE = 0.70


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "solid",
    scale: int = 1,
) -> dict[str, Any]:
    """Create one deterministic Minecraft-native hard-surface material."""
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
    rotation: Sequence[float] = (0, 0, 0),
    origin: Sequence[float] | None = None,
    faces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one semantically named native cuboid."""
    center_values = [float(value) for value in center]
    size_values = [float(value) for value in size]
    origin_values = [float(value) for value in (origin or center)]
    if bone in {"cannon", "launcher", "sensors"}:
        center_values[0] *= WEAPON_X_SCALE
        size_values[0] *= WEAPON_X_SCALE
        origin_values[0] *= WEAPON_X_SCALE
    return {
        "name": name,
        "bone": bone,
        "center": center_values,
        "size": size_values,
        "rotation": [float(value) for value in rotation],
        "origin": origin_values,
        "role": role,
        "material": material_name,
        "faces": dict(faces or {}),
    }


def point_on_ring(
    radius: float, azimuth_degrees: float, height: float
) -> tuple[float, float, float]:
    """Return one point on an X/Z radial ring."""
    angle = math.radians(azimuth_degrees)
    return radius * math.sin(angle), height, radius * math.cos(angle)


def midpoint(first: Sequence[float], second: Sequence[float]) -> tuple[float, float, float]:
    """Return the midpoint of two three-dimensional points."""
    return tuple((float(first[index]) + float(second[index])) / 2 for index in range(3))


def weapon_segment(
    name: str,
    bone: str,
    start: Sequence[float],
    end: Sequence[float],
    thickness: float | Sequence[float],
    role: str,
    material_name: str,
    *,
    overlap: float,
) -> dict[str, Any]:
    """Create a segment after applying the shared weapon-axis scale."""
    scaled_start = (float(start[0]) * WEAPON_X_SCALE, float(start[1]), float(start[2]))
    scaled_end = (float(end[0]) * WEAPON_X_SCALE, float(end[1]), float(end[2]))
    return segment_cube(
        name,
        bone,
        scaled_start,
        scaled_end,
        thickness,
        role,
        material_name,
        overlap=overlap,
    )


def main() -> None:
    """Write a detailed turret with four grounded outriggers and two weapon axes."""
    for path, digest in REFERENCES:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"unexpected Aegis reference hash: {path.name}")
        with Image.open(path) as opened:
            if opened.size != (1000, 1000):
                raise ValueError(f"unexpected Aegis reference size: {path.name} {opened.size}")

    materials = {
        "gunmetal": material("#424950", "#20252a", "#737d85", "solid", 1),
        "gunmetal_light": material("#65717a", "#353d43", "#a1adb4", "solid", 1),
        "gunmetal_dark": material("#262c31", "#101417", "#4a535a", "solid", 1),
        "edge_black": material("#171b1f", "#090b0d", "#3a4147", "solid", 1),
        "steel": material("#899398", "#495156", "#c9d0d2", "stripes", 3),
        "piston": material("#b8c1c3", "#61696c", "#e5e9e9", "gradient", 4),
        "rubber": material("#25272a", "#0b0d0f", "#494d51", "solid", 1),
        "copper": material("#9f5d46", "#4e281f", "#d59170", "stripes", 2),
        "cable_red": material("#a72d31", "#4f1218", "#e35e5d", "solid", 1),
        "sensor": material("#20343a", "#0b1519", "#6d8f95", "gradient", 3),
        "warning": material("#d4a723", "#654a08", "#f6dd67", "stripes", 2),
        "label": material("#d5dad8", "#737b79", "#f5f7f3", "solid", 1),
        "muzzle": material("#0d1012", "#030405", "#30373b", "solid", 1),
    }

    builder = SemanticModelBuilder()
    for name, parent, pivot in (
        ("pedestal", "root", (0, 0, 0)),
        ("yaw_ring", "pedestal", (0, 35, 0)),
        ("pitch_cradle", "yaw_ring", (0, 50, 0)),
        ("cannon", "pitch_cradle", (0, 52, 0)),
        ("launcher", "pitch_cradle", (0, 52, 0)),
        ("sensors", "pitch_cradle", (0, 52, 0)),
    ):
        builder.add_bone(name, parent, pivot)

    attachments: list[tuple[str, str, tuple[float, float, float]]] = []

    def add(
        cube: dict[str, Any],
        parent: str | None = None,
        joint: Sequence[float] | None = None,
    ) -> str:
        builder.add_cube(cube)
        if parent is not None:
            if joint is None:
                raise ValueError(f"attachment joint required for {cube['name']}")
            joint_values = [float(value) for value in joint]
            if cube["bone"] in {"cannon", "launcher", "sensors"} or cube["name"].startswith(
                ("copper_power_cable_", "red_weapon_cable_")
            ):
                joint_values[0] *= WEAPON_X_SCALE
            attachments.append((parent, cube["name"], tuple(joint_values)))
        return str(cube["name"])

    # Layered central pedestal: square load core, segmented panels, collars and yaw ring.
    add(box("pedestal_lower_core", "pedestal", (0, 7, 0), (18, 14, 18),
            "load-bearing lower pedestal", "gunmetal_dark"))
    add(box("pedestal_lower_front", "pedestal", (0, 8, 9.4), (13, 10, 2),
            "front lower pedestal service panel", "gunmetal"),
        "pedestal_lower_core", (0, 8, 8.5))
    add(box("pedestal_lower_back", "pedestal", (0, 8, -9.4), (13, 10, 2),
            "rear lower pedestal service panel", "gunmetal"),
        "pedestal_lower_core", (0, 8, -8.5))
    add(box("pedestal_lower_left", "pedestal", (-9.4, 8, 0), (2, 10, 13),
            "left lower pedestal service panel", "gunmetal"),
        "pedestal_lower_core", (-8.5, 8, 0))
    add(box("pedestal_lower_right", "pedestal", (9.4, 8, 0), (2, 10, 13),
            "right lower pedestal service panel", "gunmetal"),
        "pedestal_lower_core", (8.5, 8, 0))
    add(box("pedestal_lower_cap", "pedestal", (0, 14.2, 0), (20, 2.5, 20),
            "wide lower outrigger mounting collar", "gunmetal_light"),
        "pedestal_lower_core", (0, 13.5, 0))
    add(box("pedestal_mid_core", "pedestal", (0, 23, 0), (16, 16, 16),
            "segmented cylindrical-equivalent pedestal column", "gunmetal"),
        "pedestal_lower_cap", (0, 15.2, 0))
    for side, center, size, joint in (
        ("front", (0, 23, 8.3), (11, 11, 1.5), (0, 23, 7.75)),
        ("back", (0, 23, -8.3), (11, 11, 1.5), (0, 23, -7.75)),
        ("left", (-8.3, 23, 0), (1.5, 11, 11), (-7.75, 23, 0)),
        ("right", (8.3, 23, 0), (1.5, 11, 11), (7.75, 23, 0)),
    ):
        add(box(f"pedestal_mid_{side}_panel", "pedestal", center, size,
                f"{side} recessed pedestal access panel", "gunmetal_dark"),
            "pedestal_mid_core", joint)
    for index, azimuth in enumerate((45.0, 135.0, 225.0, 315.0), start=1):
        center = point_on_ring(7.55, azimuth, 23.0)
        joint = point_on_ring(6.9, azimuth, 23.0)
        add(
            box(
                f"pedestal_mid_corner_chamfer_{index}",
                "pedestal",
                center,
                (5.0, 11.0, 1.8),
                "vertical chamfer panel forming a segmented cylindrical pedestal",
                "gunmetal_light",
                rotation=(0, azimuth, 0),
            ),
            "pedestal_mid_core",
            joint,
        )
    add(box("pedestal_upper_cap", "pedestal", (0, 31.2, 0), (18.5, 2.5, 18.5),
            "upper pedestal bearing collar", "gunmetal_light"),
        "pedestal_mid_core", (0, 30.5, 0))
    add(box("yaw_ring_core", "yaw_ring", (0, 35, 0), (20, 5.5, 20),
            "rotating yaw bearing core", "edge_black"),
        "pedestal_upper_cap", (0, 32.35, 0))
    for index in range(8):
        first = point_on_ring(11.0, index * 45.0, 35.0)
        second = point_on_ring(11.0, (index + 1) * 45.0, 35.0)
        name = f"yaw_ring_segment_{index + 1}"
        add(segment_cube(name, "yaw_ring", first, second, (2.8, 3.0),
                         "segmented octagonal yaw collar", "gunmetal_light",
                         overlap=0.45, longitudinal_axis="z"),
            "yaw_ring_core", midpoint(first, second))

    # Four radial outriggers. Each has a grounded pad, a vertical outer piston,
    # an inner stabilizer piston, a red hydraulic line and a distinct root bone.
    outrigger_records: list[dict[str, Any]] = []
    for support_index, azimuth in enumerate((45.0, 135.0, 225.0, 315.0), start=1):
        support = f"support_{support_index}"
        root = point_on_ring(8.0, azimuth, 12.0)
        builder.add_bone(support, "pedestal", root)
        inner = point_on_ring(10.0, azimuth, 12.0)
        elbow = point_on_ring(21.0, azimuth, 10.0)
        crown = point_on_ring(29.0, azimuth, 18.0)
        ankle = point_on_ring(29.0, azimuth, 2.0)
        outer = point_on_ring(35.0, azimuth, 1.2)
        tangent_angle = math.radians(azimuth + 90.0)
        tangent = (math.sin(tangent_angle), 0.0, math.cos(tangent_angle))

        beam_1 = add(segment_cube(f"{support}_radial_beam", support, inner, elbow,
                                  (4.6, 5.2), "radial armored outrigger beam",
                                  "gunmetal", overlap=0.7, longitudinal_axis="z"),
                     "pedestal_lower_core", inner)
        brace = add(segment_cube(f"{support}_outer_brace", support, elbow, crown,
                                 (4.2, 4.8), "rising outer support bracket",
                                 "gunmetal_dark", overlap=0.7, longitudinal_axis="z"),
                    beam_1, elbow)
        casing_end = (crown[0], 9.0, crown[2])
        casing = add(segment_cube(f"{support}_outer_piston_casing", support, crown,
                                  casing_end, (4.2, 4.2), "vertical piston casing",
                                  "gunmetal_dark", overlap=0.5), brace, crown)
        rod = add(segment_cube(f"{support}_outer_piston_rod", support, casing_end,
                               ankle, (2.0, 2.0), "exposed vertical piston rod",
                               "piston", overlap=0.45), casing, casing_end)
        foot_center = point_on_ring(31.5, azimuth, 1.05)
        foot = add(box(f"{support}_ground_foot", support, foot_center, (6.0, 2.1, 10.0),
                       "broad radial grounded stabilizer foot", "rubber",
                       rotation=(0, azimuth, 0)), rod, ankle)
        add(segment_cube(f"{support}_outer_toe", support, ankle, outer, (2.4, 2.0),
                         "forward gripping foot extension", "gunmetal_light",
                         overlap=0.5, longitudinal_axis="z"), foot, ankle)
        heel = point_on_ring(27.0, azimuth, 1.2)
        add(segment_cube(f"{support}_inner_heel", support, ankle, heel, (2.4, 2.0),
                         "rear gripping foot extension", "gunmetal_light",
                         overlap=0.5, longitudinal_axis="z"), foot, ankle)
        add(box(f"{support}_foot_bolt", support,
                (foot_center[0], 2.35, foot_center[2]), (2.0, 1.0, 2.0),
                "bright foot anchor bolt", "steel"), foot,
            (foot_center[0], 2.0, foot_center[2]))

        inner_piston_top = point_on_ring(16.0, azimuth, 14.0)
        inner_piston_bottom = point_on_ring(20.5, azimuth, 3.0)
        inner_casing = add(segment_cube(f"{support}_inner_piston_casing", support,
                                        root, inner_piston_top, (3.2, 3.2),
                                        "inner hydraulic piston housing", "gunmetal_dark",
                                        overlap=0.45), "pedestal_lower_core", root)
        add(segment_cube(f"{support}_inner_piston_rod", support, inner_piston_top,
                         inner_piston_bottom, (1.45, 1.45),
                         "inner exposed hydraulic rod", "piston", overlap=0.45),
            inner_casing, inner_piston_top)

        cable_start = point_on_ring(9.5, azimuth, 14.5)
        cable_mid = point_on_ring(15.5, azimuth, 15.4)
        cable_end = point_on_ring(20.5, azimuth, 12.8)
        cable_1 = add(segment_cube(f"{support}_red_cable_1", support, cable_start,
                                   cable_mid, (1.0, 1.0), "red outrigger hydraulic line",
                                   "cable_red", overlap=0.3),
                      "pedestal_lower_cap", cable_start)
        add(segment_cube(f"{support}_red_cable_2", support, cable_mid, cable_end,
                         (1.0, 1.0), "red outrigger hydraulic line return",
                         "cable_red", overlap=0.3), cable_1, cable_mid)
        add(box(f"{support}_crown_cap", support, crown, (5.0, 2.2, 5.0),
                "outer piston hinge cap", "gunmetal_light",
                rotation=(0, azimuth, 0)), brace, crown)

        outrigger_records.append(
            {
                "name": support,
                "azimuth_degrees": azimuth,
                "root": list(root),
                "foot": foot,
                "ground_contact": [foot_center[0], 0.0, foot_center[2]],
                "outer_piston": [casing, f"{support}_outer_piston_rod"],
                "inner_piston": [inner_casing, f"{support}_inner_piston_rod"],
            }
        )

    # Pitch cradle and paired circular drive drums sit above the yaw bearing.
    add(box("cradle_lower_block", "pitch_cradle", (0, 42, 0), (16, 11, 15),
            "armored lower pitch cradle", "gunmetal_dark"),
        "yaw_ring_core", (0, 37.5, 0))
    add(box("cradle_crossbeam", "pitch_cradle", (0, 49, 0), (24, 7, 14),
            "cross-axis pitch cradle beam", "gunmetal"),
        "cradle_lower_block", (0, 45.5, 0))
    add(box("cradle_front_cheek", "pitch_cradle", (0, 48.5, 7.8), (16, 8, 3),
            "front cradle armor cheek", "gunmetal_light"),
        "cradle_crossbeam", (0, 48.5, 6.5))
    add(box("cradle_back_cheek", "pitch_cradle", (0, 48.5, -7.8), (16, 8, 3),
            "rear cradle armor cheek", "gunmetal_dark"),
        "cradle_crossbeam", (0, 48.5, -6.5))
    for side, z_value in (("front", 9.6), ("back", -9.6)):
        parent = "cradle_front_cheek" if side == "front" else "cradle_back_cheek"
        slab_names: list[str] = []
        slab_parent = parent
        drum_profile = ((-5, 7), (-2.5, 11), (0, 13), (2.5, 11), (5, 7))
        for index, (offset_y, width) in enumerate(drum_profile, start=1):
            name = f"{side}_drive_drum_slab_{index}"
            add(box(name, "pitch_cradle", (0, 50 + offset_y, z_value),
                    (width, 3.0, 2.8), "segmented circular pitch drive drum",
                    "gunmetal_light"), slab_parent,
                (
                    0,
                    45.5 if index == 1 else 46.25 + (index - 2) * 2.5,
                    (9.0 if z_value > 0 else -9.0) if index == 1 else z_value,
                ))
            slab_names.append(name)
            slab_parent = name
        hub_center = (0, 50, z_value + (1.7 if z_value > 0 else -1.7))
        add(box(f"{side}_drive_drum_hub", "pitch_cradle", hub_center,
                (3.2, 3.2, 2.0), "exposed pitch drive axle hub", "steel"),
            slab_names[2], (0, 50, z_value + (0.8 if z_value > 0 else -0.8)))

    # Long +X cannon: layered receiver, barrel, muzzle brake, rails and sights.
    add(box("cannon_receiver_core", "cannon", (13, 53, 0), (25, 12, 14),
            "long cannon receiver body", "gunmetal_dark"),
        "cradle_crossbeam", (2, 51, 0))
    add(box("cannon_receiver_top", "cannon", (13, 59.5, 0), (23, 3.5, 12),
            "raised cannon receiver top cover", "gunmetal"),
        "cannon_receiver_core", (13, 58.5, 0))
    add(box("cannon_receiver_bottom", "cannon", (14, 46.8, 0), (18, 3.0, 10),
            "lower recoil housing", "edge_black"),
        "cannon_receiver_core", (14, 48, 0))
    add(box("cannon_front_block", "cannon", (27, 53, 0), (6, 13, 13),
            "armored cannon trunnion block", "gunmetal"),
        "cannon_receiver_core", (24.5, 53, 0))
    add(box("cannon_side_panel_front", "cannon", (13, 53, 7.4), (16, 8, 1.6),
            "front-facing cannon service panel", "gunmetal_light"),
        "cannon_receiver_core", (13, 53, 6.6))
    add(box("cannon_side_panel_back", "cannon", (13, 53, -7.4), (16, 8, 1.6),
            "rear-facing cannon service panel", "gunmetal"),
        "cannon_receiver_core", (13, 53, -6.6))
    barrel_start = (28, 53, 0)
    barrel_mid = (45, 53.2, 0)
    barrel_end = (61, 53.4, 0)
    barrel_1 = add(weapon_segment("cannon_barrel_shroud", "cannon", barrel_start,
                                  barrel_mid, (6.2, 6.2), "thick cannon barrel shroud",
                                  "gunmetal_dark", overlap=0.7),
                   "cannon_front_block", barrel_start)
    barrel_2 = add(weapon_segment("cannon_barrel", "cannon", barrel_mid, barrel_end,
                                  (3.8, 3.8), "long exposed cannon barrel", "steel",
                                  overlap=0.6), barrel_1, barrel_mid)
    add(box("cannon_muzzle_brake", "cannon", (63.0, 53.45, 0), (6.0, 7.5, 7.5),
            "large rectangular muzzle brake", "gunmetal_light"), barrel_2, barrel_end)
    add(box("cannon_muzzle_bore", "cannon", (66.1, 53.45, 0), (1.0, 3.2, 3.2),
            "dark cannon bore opening", "muzzle"), "cannon_muzzle_brake", (65.8, 53.45, 0))
    for offset_z in (-3.3, 3.3):
        add(box(f"cannon_muzzle_port_{'front' if offset_z > 0 else 'back'}", "cannon",
                (63, 53.45, offset_z), (2.8, 2.6, 1.2),
                "muzzle brake side vent", "muzzle"),
            "cannon_muzzle_brake", (63, 53.45, offset_z * 0.85))
    add(weapon_segment("cannon_top_rail", "cannon", (5, 61.1, 0), (31, 61.1, 0),
                       (1.1, 2.0), "long top accessory rail", "steel", overlap=0.2),
        "cannon_receiver_top", (13, 60.9, 0))
    add(weapon_segment("cannon_lower_tube", "cannon", (13, 45.5, 3.0), (38, 49.5, 3.0),
                       (2.4, 2.4), "under-barrel recoil cylinder", "edge_black", overlap=0.4),
        "cannon_receiver_bottom", (14, 46.8, 3.0))
    add(box("cannon_front_sight", "sensors", (30.5, 60.0, 0), (5, 5, 4),
            "forward cannon sight box", "sensor"), "cannon_front_block", (29.5, 58.5, 0))

    # Opposed -X launcher/grip assembly: intentionally bulkier and shorter.
    add(box("launcher_receiver_core", "launcher", (-15, 53, 0), (27, 16, 18),
            "bulky opposed launcher receiver", "gunmetal"),
        "cradle_crossbeam", (-2, 51, 0))
    add(box("launcher_upper_housing", "launcher", (-16, 63, 0), (21, 7, 15),
            "high launcher electronics housing", "gunmetal_light"),
        "launcher_receiver_core", (-16, 60.5, 0))
    add(box("launcher_lower_housing", "launcher", (-15, 43.5, 0), (20, 5, 13),
            "heavy launcher lower grip block", "edge_black"),
        "launcher_receiver_core", (-15, 46.0, 0))
    add(box("launcher_front_panel", "launcher", (-15, 53, 9.7), (18, 10, 2),
            "front launcher hex-panel equivalent", "gunmetal_dark"),
        "launcher_receiver_core", (-15, 53, 8.9))
    add(box("launcher_back_panel", "launcher", (-15, 53, -9.7), (18, 10, 2),
            "rear launcher access panel", "gunmetal_dark"),
        "launcher_receiver_core", (-15, 53, -8.9))
    add(box("launcher_rear_block", "launcher", (-31, 53, 0), (8, 15, 16),
            "launcher rear breech block", "gunmetal_dark"),
        "launcher_receiver_core", (-28, 53, 0))
    add(box("launcher_tail_upper", "launcher", (-39, 58, 0), (10, 7, 13),
            "upper opposed weapon tail", "gunmetal"),
        "launcher_rear_block", (-34.5, 56, 0))
    add(box("launcher_tail_lower", "launcher", (-39, 48, 0), (10, 7, 13),
            "lower opposed weapon tail", "gunmetal_dark"),
        "launcher_rear_block", (-34.5, 50, 0))
    grip_points = ((-34.3, 48, 6), (-41, 42, 6), (-48, 47, 6), (-48, 55, 6))
    grip_parent = "launcher_tail_lower"
    grip_names = []
    for index in range(len(grip_points) - 1):
        name = f"launcher_grip_segment_{index + 1}"
        add(weapon_segment(name, "launcher", grip_points[index], grip_points[index + 1],
                           (2.4, 2.4), "angular operator/service grip cage", "steel",
                           overlap=0.35), grip_parent, grip_points[index])
        grip_parent = name
        grip_names.append(name)
    add(box("launcher_grip_pad", "launcher", (-46, 51, 7), (4, 8, 3.5),
            "dark inset launcher hand grip", "rubber", rotation=(0, 0, -12)),
        grip_names[-1], (-47.3, 51, 7))
    add(box("launcher_top_sensor", "sensors", (-19, 69, 0), (12, 6, 9),
            "raised launcher targeting sensor", "sensor"),
        "launcher_upper_housing", (-19, 66, 0))
    add(box("launcher_top_sensor_brow", "sensors", (-19, 72.4, 0), (14, 1.5, 10),
            "sensor rain brow", "gunmetal_light"),
        "launcher_top_sensor", (-19, 71.7, 0))
    add(box("launcher_hex_sensor", "sensors", (-19, 69, 4.9), (7, 4, 1.2),
            "six-cell launcher sensor plate", "sensor"),
        "launcher_top_sensor", (-19, 69, 4.4))

    # Copper power bundle and smaller red signal bundles bridge only adjacent housings.
    cable_records: list[str] = []
    for cable_index, z_offset in enumerate((-4.0, -2.0, 0.0, 2.0, 4.0), start=1):
        first = (-6, 61.5 + abs(z_offset) * 0.12, z_offset)
        second = (2, 58.5 + abs(z_offset) * 0.10, z_offset)
        name = f"copper_power_cable_{cable_index}"
        add(weapon_segment(name, "pitch_cradle", first, second, (1.0, 1.0),
                           "parallel copper weapon power bundle", "copper", overlap=0.25),
            "launcher_upper_housing", first)
        cable_records.append(name)
    for cable_index, (first, second) in enumerate(
        (
            ((-7, 45, -8), (0, 42, -7)),
            ((-7, 46, 8), (0, 43, 7)),
            ((4, 58, -7), (12, 61, -7)),
            ((4, 58, 7), (12, 61, 7)),
        ),
        start=1,
    ):
        name = f"red_weapon_cable_{cable_index}"
        parent = "launcher_receiver_core" if first[0] < 0 else "cannon_receiver_core"
        add(weapon_segment(name, "pitch_cradle", first, second, (0.8, 0.8),
                           "red weapon signal cable", "cable_red", overlap=0.2),
            parent, first)
        cable_records.append(name)

    # Ammo-feed ribs and small purposeful sensor/bolt housings complete the silhouette.
    for index in range(7):
        x_value = -4.5 + index * 1.5
        add(box(f"ammo_feed_link_{index + 1}", "pitch_cradle", (x_value, 45.5, -7.4),
                (1.0, 3.0, 1.4), "individual exposed ammunition feed link", "steel",
                rotation=(0, 0, -8)),
            "cradle_crossbeam", (x_value, 46.6, -6.8))
    for side, z_value in (("front", 7.4), ("back", -7.4)):
        for index, x_value in enumerate((7.0, 13.0, 19.0), start=1):
            add(box(f"cannon_{side}_panel_bolt_{index}", "cannon", (x_value, 56, z_value),
                    (1.0, 1.0, 1.0), "raised cannon service-panel bolt", "steel"),
                f"cannon_side_panel_{side}",
                (x_value, 56, z_value - (0.3 if z_value > 0 else -0.3)))

    landmarks: list[dict[str, Any]] = []

    def mark(
        name: str,
        cube: str,
        face: str,
        center_uv: tuple[float, float],
        size: tuple[int, int],
        color: str,
        center_color: str,
    ) -> None:
        landmarks.append(
            {
                "name": name,
                "cube": cube,
                "face": face,
                "center_uv": list(center_uv),
                "size": list(size),
                "color": color,
                "center_color": center_color,
            }
        )

    for side, cube_name, face in (
        ("front", "pedestal_mid_front_panel", "south"),
        ("back", "pedestal_mid_back_panel", "north"),
        ("left", "pedestal_mid_left_panel", "west"),
        ("right", "pedestal_mid_right_panel", "east"),
    ):
        mark(f"{side}_pedestal_label", cube_name, face, (0.5, 0.38), (7, 2), "#737b79", "#f5f7f3")
        for bolt_index, horizontal in enumerate((0.18, 0.82), start=1):
            mark(f"{side}_pedestal_bolt_{bolt_index}", cube_name, face,
                 (horizontal, 0.78), (1, 1), "#495156", "#d5dad8")
    for side, cube_name, face in (
        ("front", "cannon_side_panel_front", "south"),
        ("back", "cannon_side_panel_back", "north"),
    ):
        mark(f"{side}_cannon_seam", cube_name, face, (0.5, 0.62), (10, 1), "#171b1f", "#65717a")
        mark(f"{side}_cannon_warning", cube_name, face, (0.28, 0.28), (5, 2), "#654a08", "#f6dd67")
        mark(f"{side}_cannon_label", cube_name, face, (0.68, 0.28), (7, 2), "#737b79", "#f5f7f3")
    for side, cube_name, face in (
        ("front", "launcher_front_panel", "south"),
        ("back", "launcher_back_panel", "north"),
    ):
        for row in range(2):
            for column in range(3):
                mark(f"{side}_launcher_cell_{row + 1}_{column + 1}", cube_name, face,
                     (0.32 + 0.18 * column, 0.35 + 0.28 * row), (2, 2),
                     "#0b1519", "#6d8f95")
    mark("top_sensor_crosshair", "launcher_top_sensor", "up", (0.5, 0.5), (4, 4),
         "#0b1519", "#d4a723")
    mark("muzzle_warning_band", "cannon_muzzle_brake", "up", (0.5, 0.5), (6, 2),
         "#654a08", "#f6dd67")

    # The portrait view establishes a tall central column. Lift the complete
    # yaw/pitch assembly rigidly and lengthen only the axis-aligned pedestal
    # shell, preserving every authored segment rotation and piston thickness.
    lifted_bones = {"yaw_ring", "pitch_cradle", "cannon", "launcher", "sensors"}
    for bone in builder.bones:
        if bone["name"] in lifted_bones:
            bone["pivot"][1] = round(float(bone["pivot"][1]) + UPPER_LIFT, 6)
    lifted_cubes = {
        cube["name"] for cube in builder.cubes if cube["bone"] in lifted_bones
    }
    lifted_cubes.add("pedestal_upper_cap")
    for cube in builder.cubes:
        if cube["name"] in lifted_cubes:
            cube["center"][1] = round(float(cube["center"][1]) + UPPER_LIFT, 6)
            cube["origin"][1] = round(float(cube["origin"][1]) + UPPER_LIFT, 6)
        if cube["name"] == "pedestal_mid_core":
            cube["center"][1] = 33.0
            cube["size"][1] = 36.0
        elif cube["name"].startswith("pedestal_mid_"):
            cube["center"][1] = 33.0
            cube["size"][1] = 31.0
    shifted_links = []
    for first, second, joint in attachments:
        shift = UPPER_LIFT if second in lifted_cubes else 0.0
        shifted_links.append((first, second, (joint[0], joint[1] + shift, joint[2])))
    attachments = shifted_links

    names = [cube["name"] for cube in builder.cubes]
    inventory = {
        "pedestal_cuboids": sum(name.startswith(("pedestal_", "yaw_ring_")) for name in names),
        "outrigger_assemblies": len(outrigger_records),
        "outrigger_cuboids": sum(name.startswith("support_") for name in names),
        "grounded_feet": sum(name.endswith("_ground_foot") for name in names),
        "vertical_outer_pistons": sum(name.endswith("_outer_piston_rod") for name in names),
        "pitch_drive_drum_cuboids": sum("drive_drum" in name for name in names),
        "cannon_cuboids": sum(name.startswith("cannon_") for name in names),
        "launcher_cuboids": sum(name.startswith("launcher_") for name in names),
        "cable_cuboids": sum("cable_" in name for name in names),
        "ammo_feed_links": sum(name.startswith("ammo_feed_link_") for name in names),
        "texture_landmarks": len(landmarks),
    }

    reference_views = [
        {
            "image": str(path.resolve()),
            "sha256": digest,
            "width": 1000,
            "height": 1000,
            "camera": "uncalibrated elevated perspective",
        }
        for path, digest in REFERENCES
    ]
    spec = {
        "schema_version": 1,
        "id": "aegis_x2_turret",
        "reference": {
            "image": str(REFERENCES[0][0].resolve()),
            "sha256": REFERENCES[0][1],
            "width": 1000,
            "height": 1000,
        },
        "subject": {
            "type": "prop",
            "description": "Aegis X2 autonomous hard-surface turret on four piston outriggers",
            "symmetry": "asymmetric",
            "uncertainties": [
                "The three supplied views are uncalibrated perspective renders "
                "rather than camera metadata.",
                "Several cable routes and the pedestal underside are occluded "
                "and inferred conservatively.",
                "The exact profile of round housings is translated into "
                "Minecraft-native stepped cuboids.",
                "The three images do not establish hidden interior geometry or a visual hull.",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [120, 180],
            "identity_features": [
                "tall segmented pedestal with a distinct yaw bearing",
                "four radial grounded outriggers with vertical pistons and broad feet",
                "pitch cradle with paired segmented drive drums",
                "long +X cannon with exposed barrel and muzzle brake",
                "opposed bulky -X launcher and angular service grip",
                "copper and red cable bundles plus textured seams bolts warnings and labels",
            ],
            "required_views": [
                "front", "back", "left", "right", "top", "isometric",
                "source-3-perspective", "source-4-perspective", "source-5-perspective",
                "cannon-closeup", "launcher-closeup", "outrigger-closeup", "cradle-closeup",
            ],
            "review_targets": [
                "three source silhouettes", "opposed weapon axes", "pedestal segmentation",
                "four support contacts", "yaw and pitch pivots", "part-local depth",
                "attachment continuity", "texture identity details",
            ],
        },
        "geometry": {"precision": 32},
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
        "collision": {"width": 4.5, "height": 5.8, "eye_height": 4.7},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "multi-view-aegis-hard-surface-semantic-cuboids-v1",
            "source_mesh": None,
            "source_skin_cuboids": 0,
            "source_projection": False,
            "authored_texture_sources": [],
            "anatomical_axis": "+X cannon, -X launcher, Y up, Z drum/pitch axis",
            "reference_views": reference_views,
            "camera_parameters_are_estimated": True,
            "visual_hull_used": False,
            "hidden_geometry_established": False,
            "single_view_hidden_geometry": (
                "Cable routing, undersides, internal weapon mechanisms, and concealed support "
                "faces are conservative hard-surface inferences from three uncalibrated views."
            ),
            "yaw_axis": {"bone": "yaw_ring", "pivot": [0, 55, 0], "axis": "+Y"},
            "pitch_axis": {"bone": "pitch_cradle", "pivot": [0, 70, 0], "axis": "+Z"},
            "weapon_axes": {
                "cannon": {"bone": "cannon", "direction": [1, 0, 0]},
                "launcher": {"bone": "launcher", "direction": [-1, 0, 0]},
            },
            "outriggers": outrigger_records,
            "cable_cuboids": cable_records,
            "feature_inventory": inventory,
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
