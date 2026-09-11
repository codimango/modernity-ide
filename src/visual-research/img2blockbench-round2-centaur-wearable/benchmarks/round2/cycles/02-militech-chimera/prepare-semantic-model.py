#!/usr/bin/env python3
"""Author the Round 2 Militech Chimera as a native semantic volume."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image

from semantic_geometry import (
    SemanticModelBuilder,
    segment_cube,
    transform_radial_profile,
)


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "image.png"
ALT_REFERENCE = ROOT / "benchmarks" / "round2" / "references" / "chimera-alt.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "55ed303da9e7484812f0827922fceb0b07a8bac68ccc1a9c03e39702419eada2"
EXPECTED_ALT_SHA256 = "28ecd39372be2f3df0a5be657392b31557f8a91fb90136a78722878548bf46f7"


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "solid",
    scale: int = 1,
) -> dict[str, Any]:
    """Create one deterministic Minecraft-native material."""
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


def offset(
    point: tuple[float, float, float],
    direction: tuple[float, float, float],
    distance: float,
) -> tuple[float, float, float]:
    """Offset a point along a unit direction."""
    return tuple(point[index] + direction[index] * distance for index in range(3))


def main() -> None:
    """Write a deep armored hexapod with six independently rigged legs."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Militech Chimera reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (600, 900):
            raise ValueError(f"unexpected Militech Chimera size: {opened.size}")
    if hashlib.sha256(ALT_REFERENCE.read_bytes()).hexdigest() != EXPECTED_ALT_SHA256:
        raise ValueError("unexpected alternate Militech Chimera reference hash")
    with Image.open(ALT_REFERENCE) as opened:
        if opened.size != (736, 414):
            raise ValueError(f"unexpected alternate Chimera size: {opened.size}")

    materials = {
        "armor": material("#62694d", "#30382e", "#929579", "solid", 1),
        "armor_light": material("#85866a", "#505440", "#b8b897", "solid", 1),
        "armor_dark": material("#3a4437", "#1b241e", "#66705b", "solid", 1),
        "edge": material("#252e2b", "#101615", "#515b55", "solid", 1),
        "joint": material("#293437", "#11191b", "#657176", "solid", 1),
        "steel": material("#697478", "#30383b", "#adb7b7", "stripes", 3),
        "pale_panel": material("#bbc5ac", "#727c6c", "#e1e6cf", "solid", 1),
        "glass": material("#263d43", "#101c20", "#6e8587", "gradient", 4),
        "sensor": material("#23596b", "#0b2530", "#69a9bb", "gradient", 2),
        "amber": material("#d58b1c", "#6f3f08", "#ffd45c", "solid", 1),
        "label": material("#d8dfd1", "#7f8a7d", "#f7faef", "solid", 1),
        "rubber": material("#262a27", "#0f1210", "#505651", "solid", 1),
    }

    builder = SemanticModelBuilder()
    for name, parent, pivot in (
        ("chassis", "root", (0.0, 11.8, 0.0)),
        ("hull", "chassis", (0.0, 13.5, 0.5)),
        ("nose", "hull", (0.0, 12.8, 12.0)),
        ("turret_ring", "hull", (0.0, 17.0, -1.8)),
        ("turret", "turret_ring", (0.0, 18.2, -1.2)),
        ("roof", "turret", (0.0, 23.1, -2.0)),
        ("radar", "roof", (0.0, 24.2, -3.0)),
        ("sensors", "nose", (0.0, 12.0, 18.0)),
    ):
        builder.add_bone(name, parent, pivot)

    attachments: list[tuple[str, str, tuple[float, float, float]]] = []

    # A low continuous hull supports the ring and all six shoulder stations.
    body_cubes = (
        box("belly_core", "chassis", (0, 10.8, 0), (15.0, 4.4, 23.0),
            "deep protected central belly", "edge"),
        box("lower_hull", "hull", (0, 13.1, 0.5), (18.0, 4.5, 24.0),
            "low wide load-bearing hull", "armor_dark"),
        box("center_deck", "hull", (0, 15.4, -0.4), (17.0, 2.8, 20.5),
            "layered central deck below the turret ring", "armor"),
        box("front_deck", "nose", (0, 14.2, 11.0), (15.0, 3.4, 8.5),
            "sloping forward deck", "armor_light", rotation=(9, 0, 0)),
        box("prow_mid", "nose", (0, 12.7, 15.1), (12.8, 3.5, 6.2),
            "faceted middle prow", "armor", rotation=(13, 0, 0)),
        box("prow_tip", "nose", (0, 11.5, 18.6), (9.8, 2.6, 3.2),
            "low blunt sensor nose", "armor_light", rotation=(12, 0, 0)),
        box("lower_glacis", "nose", (0, 10.5, 15.8), (10.8, 1.8, 6.2),
            "recessed lower nose armor", "armor_dark", rotation=(8, 0, 0)),
        box("rear_hull", "hull", (0, 13.4, -11.3), (15.4, 4.0, 4.4),
            "rear armored engine block", "armor_dark", rotation=(-5, 0, 0)),
        box("rear_engine_cap", "hull", (0, 14.1, -13.0), (11.8, 2.8, 2.0),
            "stepped rear engine armor", "armor", rotation=(-7, 0, 0)),
        box("left_side_rail", "hull", (-8.8, 12.8, 0.0), (2.4, 4.4, 21.5),
            "left full-depth structural rail", "edge"),
        box("right_side_rail", "hull", (8.8, 12.8, 0.0), (2.4, 4.4, 21.5),
            "right full-depth structural rail", "edge"),
        box("left_front_cheek", "nose", (-6.2, 13.9, 13.0), (3.8, 4.0, 7.6),
            "left faceted prow cheek", "armor", rotation=(9, 9, -5)),
        box("right_front_cheek", "nose", (6.2, 13.9, 13.0), (3.8, 4.0, 7.6),
            "right faceted prow cheek", "armor", rotation=(9, -9, 5)),
        box("left_mid_cheek", "hull", (-8.4, 14.0, 0.0), (3.2, 4.8, 8.0),
            "left layered middle shoulder armor", "armor", rotation=(0, 0, -5)),
        box("right_mid_cheek", "hull", (8.4, 14.0, 0.0), (3.2, 4.8, 8.0),
            "right layered middle shoulder armor", "armor", rotation=(0, 0, 5)),
        box("left_rear_cheek", "hull", (-7.0, 14.5, -8.8), (3.6, 4.2, 7.0),
            "left rear shoulder armor", "armor", rotation=(-4, 7, -5)),
        box("right_rear_cheek", "hull", (7.0, 14.5, -8.8), (3.6, 4.2, 7.0),
            "right rear shoulder armor", "armor", rotation=(-4, -7, 5)),
        box("left_belly_skid", "chassis", (-5.0, 8.8, 0.0), (3.0, 1.0, 17.0),
            "left armored underside runner", "steel"),
        box("right_belly_skid", "chassis", (5.0, 8.8, 0.0), (3.0, 1.0, 17.0),
            "right armored underside runner", "steel"),
        box("left_lower_side_skirt", "chassis", (-8.0, 9.8, 0.0), (1.8, 3.2, 17.0),
            "left low armored chassis skirt", "armor_dark", rotation=(0, 0, -5)),
        box("right_lower_side_skirt", "chassis", (8.0, 9.8, 0.0), (1.8, 3.2, 17.0),
            "right low armored chassis skirt", "armor_dark", rotation=(0, 0, 5)),
        box("belly_front_plate", "chassis", (0, 9.4, 9.8), (10.0, 1.2, 3.8),
            "forward underside armor plate", "armor_dark", rotation=(8, 0, 0)),
        box("belly_rear_plate", "chassis", (0, 9.4, -9.5), (10.0, 1.2, 3.8),
            "rear underside armor plate", "armor_dark", rotation=(-8, 0, 0)),
        box("front_sensor_bar", "sensors", (0, 11.1, 20.0), (8.8, 1.3, 0.7),
            "wide blue forward sensor bank", "edge"),
        box("nose_hatch", "nose", (0, 15.3, 13.5), (4.6, 0.65, 3.4),
            "raised rectangular prow service hatch", "armor_light", rotation=(10, 0, 0)),
        box("left_front_fender", "nose", (-7.5, 12.8, 14.2), (1.1, 2.8, 6.0),
            "left forward edge armor", "edge", rotation=(8, 8, -4)),
        box("right_front_fender", "nose", (7.5, 12.8, 14.2), (1.1, 2.8, 6.0),
            "right forward edge armor", "edge", rotation=(8, -8, 4)),
    )
    for cube in body_cubes:
        builder.add_cube(cube)

    attachments.extend(
        [
            ("belly_core", "lower_hull", (0, 12.8, 0)),
            ("lower_hull", "center_deck", (0, 14.8, 0)),
            ("lower_hull", "front_deck", (0, 13.7, 8.8)),
            ("front_deck", "prow_mid", (0, 13.4, 13.0)),
            ("prow_mid", "prow_tip", (0, 12.45, 17.7)),
            ("prow_mid", "lower_glacis", (0, 11.2, 15.5)),
            ("lower_hull", "rear_hull", (0, 13.3, -10.0)),
            ("rear_hull", "rear_engine_cap", (0, 13.8, -12.0)),
            ("lower_hull", "left_side_rail", (-8.0, 12.8, 0)),
            ("lower_hull", "right_side_rail", (8.0, 12.8, 0)),
            ("front_deck", "left_front_cheek", (-5.5, 14.0, 12.0)),
            ("front_deck", "right_front_cheek", (5.5, 14.0, 12.0)),
            ("lower_hull", "left_mid_cheek", (-8.2, 13.5, 0)),
            ("lower_hull", "right_mid_cheek", (8.2, 13.5, 0)),
            ("rear_hull", "left_rear_cheek", (-6.0, 14.0, -9.5)),
            ("rear_hull", "right_rear_cheek", (6.0, 14.0, -9.5)),
            ("belly_core", "left_belly_skid", (-5.0, 8.95, 0)),
            ("belly_core", "right_belly_skid", (5.0, 8.95, 0)),
            ("belly_core", "left_lower_side_skirt", (-7.2, 9.8, 0)),
            ("belly_core", "right_lower_side_skirt", (7.2, 9.8, 0)),
            ("belly_core", "belly_front_plate", (0, 9.8, 9.0)),
            ("belly_core", "belly_rear_plate", (0, 9.8, -9.0)),
            ("prow_tip", "front_sensor_bar", (0, 11.45, 19.9)),
            ("front_deck", "nose_hatch", (0, 15.0, 14.85)),
            ("left_front_cheek", "left_front_fender", (-7.1, 13.3, 14.0)),
            ("right_front_cheek", "right_front_fender", (7.1, 13.3, 14.0)),
        ]
    )

    # The upper assembly is a closed rotating turret with layered wedge armor.
    turret_cubes = (
        box("turret_base", "turret", (0, 18.0, -1.5), (18.0, 2.6, 16.0),
            "deep rotating turret foundation", "edge"),
        box("cabin_core", "turret", (0, 20.4, -2.0), (16.0, 4.8, 15.0),
            "large closed armored turret core", "armor"),
        box("cabin_front_slope", "turret", (0, 19.9, 5.8), (14.8, 4.0, 1.8),
            "broad sloped wedge glacis", "pale_panel", rotation=(18, 0, 0)),
        box("turret_front_upper", "turret", (0, 21.6, 4.8), (14.0, 1.8, 3.2),
            "upper layer of the wedge front", "armor_light", rotation=(10, 0, 0)),
        box("turret_front_lower", "turret", (0, 18.5, 6.2), (13.0, 1.6, 2.5),
            "dark lower lip of the wedge front", "edge", rotation=(12, 0, 0)),
        box("cabin_left_wall", "turret", (-8.1, 20.3, -1.8), (1.2, 4.5, 13.5),
            "left faceted turret side", "armor_dark", rotation=(0, 0, -5)),
        box("cabin_right_wall", "turret", (8.1, 20.3, -1.8), (1.2, 4.5, 13.5),
            "right faceted turret side", "armor_dark", rotation=(0, 0, 5)),
        box("left_window", "turret", (-3.8, 20.8, 6.5), (5.4, 2.0, 0.55),
            "left forward observation panel", "glass", rotation=(18, 0, 0)),
        box("right_window", "turret", (3.8, 20.8, 6.5), (5.4, 2.0, 0.55),
            "right forward observation panel", "glass", rotation=(18, 0, 0)),
        box("cabin_rear", "turret", (0, 20.3, -9.6), (14.0, 4.0, 1.4),
            "conservative rear turret armor", "armor_dark", rotation=(-4, 0, 0)),
        box("left_upper_facet", "turret", (-7.1, 22.0, -2.0), (3.0, 1.8, 11.0),
            "left sloped upper turret facet", "armor_light", rotation=(0, 0, -12)),
        box("right_upper_facet", "turret", (7.1, 22.0, -2.0), (3.0, 1.8, 11.0),
            "right sloped upper turret facet", "armor_light", rotation=(0, 0, 12)),
        box("roof_plate", "roof", (0, 23.0, -2.2), (14.0, 0.9, 11.5),
            "wide armored turret roof", "armor_light"),
        box("roof_front_brow", "roof", (0, 22.8, 3.7), (13.2, 1.1, 2.0),
            "thick forward roof brow", "armor"),
        box("roof_rear_step", "roof", (0, 22.9, -8.2), (12.0, 1.1, 1.8),
            "rear roof step", "armor_dark"),
        box("roof_hatch_long", "roof", (0, 23.48, -1.8), (4.8, 0.5, 2.0),
            "cross-shaped roof access hatch", "edge"),
        box("roof_hatch_cross", "roof", (0, 23.49, -1.8), (2.0, 0.52, 4.8),
            "cross-shaped roof access hatch", "edge"),
        box("left_side_panel", "turret", (-8.45, 20.0, 0.0), (0.6, 3.0, 6.2),
            "left pale side identification panel", "pale_panel", rotation=(0, 0, -6)),
        box("right_side_panel", "turret", (8.45, 20.0, 0.0), (0.6, 3.0, 6.2),
            "right pale side identification panel", "pale_panel", rotation=(0, 0, 6)),
        box("left_lower_skirt", "turret", (-6.8, 18.0, 3.4), (4.0, 2.0, 5.0),
            "left dark lower turret skirt", "edge", rotation=(0, 8, -5)),
        box("right_lower_skirt", "turret", (6.8, 18.0, 3.4), (4.0, 2.0, 5.0),
            "right dark lower turret skirt", "edge", rotation=(0, -8, 5)),
        box("left_rear_turret_facet", "turret", (-6.8, 20.2, -8.8), (3.6, 3.5, 2.2),
            "left rear turret corner facet", "armor", rotation=(-4, 10, -5)),
        box("right_rear_turret_facet", "turret", (6.8, 20.2, -8.8), (3.6, 3.5, 2.2),
            "right rear turret corner facet", "armor", rotation=(-4, -10, 5)),
        box("turret_left_front_wedge_cheek", "turret", (-6.4, 20.0, 5.6), (3.6, 3.4, 2.8),
            "left rotated front wedge cheek", "armor", rotation=(14, 12, -9)),
        box("turret_right_front_wedge_cheek", "turret", (6.4, 20.0, 5.6), (3.6, 3.4, 2.8),
            "right rotated front wedge cheek", "armor", rotation=(14, -12, 9)),
        box("turret_left_lower_bevel", "turret", (-8.2, 18.7, -1.5), (1.8, 2.2, 10.0),
            "left lower sloped turret shell", "armor_dark", rotation=(0, 0, -18)),
        box("turret_right_lower_bevel", "turret", (8.2, 18.7, -1.5), (1.8, 2.2, 10.0),
            "right lower sloped turret shell", "armor_dark", rotation=(0, 0, 18)),
        box("turret_left_rear_roof_bevel", "turret", (-5.7, 22.0, -8.2), (3.6, 1.8, 2.8),
            "left sloped rear roof corner", "armor_light", rotation=(-7, 12, -10)),
        box("turret_right_rear_roof_bevel", "turret", (5.7, 22.0, -8.2), (3.6, 1.8, 2.8),
            "right sloped rear roof corner", "armor_light", rotation=(-7, -12, 10)),
    )
    for cube in turret_cubes:
        builder.add_cube(cube)

    attachments.extend(
        [
            ("center_deck", "turret_base", (0, 16.7, -1.5)),
            ("turret_base", "cabin_core", (0, 19.0, -2.0)),
            ("cabin_core", "cabin_front_slope", (0, 20.0, 5.0)),
            ("cabin_front_slope", "turret_front_upper", (0, 21.05, 5.8)),
            ("cabin_front_slope", "turret_front_lower", (0, 18.8, 5.9)),
            ("cabin_core", "cabin_left_wall", (-7.6, 20.4, -2.5)),
            ("cabin_core", "cabin_right_wall", (7.6, 20.4, -2.5)),
            ("cabin_front_slope", "left_window", (-3.8, 20.8, 6.3)),
            ("cabin_front_slope", "right_window", (3.8, 20.8, 6.3)),
            ("cabin_core", "cabin_rear", (0, 20.0, -9.15)),
            ("cabin_core", "left_upper_facet", (-6.8, 21.7, -2.0)),
            ("cabin_core", "right_upper_facet", (6.8, 21.7, -2.0)),
            ("cabin_core", "roof_plate", (0, 22.7, -2.5)),
            ("roof_plate", "roof_front_brow", (0, 22.9, 3.0)),
            ("roof_plate", "roof_rear_step", (0, 23.0, -7.6)),
            ("roof_plate", "roof_hatch_long", (0, 23.3, -1.8)),
            ("roof_plate", "roof_hatch_cross", (0, 23.3, -1.8)),
            ("cabin_left_wall", "left_side_panel", (-8.3, 20.5, 0)),
            ("cabin_right_wall", "right_side_panel", (8.3, 20.5, 0)),
            ("turret_base", "left_lower_skirt", (-6.4, 18.0, 3.2)),
            ("turret_base", "right_lower_skirt", (6.4, 18.0, 3.2)),
            ("cabin_rear", "left_rear_turret_facet", (-6.2, 20.2, -9.4)),
            ("cabin_rear", "right_rear_turret_facet", (6.2, 20.2, -9.4)),
            ("cabin_front_slope", "turret_left_front_wedge_cheek", (-6.0, 20.0, 5.8)),
            ("cabin_front_slope", "turret_right_front_wedge_cheek", (6.0, 20.0, 5.8)),
            ("turret_base", "turret_left_lower_bevel", (-8.0, 18.4, -1.5)),
            ("turret_base", "turret_right_lower_bevel", (8.0, 18.4, -1.5)),
            ("cabin_rear", "turret_left_rear_roof_bevel", (-4.6, 21.85, -9.4)),
            ("cabin_rear", "turret_right_rear_roof_bevel", (4.6, 21.85, -9.4)),
        ]
    )

    # Twelve tangent blocks form a visibly circular rotating collar.
    collar_names = []
    collar_center = (0.0, 16.8, -1.8)
    for index in range(12):
        angle = index * 30.0
        radians = math.radians(angle)
        center = (
            collar_center[0] + math.cos(radians) * 7.0,
            collar_center[1],
            collar_center[2] + math.sin(radians) * 7.0,
        )
        name = f"turret_collar_{index + 1:02d}"
        builder.add_cube(
            box(
                name,
                "turret_ring",
                center,
                (4.0, 1.4, 1.5),
                "segmented circular turret rotation collar",
                "steel",
                rotation=(0, -angle, 0),
            )
        )
        attachments.append(("turret_base", name, center))
        collar_names.append(name)

    radar_cubes = (
        box("radar_pedestal", "radar", (0, 23.9, -3.0), (3.8, 1.2, 3.8),
            "radar pod circular-equivalent pedestal", "joint"),
        box("radar_neck", "radar", (0, 24.6, -3.0), (1.8, 1.3, 1.8),
            "radar pod rotating neck", "steel"),
        box("radar_pod_core", "radar", (0, 25.7, -2.6), (11.5, 1.6, 5.4),
            "large roof sensor and radar pod", "armor_light", rotation=(2, 0, 0)),
        box("radar_pod_front", "radar", (0, 25.6, 0.2), (10.0, 1.2, 1.0),
            "sloped radar pod sensor face", "glass", rotation=(10, 0, 0)),
        box("radar_pod_left", "radar", (-5.8, 25.7, -2.6), (0.8, 1.4, 4.4),
            "left radar pod edge armor", "edge", rotation=(0, 0, -8)),
        box("radar_pod_right", "radar", (5.8, 25.7, -2.6), (0.8, 1.4, 4.4),
            "right radar pod edge armor", "edge", rotation=(0, 0, 8)),
        box("radar_pod_top", "radar", (0, 26.6, -2.7), (10.8, 0.4, 4.8),
            "radar pod top plate", "pale_panel"),
    )
    for cube in radar_cubes:
        builder.add_cube(cube)
    attachments.extend(
        [
            ("roof_plate", "radar_pedestal", (0, 23.4, -3.0)),
            ("radar_pedestal", "radar_neck", (0, 24.2, -3.0)),
            ("radar_neck", "radar_pod_core", (0, 25.0, -3.0)),
            ("radar_pod_core", "radar_pod_front", (0, 25.6, -0.05)),
            ("radar_pod_core", "radar_pod_left", (-5.5, 26.0, -2.6)),
            ("radar_pod_core", "radar_pod_right", (5.5, 26.0, -2.6)),
            ("radar_pod_core", "radar_pod_top", (0, 26.45, -2.7)),
        ]
    )

    antennae = (
        ("antenna_left", (-4.2, 23.3, -6.2), (-4.2, 26.2, -6.2)),
        ("antenna_center", (-2.5, 23.3, -6.7), (-2.5, 25.9, -6.7)),
        ("antenna_right", (4.5, 23.3, -6.4), (4.5, 26.0, -6.4)),
    )
    for name, start, end in antennae:
        builder.add_bone(name, "roof", start)
        builder.add_cube(
            segment_cube(
                name,
                name,
                start,
                end,
                (0.45, 0.45),
                "upright roof communications aerial",
                "steel",
                overlap=0.15,
            )
        )
        attachments.append(("roof_plate", name, start))

    # Three paired stations form the Chimera's six-legged stance. Each leg has
    # a four-link load path plus a broad shield over the long lower actuator.
    leg_records: list[dict[str, Any]] = []
    quadrant_data = (
        ("front_right", 42.0, "front"),
        ("front_left", 138.0, "front"),
        ("middle_right", 0.0, "middle"),
        ("middle_left", 180.0, "middle"),
        ("rear_left", 222.0, "rear"),
        ("rear_right", 318.0, "rear"),
    )
    for leg_name, azimuth, station in quadrant_data:
        joints = transform_radial_profile(
            (0.0, 0.0, 0.0),
            azimuth,
            (
                (0.0, 11.8, 9.5),
                (0.0, 10.8, 13.8),
                (0.0, 8.2, 17.2),
                (0.0, 4.1, 20.2),
                (0.0, 1.6, 22.0),
            ),
        )
        chain = builder.add_chain(
            f"{leg_name}_leg",
            "chassis",
            joints,
            (3.8, 3.5, 4.0, 2.8),
            ("armor_dark", "joint", "armor", "steel"),
            f"{leg_name.replace('_', ' ')} articulated load-bearing leg",
            overlap=0.55,
            depths=(4.5, 3.8, 4.2, 3.0),
        )
        root = joints[0]
        hip_name = f"{leg_name}_hip_housing"
        builder.add_cube(
            box(
                hip_name,
                "chassis",
                root,
                (5.4, 4.6, 5.4),
                f"{leg_name.replace('_', ' ')} square armored hip",
                "armor_dark",
                rotation=(0, -azimuth, 0),
            )
        )
        hip_parent = (
            ("right_side_rail" if "right" in leg_name else "left_side_rail")
            if station == "middle"
            else "lower_hull"
        )
        attachments.append((hip_parent, hip_name, root))
        attachments.append((hip_name, chain.cubes[0], root))
        attachments.extend(chain.attachments)

        for index, joint in enumerate(joints[1:4], start=1):
            hinge_name = f"{leg_name}_hinge_{index}"
            hinge_size = (4.4, 4.4, 4.4) if index < 3 else (3.7, 3.7, 3.7)
            builder.add_cube(
                box(
                    hinge_name,
                    chain.bones[index - 1],
                    joint,
                    hinge_size,
                    f"{leg_name.replace('_', ' ')} visible pivot hinge {index}",
                    "joint",
                )
            )
            attachments.append((chain.cubes[index - 1], hinge_name, joint))
            attachments.append((hinge_name, chain.cubes[index], joint))

        shield_name = f"{leg_name}_shin_shield"
        shield_delta = tuple(joints[3][axis] - joints[2][axis] for axis in range(3))
        shield_length = math.sqrt(sum(value * value for value in shield_delta))
        shield_direction = tuple(value / shield_length for value in shield_delta)
        shield_start = tuple(
            joints[2][axis] - shield_direction[axis] for axis in range(3)
        )
        shield_end = tuple(
            joints[3][axis] + shield_direction[axis] for axis in range(3)
        )
        shield = segment_cube(
            shield_name,
            chain.bones[2],
            shield_start,
            shield_end,
            (5.8, 2.6),
            f"{leg_name.replace('_', ' ')} large rectangular shin shield",
            "armor_light",
            overlap=0.25,
        )
        builder.add_cube(shield)
        shield_joint = tuple(
            (shield_start[axis] + shield_end[axis]) / 2 for axis in range(3)
        )
        attachments.append((chain.cubes[2], shield_name, shield_joint))
        shield_plate_names = []
        for plate_name, first_amount, second_amount in (
            ("upper", 0.08, 0.32),
            ("lower", 0.68, 0.92),
        ):
            plate_start = tuple(
                shield_start[axis]
                + (shield_end[axis] - shield_start[axis]) * first_amount
                for axis in range(3)
            )
            plate_end = tuple(
                shield_start[axis]
                + (shield_end[axis] - shield_start[axis]) * second_amount
                for axis in range(3)
            )
            plate_cube_name = f"{leg_name}_shin_{plate_name}_plate"
            builder.add_cube(
                segment_cube(
                    plate_cube_name,
                    chain.bones[2],
                    plate_start,
                    plate_end,
                    (6.5, 3.0),
                    f"{leg_name.replace('_', ' ')} raised {plate_name} shin plate",
                    "armor",
                    overlap=0.12,
                )
            )
            plate_joint = tuple(
                (plate_start[axis] + plate_end[axis]) / 2 for axis in range(3)
            )
            attachments.append((shield_name, plate_cube_name, plate_joint))
            shield_plate_names.append(plate_cube_name)

        angle = math.radians(azimuth)
        radial = (math.cos(angle), 0.0, math.sin(angle))
        tangent = (-math.sin(angle), 0.0, math.cos(angle))
        endpoint = joints[-1]
        foot_name = f"{leg_name}_foot_pad"
        foot_center = (endpoint[0], 0.9, endpoint[2])
        builder.add_cube(
            box(
                foot_name,
                chain.bones[-1],
                foot_center,
                (6.2, 1.8, 5.6),
                f"{leg_name.replace('_', ' ')} large rectangular grounded foot",
                "rubber",
                rotation=(0, -azimuth, 0),
            )
        )
        attachments.append((chain.cubes[-1], foot_name, endpoint))

        foot_armor_name = f"{leg_name}_foot_armor"
        foot_armor_center = (endpoint[0], 2.0, endpoint[2])
        builder.add_cube(
            box(
                foot_armor_name,
                chain.bones[-1],
                foot_armor_center,
                (5.6, 2.4, 4.4),
                f"{leg_name.replace('_', ' ')} armored ankle and foot shield",
                "armor_dark",
                rotation=(0, -azimuth, 0),
            )
        )
        attachments.append((foot_name, foot_armor_name, (endpoint[0], 1.3, endpoint[2])))

        toe_names = []
        for toe_index, tangent_offset in enumerate((-1.35, 0.0, 1.35), start=1):
            start = (
                endpoint[0] + tangent[0] * tangent_offset,
                0.72,
                endpoint[2] + tangent[2] * tangent_offset,
            )
            end = offset(start, radial, 2.8)
            toe_name = f"{leg_name}_toe_{toe_index}"
            builder.add_cube(
                segment_cube(
                    toe_name,
                    chain.bones[-1],
                    start,
                    end,
                    (0.8, 0.8),
                    f"{leg_name.replace('_', ' ')} grounded gripping toe",
                    "steel",
                    overlap=0.2,
                    longitudinal_axis="z",
                )
            )
            attachments.append((foot_name, toe_name, start))
            toe_names.append(toe_name)

        leg_records.append(
            {
                "name": leg_name,
                "station": station,
                "azimuth_degrees": azimuth,
                "root": list(root),
                "joints": [list(point) for point in joints],
                "segments": list(chain.cubes),
                "hinges": [f"{leg_name}_hinge_{index}" for index in range(1, 4)],
                "shin_shield": shield_name,
                "shin_plates": shield_plate_names,
                "foot": foot_name,
                "foot_armor": foot_armor_name,
                "toes": toe_names,
            }
        )

    names = [cube["name"] for cube in builder.cubes]
    body_names = {
        "belly_core", "lower_hull", "center_deck", "front_deck", "prow_mid",
        "prow_tip", "lower_glacis", "rear_hull", "rear_engine_cap",
        "left_side_rail", "right_side_rail", "left_mid_cheek", "right_mid_cheek",
        "left_belly_skid", "right_belly_skid", "belly_front_plate",
        "belly_rear_plate", "left_lower_side_skirt", "right_lower_side_skirt",
        "left_front_fender", "right_front_fender",
        "left_front_cheek", "right_front_cheek", "left_rear_cheek",
        "right_rear_cheek", "front_sensor_bar", "nose_hatch",
    }
    turret_names = {
        name
        for name in names
        if name.startswith(("turret_", "cabin_", "roof_", "radar_"))
    }
    landmarks: list[dict[str, Any]] = []
    for side, cube_name, face in (
        ("left", "cabin_left_wall", "west"),
        ("right", "cabin_right_wall", "east"),
    ):
        for row, vertical in enumerate((0.38, 0.55), start=1):
            for column, horizontal in enumerate((0.33, 0.5, 0.67), start=1):
                landmarks.append(
                    {
                        "name": f"{side}_amber_{row}_{column}",
                        "cube": cube_name,
                        "face": face,
                        "center_uv": [horizontal, vertical],
                        "size": [2, 2],
                        "color": "#7a4308",
                        "center_color": "#ffd45c",
                    }
                )
        landmarks.append(
            {
                "name": f"{side}_militech_bar",
                "cube": cube_name,
                "face": face,
                "center_uv": [0.5, 0.18],
                "size": [7, 1],
                "color": "#d8dfd1",
                "center_color": "#f7faef",
            }
        )
    for index, horizontal in enumerate((0.25, 0.5, 0.75), start=1):
        landmarks.append(
            {
                "name": f"front_sensor_{index}",
                "cube": "front_sensor_bar",
                "face": "south",
                "center_uv": [horizontal, 0.5],
                "size": [2, 1],
                "color": "#0b2530",
                "center_color": "#69a9bb",
            }
        )
    for record in leg_records:
        for index, (horizontal, vertical) in enumerate(
            ((0.18, 0.2), (0.82, 0.2), (0.18, 0.8), (0.82, 0.8)),
            start=1,
        ):
            landmarks.append(
                {
                    "name": f"{record['name']}_shield_bolt_{index}",
                    "cube": record["shin_shield"],
                    "face": "south",
                    "center_uv": [horizontal, vertical],
                    "size": [1, 1],
                    "color": "#252e2b",
                    "center_color": "#adb7b7",
                }
            )
        landmarks.append(
            {
                "name": f"{record['name']}_shield_seam",
                "cube": record["shin_shield"],
                "face": "south",
                "center_uv": [0.5, 0.5],
                "size": [1, 5],
                "color": "#30383b",
                "center_color": "#697478",
            }
        )
    for index, horizontal in enumerate((0.3, 0.5, 0.7), start=1):
        landmarks.append(
            {
                "name": f"radar_status_light_{index}",
                "cube": "radar_pod_front",
                "face": "south",
                "center_uv": [horizontal, 0.5],
                "size": [1, 1],
                "color": "#0b2530",
                "center_color": "#69a9bb",
            }
        )
    landmarks.extend(
        [
            {
                "name": "roof_hatch_mark",
                "cube": "roof_hatch_long",
                "face": "up",
                "center_uv": [0.5, 0.5],
                "size": [4, 2],
                "color": "#697478",
                "center_color": "#adb7b7",
            },
            {
                "name": "nose_warning_mark",
                "cube": "nose_hatch",
                "face": "up",
                "center_uv": [0.5, 0.5],
                "size": [3, 1],
                "color": "#d58b1c",
                "center_color": "#ffd45c",
            },
        ]
    )

    feature_inventory = {
        "body_volumes": len(body_names),
        "upper_turret_cuboids": len(turret_names),
        "mechanical_leg_chains": len(leg_records),
        "mechanical_leg_segments": sum(len(record["segments"]) for record in leg_records),
        "mechanical_hinges": sum(len(record["hinges"]) for record in leg_records),
        "hip_housings": sum(name.endswith("_hip_housing") for name in names),
        "shin_shields": sum(name.endswith("_shin_shield") for name in names),
        "shin_armor_layers": sum(
            name.endswith(("_shin_shield", "_shin_upper_plate", "_shin_lower_plate"))
            for name in names
        ),
        "grounded_feet": sum(name.endswith("_foot_pad") for name in names),
        "foot_armor_blocks": sum(name.endswith("_foot_armor") for name in names),
        "toe_claws": sum("_toe_" in name for name in names),
        "turret_collar_segments": len(collar_names),
        "radar_pod_cuboids": sum(name.startswith("radar_") for name in names),
        "roof_antennae": sum(name.startswith("antenna_") for name in names),
        "amber_status_lights": sum("_amber_" in mark["name"] for mark in landmarks),
        "front_optics": sum(mark["name"].startswith("front_sensor_") for mark in landmarks),
        "panel_bolts": sum("_bolt_" in mark["name"] for mark in landmarks),
        "panel_seams": sum("_seam" in mark["name"] for mark in landmarks),
    }

    spec = {
        "schema_version": 1,
        "id": "militech_chimera",
        "reference": {
            "image": str(REFERENCE.resolve()),
            "sha256": EXPECTED_SHA256,
            "width": 600,
            "height": 900,
        },
        "subject": {
            "type": "vehicle",
            "description": "Deep armored six-legged Militech Chimera combat machine",
            "symmetry": "bilateral",
            "uncertainties": [
                "The two still references occlude parts of the far-side leg joints.",
                "Exact underside equipment and rear-most armor remain partly unobserved.",
                "Hidden-side panel graphics mirror the visible side conservatively.",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [120, 180],
            "identity_features": [
                "deep low armored hull with a sloped sensor nose",
                "segmented circular collar and large faceted rotating upper turret",
                "six separately articulated legs at front, middle, and rear stations",
                "large rectangular shin shields, hinge blocks, armored feet, and triple toes",
                "roof radar pod, three aerials, blue optics, amber lights, seams, and bolts",
            ],
            "required_views": [
                "front", "back", "left", "right", "top", "isometric",
                "original-reference-perspective", "alternate-reference-perspective",
                "leg-closeup", "chassis-closeup", "turret-closeup",
            ],
            "review_targets": [
                "two source silhouettes", "true chassis depth", "six-leg station layout",
                "joint continuity", "six ground contacts", "faceted turret identity",
            ],
        },
        "geometry": {"precision": 32},
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
        "collision": {"width": 3.6, "height": 2.7, "eye_height": 2.25},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "deep-hard-surface-hexapod-semantic-cuboids-v2",
            "source_mesh": None,
            "source_skin_cuboids": 0,
            "source_projection": False,
            "authored_texture_sources": [],
            "finish_contract": {
                "name": "olive-khaki-military-camouflage",
                "canonical_reference": "image.png",
                "alternate_white_reference_is_geometry_only": True,
                "fallback_materials_use_camo_panel_tones": True,
            },
            "anatomical_axis": "+Z nose, X width, Y up",
            "single_view_hidden_geometry": (
                "Far-side articulation, underside equipment, and hidden panel graphics "
                "remain conservative symmetric inferences across two still photographs."
            ),
            "additional_references": [
                {
                    "image": "benchmarks/round2/references/chimera-alt.png",
                    "sha256": EXPECTED_ALT_SHA256,
                    "width": 736,
                    "height": 414,
                }
            ],
            "leg_chains": leg_records,
            "feature_inventory": feature_inventory,
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        },
    }
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
