#!/usr/bin/env python3
"""Author the Round 3 Atlus as a holistic native Blockbench vehicle."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image

from semantic_geometry import SemanticModelBuilder, segment_cube


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "round3-inputs" / "atlus.png"
MULTIVIEW = ROOT / "round3-inputs" / "atlus-multiview"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "5458ba42d698b38ed2a0a3a55e17a4608a2a4579f3bcdfc22a9b3e7018c74a25"
LONGITUDINAL_SCALE = 1.25
MULTIVIEW_REFERENCES = {
    "front-quarter": "12c3c09ae7ba0c10efe46411c57a13f1477b695923e05475ce34b07c6ca7e967",
    "front": "7bb5a2aebb27c2c4d42343f0ef3b19f993733a596b7187576d22d2623227daa4",
    "side": "c47b04501de8a59322ae03d6bfb8d2302e5f474f58a3f022bb5cfa22818c0d98",
    "rear": "6454b749f851f58f77b3d670683855cb020c18d6e61b2642a47b24fb37b2d83d",
    "top": "a4a01fa0d23029f3299e493428db8c737fddca533e66e221f464eb10be79a4f0",
}


def material(base: str, shade: str, highlight: str) -> dict[str, Any]:
    """Return one clean, bounded Minecraft panel material."""
    return {
        "base": base,
        "shade": shade,
        "highlight": highlight,
        "pattern": "solid",
        "pattern_scale": 1,
    }


def stretch(point: tuple[float, float, float]) -> tuple[float, float, float]:
    """Apply the independently observed top/side-view length proportion."""
    return point[0], point[1], point[2] * LONGITUDINAL_SCALE


def box(
    name: str,
    bone: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    role: str,
    paint: str,
    *,
    rotation: tuple[float, float, float] = (0, 0, 0),
    origin: tuple[float, float, float] | None = None,
    faces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one named semantic cuboid."""
    stretched_center = stretch(center)
    stretched_origin = stretch(origin or center)
    return {
        "name": name,
        "bone": bone,
        "center": list(stretched_center),
        "size": [size[0], size[1], size[2] * LONGITUDINAL_SCALE],
        "rotation": list(rotation),
        "origin": list(stretched_origin),
        "role": role,
        "material": paint,
        "faces": dict(faces or {}),
    }


