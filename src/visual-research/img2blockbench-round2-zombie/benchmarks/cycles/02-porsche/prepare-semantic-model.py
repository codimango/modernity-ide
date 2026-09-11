#!/usr/bin/env python3
"""Author the Cycle 2 volumetric Porsche 911 Turbo (930) benchmark."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from semantic_geometry import SemanticModelBuilder


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "benchmarks" / "references" / "02-porsche-911.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "3b161a5f5e5c4a1ab3aa1034ceb5e6f0f727e51f6f7d0135ed4bae0e67c3f1d1"


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


def livery_texture() -> dict[str, Any]:
    """Return an authored silver/red/white 930 side graphic, never source pixels."""
    image = Image.new("RGBA", (32, 16), "#8f8d89")
    draw = ImageDraw.Draw(image)
    # One clean rearward diagonal: an ivory pinstripe followed by red. Keeping
    # the background flat avoids the noisy resampling seen in the first pass.
    draw.polygon(((8, 0), (16, 0), (10, 15), (4, 15)), fill="#ece8dc")
    draw.polygon(((13, 0), (30, 0), (24, 15), (7, 15)), fill="#bd302d")
    draw.rectangle((0, 14, 31, 15), fill="#252627")
    draw.line((10, 14, 19, 14), fill="#bd302d", width=1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return {
        "data_uri": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "repeat": [1, 1],
        "offset": [0, 0],
        "center": [0, 0],
        "rotation": 0,
        "wrap": [1001, 1001],
        "flip_y": True,
    }


def lamp_texture() -> dict[str, Any]:
    """Return a transparent pixel-octagon lens for an embedded round lamp."""
    image = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    outline = ((3, 0), (8, 0), (11, 3), (11, 8), (8, 11), (3, 11), (0, 8), (0, 3))
    inner = ((3, 1), (8, 1), (10, 3), (10, 8), (8, 10), (3, 10), (1, 8), (1, 3))
    draw.polygon(outline, fill="#75632f")
    draw.polygon(inner, fill="#d5bd6a")
    draw.rectangle((3, 2, 7, 4), fill="#f1dc87")
    draw.rectangle((4, 2, 6, 3), fill="#fff4b0")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return {
        "data_uri": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
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


def main() -> None:
    """Write a complete four-sided, four-wheel semantic 930 model."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Porsche reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (1859, 609):
            raise ValueError(f"unexpected Porsche reference size: {opened.size}")

    materials = {
        "silver": material("#969692", "#5f6260", "#d0cec6", "solid", 1),
        "silver_light": material("#aaa8a1", "#747572", "#dedbd2", "solid", 1),
        "silver_dark": material("#686a67", "#414442", "#999b96", "solid", 1),
        "dark_trim": material("#242628", "#101112", "#4c5051", "solid", 1),
        "rubber": material("#393a37", "#151615", "#5e5f59", "solid", 1),
        "sidewall": material("#44443f", "#1b1c1a", "#69685f", "solid", 1),
        "wheel_metal": material("#716952", "#3b372c", "#aaa087", "solid", 1),
        "hub_dark": material("#383832", "#151614", "#69675d", "solid", 1),
        "glass": material("#23343a", "#0d171c", "#64777a", "gradient", 3),
        "glass_glint": material("#496069", "#1a2a30", "#9aa9a7", "gradient", 3),
        "headlamp": {
            **material("#cdb56b", "#75632f", "#fff4b0", "solid", 1),
            "source_texture": lamp_texture(),
        },
        "lamp_glint": material("#eed47c", "#9b742b", "#fffbd0", "solid", 1),
        "tail_lamp": material("#a32627", "#4a1013", "#ed594d", "dither", 2),
        "amber": material("#c67d21", "#633b0f", "#f4bd48", "solid", 1),
        "chrome": material("#a9aaa4", "#555956", "#eef0e9", "gradient", 2),
        "plate": material("#d3d8cf", "#5b6f74", "#f7f6eb", "solid", 1),
        "red": material("#ae2f2b", "#5a1717", "#e3584e", "dither", 2),
        "side_livery": {
            **material("#92918d", "#5d6060", "#d5d2c9", "solid", 1),
            "source_texture": livery_texture(),
        },
    }

    builder = SemanticModelBuilder()
    for name, parent, pivot in (
        ("chassis", "root", (0, 4.8, 0)),
        ("body", "chassis", (0, 7.0, 0)),
        ("hood", "body", (0, 7.8, 10.0)),
        ("cabin", "body", (0, 9.5, -1.5)),
        ("rear_body", "body", (0, 7.6, -10.0)),
        ("spoiler", "rear_body", (0, 8.8, -14.0)),
        ("front_left_wheel", "chassis", (-7.35, 4.25, 9.0)),
        ("front_right_wheel", "chassis", (7.35, 4.25, 9.0)),
        ("rear_left_wheel", "chassis", (-7.35, 4.25, -9.2)),
        ("rear_right_wheel", "chassis", (7.35, 4.25, -9.2)),
        ("front_details", "hood", (0, 6.8, 15.5)),
        ("rear_details", "rear_body", (0, 6.5, -15.0)),
    ):
        builder.add_bone(name, parent, pivot)

    # A complete underbody and overlapping front/middle/rear masses establish
    # actual width and depth from every direction. +Z is the nose.
    body_cubes = (
        box("undertray", "chassis", (0, 2.7, 0), (13.8, 1.0, 30.5), "complete flat undertray", "dark_trim"),
        box("lower_chassis", "chassis", (0, 4.45, 0), (14.4, 3.4, 29.0), "full length low chassis volume", "silver_dark"),
        box("center_body", "body", (0, 6.45, 0.25), (14.6, 4.35, 25.8), "wide continuous 930 body waist", "silver"),
        box("front_nose", "hood", (0, 6.65, 14.15), (13.3, 3.05, 4.1), "low rounded front nose", "silver_light", rotation=(6, 0, 0)),
        box("hood_main", "hood", (0, 7.65, 10.45), (10.6, 2.45, 8.8), "narrow low sloping hood between fenders", "silver_light", rotation=(8, 0, 0)),
        box("front_left_fender_front", "hood", (-5.35, 7.35, 14.0), (4.0, 3.25, 3.7), "left rounded fender nose", "silver", rotation=(8, 0, -2)),
        box("front_right_fender_front", "hood", (5.35, 7.35, 14.0), (4.0, 3.25, 3.7), "right rounded fender nose", "silver", rotation=(8, 0, 2)),
        box("front_left_fender_crown", "hood", (-5.55, 8.15, 10.45), (3.8, 2.65, 5.5), "left raised fender crown over wheel", "silver", rotation=(6, 0, -2)),
        box("front_right_fender_crown", "hood", (5.55, 8.15, 10.45), (3.8, 2.65, 5.5), "right raised fender crown over wheel", "silver", rotation=(6, 0, 2)),
        box("front_left_fender_rear", "hood", (-5.6, 7.3, 7.35), (3.45, 3.0, 2.5), "left fender rear taper", "silver", rotation=(2, 0, -2)),
        box("front_right_fender_rear", "hood", (5.6, 7.3, 7.35), (3.45, 3.0, 2.5), "right fender rear taper", "silver", rotation=(2, 0, 2)),
        box("rear_deck", "rear_body", (0, 7.65, -11.0), (13.6, 3.0, 8.7), "sloping rear engine deck", "silver", rotation=(-5, 0, 0)),
        box("rear_left_haunch_front", "rear_body", (-5.7, 7.05, -6.8), (3.8, 3.35, 3.2), "left rear haunch front rise", "silver", rotation=(-2, 0, -2)),
        box("rear_right_haunch_front", "rear_body", (5.7, 7.05, -6.8), (3.8, 3.35, 3.2), "right rear haunch front rise", "silver", rotation=(-2, 0, 2)),
        box("rear_left_haunch_crown", "rear_body", (-5.9, 7.95, -9.45), (4.2, 3.0, 5.8), "left wide turbo fender crown", "silver", rotation=(-4, 0, -2), faces={"west": {"material": "side_livery"}}),
        box("rear_right_haunch_crown", "rear_body", (5.9, 7.95, -9.45), (4.2, 3.0, 5.8), "right wide turbo fender crown", "silver", rotation=(-4, 0, 2), faces={"east": {"material": "side_livery", "flip_x": True}}),
        box("rear_left_haunch_tail", "rear_body", (-5.6, 7.05, -13.3), (3.9, 3.35, 3.1), "left haunch rear taper", "silver", rotation=(-6, 0, -2)),
        box("rear_right_haunch_tail", "rear_body", (5.6, 7.05, -13.3), (3.9, 3.35, 3.1), "right haunch rear taper", "silver", rotation=(-6, 0, 2)),
        box("left_door_volume", "body", (-6.2, 6.55, -0.65), (2.15, 5.0, 10.9), "deep clean left door and sill volume", "silver"),
        box("right_door_volume", "body", (6.2, 6.55, -0.65), (2.15, 5.0, 10.9), "deep clean right door and sill volume", "silver"),
        box("left_rocker", "body", (-7.15, 3.85, -0.75), (1.1, 1.05, 18.2), "left black rocker trim", "dark_trim"),
        box("right_rocker", "body", (7.15, 3.85, -0.75), (1.1, 1.05, 18.2), "right black rocker trim", "dark_trim"),
        box("front_bumper", "front_details", (0, 4.75, 16.0), (14.5, 1.45, 1.15), "slim full width front bumper", "chrome"),
        box("front_splitter", "front_details", (0, 3.55, 16.3), (14.7, 0.55, 1.35), "thin black front splitter", "dark_trim"),
        box("rear_bumper", "rear_details", (0, 4.65, -15.45), (14.8, 1.55, 1.2), "slim full width rear impact bumper", "dark_trim"),
        box("rear_valance", "rear_details", (0, 3.65, -15.1), (14.1, 1.35, 1.45), "low rear valance", "silver_dark"),
    )
    for cube in body_cubes:
        builder.add_cube(cube)

    # The greenhouse is a closed, deep assembly rather than a painted side
    # panel. Strongly raked glass meets a three-step arched fastback roof.
    cabin_cubes = (
        box("cabin_floor", "cabin", (0, 8.85, -1.4), (11.6, 1.35, 12.7), "closed low cabin shoulder volume", "silver_dark"),
        box("windshield", "cabin", (0, 11.15, 3.7), (10.45, 4.45, 0.75), "strongly raked full width windshield", "glass_glint", rotation=(-42, 0, 0)),
        box("rear_glass", "cabin", (0, 10.95, -5.35), (9.9, 4.65, 0.75), "long fastback rear glass", "glass", rotation=(43, 0, 0)),
        box("roof_front_step", "cabin", (0, 13.15, 1.05), (9.7, 0.8, 2.35), "sloped front roof shoulder", "silver_light", rotation=(-10, 0, 0)),
        box("roof_crown", "cabin", (0, 13.45, -1.35), (9.2, 0.9, 3.65), "low central roof crown", "silver_light"),
        box("roof_rear_step", "cabin", (0, 13.1, -3.9), (9.35, 0.8, 2.55), "descending rear roof shoulder", "silver_light", rotation=(12, 0, 0)),
        box("left_front_window", "cabin", (-5.25, 11.25, 1.0), (0.5, 3.15, 4.7), "left door side window", "glass_glint", rotation=(-4, 0, 0)),
        box("right_front_window", "cabin", (5.25, 11.25, 1.0), (0.5, 3.15, 4.7), "right door side window", "glass_glint", rotation=(-4, 0, 0)),
        box("left_rear_window", "cabin", (-5.05, 11.1, -3.25), (0.55, 2.85, 3.55), "left tapering rear quarter window", "glass", rotation=(16, 0, 0)),
        box("right_rear_window", "cabin", (5.05, 11.1, -3.25), (0.55, 2.85, 3.55), "right tapering rear quarter window", "glass", rotation=(16, 0, 0)),
        box("left_b_pillar", "cabin", (-5.4, 11.2, -1.2), (0.6, 3.45, 0.6), "left B pillar", "silver_dark"),
        box("right_b_pillar", "cabin", (5.4, 11.2, -1.2), (0.6, 3.45, 0.6), "right B pillar", "silver_dark"),
        box("left_a_pillar", "cabin", (-5.3, 11.2, 3.75), (0.6, 4.45, 0.65), "left strongly swept A pillar", "silver_dark", rotation=(-42, 0, 0)),
        box("right_a_pillar", "cabin", (5.3, 11.2, 3.75), (0.6, 4.45, 0.65), "right strongly swept A pillar", "silver_dark", rotation=(-42, 0, 0)),
        box("left_c_pillar", "cabin", (-5.1, 11.0, -5.4), (0.65, 4.65, 0.65), "left fastback C pillar", "silver", rotation=(43, 0, 0)),
        box("right_c_pillar", "cabin", (5.1, 11.0, -5.4), (0.65, 4.65, 0.65), "right fastback C pillar", "silver", rotation=(43, 0, 0)),
    )
    for cube in cabin_cubes:
        builder.add_cube(cube)

    # Whale-tail, mirrors, and door handles are the strongest 930 identifiers
    # after the round lamps and arched greenhouse.
    detail_cubes = (
        box("spoiler_left_support", "spoiler", (-3.7, 8.85, -13.7), (0.9, 1.45, 1.35), "left compact whale-tail support", "silver_dark", rotation=(-7, 0, 0)),
        box("spoiler_right_support", "spoiler", (3.7, 8.85, -13.7), (0.9, 1.45, 1.35), "right compact whale-tail support", "silver_dark", rotation=(-7, 0, 0)),
        box("whale_tail", "spoiler", (0, 9.65, -14.65), (11.6, 0.62, 2.65), "thin integrated whale-tail spoiler", "silver", rotation=(-4, 0, 0)),
        box("left_mirror_stem", "cabin", (-6.0, 10.5, 2.75), (1.45, 0.55, 0.55), "left mirror stem", "dark_trim"),
        box("right_mirror_stem", "cabin", (6.0, 10.5, 2.75), (1.45, 0.55, 0.55), "right mirror stem", "dark_trim"),
        box("left_mirror", "cabin", (-7.0, 10.65, 2.85), (1.7, 1.1, 1.8), "left compact mirror housing", "silver_dark", rotation=(0, 6, -4)),
        box("right_mirror", "cabin", (7.0, 10.65, 2.85), (1.7, 1.1, 1.8), "right compact mirror housing", "silver_dark", rotation=(0, -6, 4)),
        box("left_door_handle", "body", (-7.35, 7.75, -1.35), (0.4, 0.4, 1.65), "left black door handle", "dark_trim"),
        box("right_door_handle", "body", (7.35, 7.75, -1.35), (0.4, 0.4, 1.65), "right black door handle", "dark_trim"),
    )
    for cube in detail_cubes:
        builder.add_cube(cube)

    # Axles make the wheels structurally connected while each corner retains
    # a distinct semantic bone for animation and inspection.
    builder.add_cube(box("front_axle", "chassis", (0, 4.25, 9.0), (16.2, 1.2, 1.2), "front axle connecting both wheels", "hub_dark"))
    builder.add_cube(box("rear_axle", "chassis", (0, 4.25, -9.2), (16.2, 1.2, 1.2), "rear axle connecting both wheels", "hub_dark"))

    wheel_records: list[tuple[str, float, float]] = []
    for axle, z, diameter in (("front", 9.0, 7.9), ("rear", -9.2, 7.9)):
        for side, x in (("left", -7.35), ("right", 7.35)):
            prefix = f"{axle}_{side}_wheel"
            bone = prefix
            outward = -1 if side == "left" else 1
            builder.add_cube(box(f"{prefix}_tire_vertical", bone, (x, 4.25, z), (3.55, diameter, 4.75), f"{axle} {side} vertical tire lobe", "rubber"))
            builder.add_cube(box(f"{prefix}_tire_diagonal", bone, (x, 4.25, z), (3.6, diameter * 0.9, 4.5), f"{axle} {side} diagonal tire lobe", "rubber", rotation=(45, 0, 0)))
            builder.add_cube(box(f"{prefix}_sidewall", bone, (x + outward * 1.55, 4.25, z), (0.68, diameter * 0.56, 3.3), f"{axle} {side} inset diagonal sidewall", "sidewall", rotation=(45, 0, 0)))
            builder.add_cube(box(f"{prefix}_hub", bone, (x + outward * 1.87, 4.25, z), (0.62, 4.15, 4.15), f"{axle} {side} bronze wheel hub", "wheel_metal"))
            builder.add_cube(box(f"{prefix}_spoke_vertical", bone, (x + outward * 2.2, 4.25, z), (0.3, 3.55, 0.62), f"{axle} {side} vertical wheel spoke", "hub_dark"))
            builder.add_cube(box(f"{prefix}_spoke_horizontal", bone, (x + outward * 2.22, 4.25, z), (0.3, 0.62, 3.55), f"{axle} {side} horizontal wheel spoke", "hub_dark"))
            builder.add_cube(box(f"{prefix}_center_cap", bone, (x + outward * 2.4, 4.25, z), (0.24, 1.05, 1.05), f"{axle} {side} wheel center cap", "chrome"))
            wheel_records.append((prefix, x, z))

    # A body-colored recessed bezel and alpha-masked octagonal pixel lens make
    # each lamp read round without adding a square yellow block above the hood.
    for side, x in (("left", -4.65), ("right", 4.65)):
        builder.add_cube(box(f"{side}_headlamp_vertical", "front_details", (x, 8.25, 16.02), (2.8, 2.8, 0.48), f"{side} recessed headlamp bezel", "silver_dark"))
        builder.add_cube(box(f"{side}_headlamp_horizontal", "front_details", (x, 8.25, 16.3), (2.55, 2.55, 0.26), f"{side} round alpha-masked headlamp lens", "headlamp"))
        builder.add_cube(box(f"{side}_headlamp_glint", "front_details", (x - 0.25, 8.55, 16.48), (0.42, 0.42, 0.18), f"{side} headlamp glint", "lamp_glint"))
        builder.add_cube(box(f"{side}_turn_signal", "front_details", (x, 5.45, 16.65), (2.25, 0.72, 0.35), f"{side} amber bumper indicator", "amber"))

    builder.add_cube(box("front_grille", "front_details", (0, 5.3, 16.65), (3.8, 0.72, 0.35), "center front cooling grille", "dark_trim"))
    builder.add_cube(box("front_plate", "front_details", (0, 4.4, 16.92), (3.8, 1.05, 0.3), "front license plate", "plate"))
    builder.add_cube(box("rear_light_left", "rear_details", (-3.85, 6.65, -16.0), (5.4, 1.05, 0.42), "left rear tail lamp", "tail_lamp"))
    builder.add_cube(box("rear_light_right", "rear_details", (3.85, 6.65, -16.0), (5.4, 1.05, 0.42), "right rear tail lamp", "tail_lamp"))
    builder.add_cube(box("rear_center_reflector", "rear_details", (0, 6.65, -16.04), (2.0, 1.05, 0.45), "center red rear reflector", "red"))
    builder.add_cube(box("rear_plate", "rear_details", (0, 5.15, -16.02), (3.8, 1.05, 0.32), "rear license plate", "plate"))
    builder.add_cube(box("left_exhaust", "rear_details", (-4.8, 2.9, -15.9), (1.8, 0.85, 1.2), "left black exhaust tip", "dark_trim"))
    builder.add_cube(box("right_exhaust", "rear_details", (4.8, 2.9, -15.9), (1.8, 0.85, 1.2), "right black exhaust tip", "dark_trim"))

    # Shared-joint records prove each wheel/axle and spoiler support connects.
    attachments = []
    for prefix, x, z in wheel_records:
        axle_name = "front_axle" if prefix.startswith("front") else "rear_axle"
        joint_x = x + (0.55 if x < 0 else -0.55)
        attachments.append((axle_name, f"{prefix}_tire_vertical", (joint_x, 4.25, z)))
        attachments.extend(
            [
                (f"{prefix}_tire_vertical", f"{prefix}_sidewall", (x + (-1 if x < 0 else 1) * 1.45, 4.25, z)),
                (f"{prefix}_sidewall", f"{prefix}_hub", (x + (-1 if x < 0 else 1) * 1.77, 4.25, z)),
            ]
        )
    attachments.extend(
        [
            ("rear_deck", "spoiler_left_support", (-3.7, 8.3, -13.7)),
            ("rear_deck", "spoiler_right_support", (3.7, 8.3, -13.7)),
            ("spoiler_left_support", "whale_tail", (-3.7, 9.4, -14.2)),
            ("spoiler_right_support", "whale_tail", (3.7, 9.4, -14.2)),
        ]
    )

    names = [cube["name"] for cube in builder.cubes]
    body_names = {
        "undertray",
        "lower_chassis",
        "center_body",
        "front_nose",
        "hood_main",
        "rear_deck",
    } | {
        name
        for name in names
        if "fender_" in name or "haunch_" in name
    }
    feature_inventory = {
        "body_volumes": sum(name in body_names for name in names),
        "fender_haunch_volumes": sum("fender" in name or "haunch" in name for name in names),
        "wheel_assemblies": len(wheel_records),
        "wheel_cuboids": sum("_wheel_" in name for name in names),
        "headlamp_cuboids": sum("headlamp" in name for name in names),
        "greenhouse_glass": sum(name in {"windshield", "rear_glass", "left_front_window", "right_front_window", "left_rear_window", "right_rear_window"} for name in names),
        "mirrors": sum(name in {"left_mirror", "right_mirror"} for name in names),
        "spoiler_cuboids": sum(name in {"spoiler_left_support", "spoiler_right_support", "whale_tail"} for name in names),
        "tail_lamps": sum(name.startswith("rear_light_") for name in names),
    }

    spec = {
        "schema_version": 1,
        "id": "porsche_911_turbo_930",
        "reference": {
            "image": str(REFERENCE.resolve()),
            "sha256": EXPECTED_SHA256,
            "width": 1859,
            "height": 609,
        },
        "subject": {
            "type": "vehicle",
            "description": "Complete silver Porsche 911 Turbo 930 with red-white racing livery",
            "symmetry": "bilateral",
            "uncertainties": [
                "The single three-quarter image hides the exact opposite-side decals",
                "Underside and engine-bay details are conservatively inferred",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [80, 110],
            "identity_features": [
                "low sloping hood and paired round headlamps",
                "arched compact greenhouse with sloped windshield and rear glass",
                "four complete deep wheels under flared fenders",
                "wide rear turbo haunches and raised whale-tail spoiler",
                "red-white diagonal side racing livery",
            ],
            "required_views": ["front", "back", "left", "right", "top", "isometric", "reference-angle", "wheel-closeup", "greenhouse-closeup"],
            "review_targets": ["complete 3D volume", "930 silhouette", "four wheel grounding", "circular lamps", "greenhouse", "spoiler", "side livery"],
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
        "landmarks": [
            {"name": "hood_badge", "cube": "hood_main", "face": "up", "center_uv": [0.5, 0.77], "size": [1, 1], "color": "#9f7727", "center_color": "#e0be55"},
            {"name": "roof_banner_left", "cube": "windshield", "face": "south", "center_uv": [0.36, 0.12], "size": [3, 1], "color": "#e5e1d7", "center_color": "#252628"},
            {"name": "roof_banner_right", "cube": "windshield", "face": "south", "center_uv": [0.64, 0.12], "size": [3, 1], "color": "#e5e1d7", "center_color": "#252628"},
        ],
        "collision": {"width": 1.9, "height": 1.25, "eye_height": 1.05},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "complete-hard-surface-semantic-cuboids-v2",
            "source_mesh": None,
            "source_skin_cuboids": 0,
            "authored_texture_sources": ["side_livery"],
            "anatomical_axis": "+Z nose, X width, Y up",
            "single_view_hidden_geometry": "Opposite side mirrors observed side geometry; front, rear, roof, underbody, and exact wheel depth are conservative Porsche 930 priors.",
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