def add_cross(
    landmarks: list[dict[str, Any]],
    prefix: str,
    cube: str,
    face: str,
    center_uv: tuple[float, float],
    size: int,
) -> None:
    """Add a two-stroke red medical cross as texture pixels."""
    landmarks.extend(
        [
            {
                "name": f"{prefix}_vertical",
                "cube": cube,
                "face": face,
                "center_uv": list(center_uv),
                "size": [max(2, size // 3), size],
                "color": "#9b1d2a",
                "center_color": "#d8373f",
            },
            {
                "name": f"{prefix}_horizontal",
                "cube": cube,
                "face": face,
                "center_uv": list(center_uv),
                "size": [size, max(2, size // 3)],
                "color": "#9b1d2a",
                "center_color": "#d8373f",
            },
        ]
    )


def main() -> None:
    """Write a deep, six-view-readable Trauma Team aerodyne."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Atlus reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (712, 340):
            raise ValueError(f"unexpected Atlus reference dimensions: {opened.size}")
    for view, digest in MULTIVIEW_REFERENCES.items():
        path = MULTIVIEW / f"{view}.webp"
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"unexpected Atlus {view} reference hash")
        with Image.open(path) as opened:
            if opened.size != (1920, 1080):
                raise ValueError(f"unexpected Atlus {view} dimensions: {opened.size}")

    materials = {
        "white": material("#d9e0e2", "#879198", "#f5f8f7"),
        "white_bright": material("#eef2ef", "#aeb8bc", "#ffffff"),
        "white_shadow": material("#9ea9ae", "#5c6870", "#d1d8d9"),
        "teal": material("#2a9da5", "#15555f", "#62cbd0"),
        "teal_dark": material("#17616d", "#0b3039", "#3599a4"),
        "teal_light": material("#55bfc2", "#277b83", "#91e1dc"),
        "gunmetal": material("#313b46", "#121820", "#667481"),
        "vent": material("#17232d", "#080d12", "#485865"),
        "glass": material("#24445d", "#101e2b", "#6b91a7"),
        "red": material("#a3212c", "#4b0d14", "#e2454c"),
        "amber": material("#d69225", "#6e3a08", "#ffd15b"),
        "blue_light": material("#38c2d7", "#126071", "#8ce8ee"),
        "rubber": material("#20252b", "#090c10", "#4b525a"),
    }

    builder = SemanticModelBuilder(pivot=(0, 0, 0))
    for name, parent, pivot in (
        ("chassis", "root", (0, 9, 0)),
        ("nose", "chassis", (0, 11, 15)),
        ("cabin", "chassis", (0, 14, 0)),
        ("rear", "chassis", (0, 11, -16)),
        ("roof", "cabin", (0, 19, -2)),
        ("left_pod", "chassis", (-13.5, 11, 0)),
        ("right_pod", "chassis", (13.5, 11, 0)),
        ("undercarriage", "chassis", (0, 7, 0)),
    ):
        builder.add_bone(name, parent, stretch(pivot))

    attachments: list[tuple[str, str, tuple[float, float, float]]] = []

    # The central fuselage is a true 3D volume with a long belly, layered roof,
    # faceted prow, and a modeled rear rather than a side-view extrusion.
    central = (
        box("belly_keel", "chassis", (0, 8.2, -0.5), (18, 4.5, 34),
            "full-length armored belly", "gunmetal"),
        box("lower_fuselage", "chassis", (0, 10.6, 0), (22, 5.0, 34),
            "deep central load-bearing fuselage", "teal_dark"),
        box("mid_fuselage", "cabin", (0, 13.6, -0.5), (23, 6.2, 31),
            "broad pressurized cabin volume", "white_shadow"),
        box("upper_cabin", "cabin", (0, 17.0, -2.0), (20, 3.7, 23),
            "raised central cabin crown", "white"),
        box("roof_spine", "roof", (0, 19.1, -2.2), (15, 1.1, 19),
            "long armored roof spine", "white_bright"),
        box("roof_front_slope", "roof", (0, 18.4, 8.3), (17, 2.0, 5.4),
            "sloped forward roof transition", "white", rotation=(12, 0, 0)),
        box("nose_deck", "nose", (0, 14.3, 14.3), (21, 4.3, 9.0),
            "broad descending prow deck", "white", rotation=(10, 0, 0)),
        box("nose_mid", "nose", (0, 12.1, 19.1), (19, 4.2, 6.7),
            "faceted forward prow", "white_bright", rotation=(8, 0, 0)),
        box("nose_tip", "nose", (0, 10.4, 23.0), (15, 3.2, 3.0),
            "blunt armored nose tip", "white_shadow", rotation=(7, 0, 0)),
        box("nose_lower", "nose", (0, 9.1, 19.5), (17, 3.0, 7.0),
            "recessed lower prow", "teal_dark", rotation=(7, 0, 0)),
        box("front_grille", "nose", (0, 9.7, 24.45), (11.0, 3.0, 0.8),
            "ribbed-looking forward cooling grille", "vent"),
        box("left_windscreen", "cabin", (-5.2, 16.1, 10.4), (8.2, 2.6, 0.65),
            "left forward cockpit glazing", "glass", rotation=(11, 0, 0)),
        box("right_windscreen", "cabin", (5.2, 16.1, 10.4), (8.2, 2.6, 0.65),
            "right forward cockpit glazing", "glass", rotation=(11, 0, 0)),
        box("windscreen_brow", "cabin", (0, 17.7, 10.0), (17.2, 0.8, 1.2),
            "thick cockpit brow", "white_bright", rotation=(8, 0, 0)),
        box("rear_cabin", "rear", (0, 13.5, -16.2), (21, 7.0, 7.5),
            "deep rear cabin and machinery bay", "white"),
        box("rear_upper_taper", "rear", (0, 16.8, -17.0), (17, 3.0, 7.0),
            "tapered upper rear armor", "white_shadow", rotation=(-7, 0, 0)),
        box("rear_bumper", "rear", (0, 9.3, -20.6), (18, 3.0, 1.8),
            "rear impact and thruster beam", "gunmetal"),
        box("rear_service_panel", "rear", (0, 13.0, -20.25), (10, 4.6, 0.7),
            "rear service hatch", "white_bright"),
        box("left_cabin_rail", "cabin", (-10.8, 13.0, -1.5), (1.0, 5.5, 26),
            "left longitudinal cabin edge", "gunmetal"),
        box("right_cabin_rail", "cabin", (10.8, 13.0, -1.5), (1.0, 5.5, 26),
            "right longitudinal cabin edge", "gunmetal"),
    )
    for cube in central:
        builder.add_cube(cube)

    attachments.extend(
        [
            ("belly_keel", "lower_fuselage", (0, 9.8, 0)),
            ("lower_fuselage", "mid_fuselage", (0, 12.0, 0)),
            ("mid_fuselage", "upper_cabin", (0, 15.3, -2)),
            ("upper_cabin", "roof_spine", (0, 18.7, -2)),
            ("upper_cabin", "roof_front_slope", (0, 17.8, 7.8)),
            ("mid_fuselage", "nose_deck", (0, 14.0, 12.5)),
            ("nose_deck", "nose_mid", (0, 13.0, 17.0)),
            ("nose_mid", "nose_tip", (0, 11.2, 21.8)),
            ("nose_mid", "nose_lower", (0, 9.8, 20.8)),
            ("lower_fuselage", "rear_cabin", (0, 11.8, -15.5)),
            ("rear_cabin", "rear_upper_taper", (0, 16.0, -17.0)),
            ("rear_cabin", "rear_bumper", (0, 10.5, -19.8)),
        ]
    )

    # Side nacelles are deep longitudinal assemblies. Each has an outer door,
    # forward intake, rear machinery, and underside fin, all visible in side views.
    pod_feature_names: dict[str, list[str]] = {"left": [], "right": []}
    for side, sign in (("left", -1), ("right", 1)):
        bone = f"{side}_pod"
        outward = "west" if sign < 0 else "east"
        roll = 4 * sign
        pod_cubes = (
            box(f"{side}_pod_bridge_front", bone, (9.9 * sign, 11.4, 9.0),
                (4.2, 2.4, 5.2), f"{side} forward nacelle bridge", "gunmetal"),
            box(f"{side}_pod_bridge_rear", bone, (9.9 * sign, 11.2, -9.0),
                (4.2, 2.4, 5.2), f"{side} rear nacelle bridge", "gunmetal"),
            box(f"{side}_pod_core", bone, (14.0 * sign, 11.7, -0.5),
                (7.8, 8.8, 25.5), f"{side} full-depth teal nacelle", "teal"),
            box(f"{side}_pod_upper", bone, (13.7 * sign, 15.3, -1.0),
                (7.2, 3.2, 22.5), f"{side} upper nacelle cowling", "white", rotation=(0, 0, roll)),
            box(f"{side}_pod_lower", bone, (14.0 * sign, 8.1, -1.5),
                (6.8, 2.2, 20.5), f"{side} lower nacelle keel", "teal_dark", rotation=(0, 0, -roll)),
            box(f"{side}_front_shoulder", bone, (14.2 * sign, 12.8, 12.7),
                (8.5, 8.3, 7.0), f"{side} large forward pod shoulder", "teal_light", rotation=(5, 0, roll)),
            box(f"{side}_front_brow", bone, (14.0 * sign, 16.5, 13.1),
                (7.8, 1.5, 6.0), f"{side} white forward pod brow", "white_bright", rotation=(5, 0, roll)),
            box(f"{side}_intake_frame", bone, (14.2 * sign, 12.4, 16.0),
                (6.4, 6.0, 1.2), f"{side} forward intake frame", "white_shadow"),
            box(f"{side}_intake", bone, (14.2 * sign, 12.4, 16.7),
                (4.6, 4.3, 0.8), f"{side} dark forward intake cavity", "vent"),
            box(f"{side}_rear_housing", bone, (14.0 * sign, 11.8, -14.0),
                (7.6, 8.3, 6.3), f"{side} rear nacelle machinery", "white_shadow", rotation=(-4, 0, roll)),
            box(f"{side}_rear_cap", bone, (14.0 * sign, 11.4, -17.4),
                (6.3, 6.3, 1.4), f"{side} rear nacelle exhaust frame", "gunmetal"),
            box(f"{side}_rear_throat", bone, (14.0 * sign, 11.4, -18.2),
                (4.5, 4.5, 0.7), f"{side} rear nacelle dark exhaust", "vent"),
            box(f"{side}_rear_core", bone, (14.0 * sign, 11.4, -18.6),
                (2.6, 2.6, 0.5), f"{side} cyan rear drive core", "blue_light"),
            box(f"{side}_outer_door", bone, (17.95 * sign, 13.0, -1.5),
                (0.72, 8.0, 18.0), f"{side} broad Trauma Team side door", "white_bright"),
            box(f"{side}_door_top", bone, (18.15 * sign, 17.0, -1.5),
                (0.52, 0.65, 18.5), f"{side} raised door top seam", "gunmetal"),
            box(f"{side}_door_bottom", bone, (18.15 * sign, 9.0, -1.5),
                (0.52, 0.65, 18.5), f"{side} raised door bottom seam", "gunmetal"),
            box(f"{side}_door_front", bone, (18.15 * sign, 13.0, 7.5),
                (0.52, 7.4, 0.65), f"{side} raised forward door seam", "gunmetal"),
            box(f"{side}_door_rear", bone, (18.15 * sign, 13.0, -10.5),
                (0.52, 7.4, 0.65), f"{side} raised rear door seam", "gunmetal"),
            box(f"{side}_top_sensor", bone, (14.0 * sign, 17.4, 4.4),
                (3.0, 0.9, 3.2), f"{side} nacelle roof sensor", "red"),
            box(f"{side}_bottom_fin", bone, (14.0 * sign, 6.2, -2.0),
                (3.0, 3.0, 7.2), f"{side} stabilizing underside fin", "gunmetal", rotation=(0, 0, -roll)),
            box(f"{side}_forward_strake", bone, (17.0 * sign, 9.0, 11.3),
                (2.0, 2.2, 7.0), f"{side} forward lower strake", "white", rotation=(6, 0, roll)),
            box(f"{side}_rear_strake", bone, (17.0 * sign, 8.8, -10.6),
                (2.0, 2.2, 6.2), f"{side} rear lower strake", "white", rotation=(-6, 0, roll)),
        )
        for cube in pod_cubes:
            builder.add_cube(cube)
            pod_feature_names[side].append(cube["name"])
        attachments.extend(
            [
                ("mid_fuselage", f"{side}_pod_bridge_front", (10.5 * sign, 12.0, 9.0)),
                (f"{side}_pod_bridge_front", f"{side}_pod_core", (11.5 * sign, 11.8, 9.0)),
                ("lower_fuselage", f"{side}_pod_bridge_rear", (10.5 * sign, 11.2, -9.0)),
                (f"{side}_pod_bridge_rear", f"{side}_pod_core", (11.5 * sign, 11.5, -9.0)),
                (f"{side}_pod_core", f"{side}_front_shoulder", (14 * sign, 12.0, 11.0)),
                (f"{side}_pod_core", f"{side}_rear_housing", (14 * sign, 11.7, -12.5)),
                (f"{side}_rear_housing", f"{side}_rear_cap", (14 * sign, 11.5, -17.0)),
            ]
        )

    # Four articulated landing modules create an informative underside and make
    # the craft read as a massive VTOL rather than a flat decorated slab.
    gear_records = []
    for station, z in (("front", 9.0), ("rear", -10.0)):
        for side, sign in (("left", -1), ("right", 1)):
            prefix = f"{station}_{side}_gear"
            root = (13.5 * sign, 8.0, z)
            knee = (14.0 * sign, 5.8, z - 0.4)
            ankle = (14.0 * sign, 3.1, z - 0.1)
            strut = segment_cube(
                f"{prefix}_strut", "undercarriage", stretch(root), stretch(knee), (4.0, 4.0),
                f"{station} {side} integrated upper hover pylon", "gunmetal", overlap=0.35,
            )
            lower = segment_cube(
                f"{prefix}_lower", "undercarriage", stretch(knee), stretch(ankle), (5.0, 5.0),
                f"{station} {side} chunky lower hover pylon", "teal_dark", overlap=0.35,
            )
            shoe = box(f"{prefix}_shoe", "undercarriage", (14.0 * sign, 1.6, z + 0.25),
                       (7.0, 3.2, 7.5), f"{station} {side} broad hover and landing housing", "rubber",
                       faces={"down": {"material": "blue_light"}})
            armor = box(f"{prefix}_armor", "undercarriage", (16.8 * sign, 4.6, z - 0.2),
                        (2.2, 5.5, 4.4), f"{station} {side} outer hover-pylon armor", "teal_dark")
            toe = box(f"{prefix}_toe", "undercarriage", (14.0 * sign, 0.8, z + 4.0),
                      (6.0, 1.6, 1.2), f"{station} {side} forward hover-housing lip", "gunmetal")
            for cube in (strut, lower, shoe, armor, toe):
                builder.add_cube(cube)
            attachments.extend(
                [
                    (f"{side}_pod_core", strut["name"], root),
                    (strut["name"], lower["name"], knee),
                    (lower["name"], armor["name"], (15.8 * sign, 4.5, z - 0.2)),
                    (lower["name"], shoe["name"], ankle),
                    (shoe["name"], toe["name"], (14.0 * sign, 0.9, z + 3.9)),
                ]
            )
            gear_records.append(
                {"name": prefix, "root": list(stretch(root)), "knee": list(stretch(knee)),
                 "ankle": list(stretch(ankle)), "shoe": shoe["name"]}
            )

    # Rear drive cluster, roof equipment, side sensors, and bounded panel relief.
    details = [
        box("rear_thruster_left_frame", "rear", (-6.2, 11.0, -21.1), (5.0, 4.5, 1.2),
            "left central rear thruster frame", "gunmetal"),
        box("rear_thruster_left_core", "rear", (-6.2, 11.0, -21.8), (3.2, 2.8, 0.6),
            "left central rear cyan thruster", "blue_light"),
        box("rear_thruster_right_frame", "rear", (6.2, 11.0, -21.1), (5.0, 4.5, 1.2),
            "right central rear thruster frame", "gunmetal"),
        box("rear_thruster_right_core", "rear", (6.2, 11.0, -21.8), (3.2, 2.8, 0.6),
            "right central rear cyan thruster", "blue_light"),
        box("rear_thruster_center_frame", "rear", (0, 8.0, -21.0), (4.0, 2.3, 1.0),
            "lower central rear thruster frame", "vent"),
        box("rear_thruster_center_core", "rear", (0, 8.0, -21.6), (2.5, 1.3, 0.5),
            "lower central rear cyan thruster", "blue_light"),
        box("roof_medical_panel", "roof", (0, 19.75, -2.0), (8.2, 0.45, 7.0),
            "raised roof medical identification panel", "white_bright"),
        box("roof_front_beacon_left", "roof", (-5.5, 19.9, 5.6), (2.3, 0.7, 1.3),
            "left red roof beacon", "red"),
        box("roof_front_beacon_right", "roof", (5.5, 19.9, 5.6), (2.3, 0.7, 1.3),
            "right red roof beacon", "red"),
        box("roof_rear_beacon_left", "roof", (-5.5, 19.9, -9.5), (2.3, 0.7, 1.3),
            "left rear roof beacon", "red"),
        box("roof_rear_beacon_right", "roof", (5.5, 19.9, -9.5), (2.3, 0.7, 1.3),
            "right rear roof beacon", "red"),
        box("roof_sensor_left", "roof", (-6.2, 19.9, 0.6), (2.2, 0.8, 2.2),
            "left roof optical sensor", "glass"),
        box("roof_sensor_right", "roof", (6.2, 19.9, 0.6), (2.2, 0.8, 2.2),
            "right roof optical sensor", "glass"),
        box("nose_red_chevron_left", "nose", (-5.8, 16.3, 13.2), (5.0, 0.55, 1.0),
            "left raised red prow marking", "red", rotation=(10, 0, 0)),
        box("nose_red_chevron_right", "nose", (5.8, 16.3, 13.2), (5.0, 0.55, 1.0),
            "right raised red prow marking", "red", rotation=(10, 0, 0)),
    ]
    for cube in details:
        builder.add_cube(cube)

    # Atlus-specific silhouette assemblies established by the official front,
    # side, rear, and top views.
    for side, sign in (("left", -1), ("right", 1)):
        builder.add_cube(
            box(
                f"{side}_nose_cheek", "nose", (8.6 * sign, 13.2, 19.0),
                (4.2, 4.8, 9.0), f"{side} tapered armored prow cheek", "white",
                rotation=(5, -11 * sign, 2 * sign),
            )
        )
        builder.add_cube(
            box(
                f"{side}_canopy_side", "cabin", (10.25 * sign, 16.5, 8.0),
                (0.65, 2.8, 5.4), f"{side} angled canopy side glazing", "glass",
                rotation=(4, 0, 2 * sign),
            )
        )
        builder.add_cube(
            box(
                f"{side}_nose_weapon_housing", "nose", (4.8 * sign, 7.1, 18.5),
                (4.0, 2.5, 4.8), f"{side} under-nose four-barrel weapon housing", "gunmetal",
            )
        )
        barrel_index = 0
        for x_offset in (-0.65, 0.65):
            for y_offset in (-0.55, 0.55):
                barrel_index += 1
                builder.add_cube(
                    box(
                        f"{side}_nose_weapon_barrel_{barrel_index}", "nose",
                        (4.8 * sign + x_offset, 7.1 + y_offset, 23.2),
                        (0.62, 0.62, 7.2), f"{side} under-nose weapon barrel {barrel_index}",
                        "gunmetal",
                    )
                )
                builder.add_cube(
                    box(
                        f"{side}_nose_weapon_muzzle_{barrel_index}", "nose",
                        (4.8 * sign + x_offset, 7.1 + y_offset, 26.85),
                        (1.0, 1.0, 0.6), f"{side} weapon muzzle collar {barrel_index}",
                        "white_shadow",
                    )
                )
        for index, y in enumerate((9.8, 10.8, 11.8, 12.8)):
            builder.add_cube(
                box(
                    f"{side}_rear_pod_louver_{index + 1}", f"{side}_pod",
                    (14.0 * sign, y, -18.75), (5.8, 0.42, 0.65),
                    f"{side} rear hover-pod exhaust louver", "vent",
                )
            )

    underside_machinery = (
        box("ventral_equipment_bay", "undercarriage", (0, 6.2, -1.0), (14.0, 2.4, 18.0),
            "chunky central ventral equipment bay", "gunmetal"),
        box("ventral_forward_gimbal", "undercarriage", (0, 5.2, 10.5), (6.5, 3.4, 6.0),
            "forward underside sensor and weapon gimbal", "white_shadow"),
        box("ventral_gimbal_core", "undercarriage", (0, 4.3, 12.0), (4.0, 2.0, 3.2),
            "dark forward gimbal core", "vent"),
        box("ventral_left_tank", "undercarriage", (-4.5, 5.0, -8.5), (4.0, 3.0, 8.0),
            "left underside machinery tank", "teal_dark"),
        box("ventral_right_tank", "undercarriage", (4.5, 5.0, -8.5), (4.0, 3.0, 8.0),
            "right underside machinery tank", "teal_dark"),
        box("ventral_rear_guard", "undercarriage", (0, 5.0, -14.5), (11.0, 2.0, 3.5),
            "rear underside machinery guard", "white_shadow"),
    )
    for cube in underside_machinery:
        builder.add_cube(cube)

    # Orthographic front/rear evidence exposes these silhouette-defining parts:
    # a broad central louver stack, ribbed outer hover pods, rear light rails,
    # and paired roof turbine ports. They are modeled on their observed axes.
    for index, y in enumerate((8.45, 8.9, 9.35, 9.8, 10.25, 10.7, 11.15)):
        builder.add_cube(
            box(
                f"front_grille_louver_{index + 1}", "nose", (0, y, 24.9),
                (11.5, 0.28, 0.55), "front cooling grille horizontal louver", "white_shadow",
            )
        )
    for side, sign in (("left", -1), ("right", 1)):
        for index, y in enumerate((10.7, 11.6, 12.5, 13.4)):
            builder.add_cube(
                box(
                    f"{side}_front_pod_rib_{index + 1}", f"{side}_pod",
                    (14.2 * sign, y, 17.22), (6.2, 0.38, 0.55),
                    f"{side} forward hover-pod cooling rib", "gunmetal",
                )
            )
        builder.add_cube(
            box(
                f"{side}_rear_light_rail", "rear", (10.6 * sign, 14.0, -20.72),
                (0.8, 6.5, 0.52), f"{side} vertical rear emergency light rail", "red",
            )
        )
        builder.add_cube(
            box(
                f"{side}_roof_turbine_port", "roof", (4.5 * sign, 19.8, -1.5),
                (3.2, 0.75, 3.2), f"{side} square Minecraft abstraction of roof turbine port", "vent",
            )
        )
        for station, z in (("front", 9.0), ("rear", -10.0)):
            builder.add_cube(
                box(
                    f"{side}_{station}_hover_nozzle", f"{side}_pod",
                    (14.0 * sign, 6.3, z), (3.4, 1.2, 3.4),
                    f"{side} {station} downward hover nozzle", "vent",
                )
            )
            builder.add_cube(
                box(
                    f"{side}_{station}_hover_core", f"{side}_pod",
                    (14.0 * sign, 5.55, z), (2.1, 0.45, 2.1),
                    f"{side} {station} cyan downward hover core", "blue_light",
                )
            )

    # Three slim aerials use true rotated depth-bearing cuboids.
    aerials = (
        ("antenna_left", (-5.0, 19.5, -7.0), (-5.6, 24.0, -7.6)),
        ("antenna_right", (5.0, 19.5, -7.0), (5.7, 24.6, -7.7)),
        ("antenna_center", (0, 19.5, -10.0), (0, 22.8, -11.0)),
    )
    for name, start, end in aerials:
        builder.add_cube(segment_cube(name, "roof", stretch(start), stretch(end), 0.38,
                                      "roof communications aerial", "gunmetal", overlap=0.1))

    landmarks: list[dict[str, Any]] = []
    for side, face in (("left", "west"), ("right", "east")):
        add_cross(landmarks, f"{side}_door_cross", f"{side}_outer_door", face, (0.52, 0.48), 9)
        for index, uv in enumerate(((0.43, 0.39), (0.61, 0.39), (0.43, 0.57), (0.61, 0.57))):
            landmarks.append({
                "name": f"{side}_door_cross_diagonal_{index + 1}",
                "cube": f"{side}_outer_door",
                "face": face,
                "center_uv": list(uv),
                "size": [2, 2],
                "color": "#9b1d2a",
                "center_color": "#d8373f",
            })
        # A tiny upper stripe and three dark ventilation perforations add the
        # source's crisp graphic hierarchy without procedural texture noise.
        landmarks.append({
            "name": f"{side}_door_label",
            "cube": f"{side}_outer_door",
            "face": face,
            "center_uv": [0.52, 0.18],
            "size": [8, 1],
            "color": "#a3212c",
            "center_color": "#d8373f",
        })
        for index, uv in enumerate(((0.25, 0.30), (0.25, 0.38), (0.25, 0.46))):
            landmarks.append({
                "name": f"{side}_pod_vent_{index + 1}",
                "cube": f"{side}_front_shoulder",
                "face": face,
                "center_uv": list(uv),
                "size": [2, 2],
                "color": "#16242c",
                "center_color": "#0a1116",
            })
    add_cross(landmarks, "roof_cross", "roof_medical_panel", "up", (0.5, 0.5), 10)
    add_cross(landmarks, "rear_cross", "rear_service_panel", "north", (0.5, 0.5), 7)
    for index, x in enumerate((0.28, 0.42, 0.58, 0.72)):
        landmarks.append({
            "name": f"front_grille_slit_{index + 1}",
            "cube": "front_grille",
            "face": "south",
            "center_uv": [x, 0.5],
            "size": [1, 5],
            "color": "#778690",
            "center_color": "#c0c9ca",
        })

    feature_inventory = {
        "central_fuselage_cuboids": len(central),
        "left_side_pod_cuboids": len(pod_feature_names["left"]),
        "right_side_pod_cuboids": len(pod_feature_names["right"]),
        "landing_gear_modules": len(gear_records),
        "landing_gear_cuboids": sum("_gear_" in cube["name"] for cube in builder.cubes),
        "rear_thruster_cuboids": sum("rear_thruster_" in cube["name"] for cube in builder.cubes),
        "roof_aerials": sum(cube["name"].startswith("antenna_") for cube in builder.cubes),
        "medical_marking_strokes": sum("cross" in mark["name"] for mark in landmarks),
        "under_nose_weapon_barrels": sum("nose_weapon_barrel" in cube["name"] for cube in builder.cubes),
        "under_nose_weapon_muzzles": sum("nose_weapon_muzzle" in cube["name"] for cube in builder.cubes),
        "rear_pod_louvers": sum("rear_pod_louver" in cube["name"] for cube in builder.cubes),
        "ventral_machinery_cuboids": sum(cube["name"].startswith("ventral_") for cube in builder.cubes),
        "side_detail_cuboids": sum(
            cube["name"].startswith(("left_", "right_")) for cube in builder.cubes
        ),
    }

    spec = {
        "schema_version": 1,
        "id": "atlus_trauma_team_aerodyne",
        "reference": {
            "image": Path(
                os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())
            ).as_posix(),
            "sha256": EXPECTED_SHA256,
            "width": 712,
            "height": 340,
        },
        "subject": {
            "type": "vehicle",
            "description": "White and teal Trauma Team Atlus armored aerodyne",
            "symmetry": "bilateral",
            "uncertainties": [
                "Only one three-quarter reference image was supplied.",
                "The exact rear thruster layout and underside are conservatively inferred.",
                "The hidden opposite-side graphics mirror the observed side.",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [140, 170],
            "identity_features": [
                "low broad white armored fuselage with a faceted prow",
                "paired full-depth teal side nacelles and white Trauma Team doors",
                "red medical crosses and bounded emergency markings",
                "four modeled landing modules and a detailed underside",
                "rear cyan drive cores, roof beacons, sensors, and aerials",
            ],
            "required_views": [
                "front", "back", "left", "right", "top", "isometric",
                "reference-angle", "underside", "side-pod-closeup", "rear-closeup",
                "underside-closeup",
            ],
            "review_targets": [
                "three-axis volume", "front-to-back silhouette", "side-pod depth",
                "opposite-side completeness", "rear machinery", "underside articulation",
                "clean Minecraft palette",
            ],
        },
        "geometry": {"precision": 32},
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
        "collision": {"width": 4.5, "height": 2.5, "eye_height": 1.8},
        "generation": {
            "lane": "agent-authored-holistic-semantic-volume",
            "algorithm": "multi-axis-hard-surface-vehicle-v1",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "texture_contract": {
                "name": "bounded-trauma-team-minecraft-panels",
                "procedural_noise": False,
                "all_material_patterns_solid": True,
                "source_pixels_embedded_verbatim": False,
                "palette_roles": ["white", "gray", "teal", "red", "dark machinery", "cyan light"],
            },
            "anatomical_axis": "+Z nose, -Z rear, X width, Y up",
            "single_view_hidden_geometry": (
                "Five official exterior views constrain front, side, rear, and roof shape. "
                "The inaccessible underside interior remains a conservative bilateral "
                "hard-surface inference rather than claimed source-observed truth."
            ),
            "geometry_references": [
                {
                    "view": view,
                    "image": f"round3-inputs/atlus-multiview/{view}.webp",
                    "sha256": digest,
                    "width": 1920,
                    "height": 1080,
                    "use": "geometry-and-marking-evidence-only",
                }
                for view, digest in MULTIVIEW_REFERENCES.items()
            ],
            "feature_inventory": feature_inventory,
            "side_pod_feature_names": pod_feature_names,
            "landing_gear": gear_records,
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(stretch(joint))}
                for first, second, joint in attachments
            ],
        },
    }
    CYCLE.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
