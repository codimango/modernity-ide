#!/usr/bin/env python3
"""Author the reviewed semantic hybrid Nian model specification."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "benchmarks" / "references" / "04-nian.jpg"
MASK = Path(__file__).resolve().parent / "inputs" / "foreground-mask.png"
OUTPUT = Path(__file__).resolve().parent / "model-spec.json"
EXPECTED_SHA256 = "644faf9b0d58763d91daa70a6819c269451fa0e021852356556453758fc23d99"


def material(base: str, shade: str, highlight: str, pattern: str = "dither") -> dict[str, Any]:
    """Create one deterministic pixel material."""
    return {
        "base": base,
        "shade": shade,
        "highlight": highlight,
        "pattern": pattern,
        "pattern_scale": 2,
    }


def region(left: int, top: int, right: int, bottom: int) -> list[float]:
    """Convert source-pixel bounds to normalized texture coordinates."""
    return [left / 640, top / 480, right / 640, bottom / 480]


def motif_source_texture(
    kind: str,
    base: str,
    shade: str,
    highlight: str,
) -> dict[str, Any]:
    """Create one deterministic, opaque pixel-art identity motif."""
    dimensions = {
        "spiral": (10, 14),
        "flame": (13, 22),
    }
    if kind not in dimensions:
        raise ValueError(f"unknown motif texture: {kind}")
    width, height = dimensions[kind]

    def rgb(value: str) -> tuple[int, int, int]:
        return (
            int(value[1:3], 16),
            int(value[3:5], 16),
            int(value[5:7], 16),
        )

    base_rgb = rgb(base)
    shade_rgb = rgb(shade)
    highlight_rgb = rgb(highlight)
    image = Image.new("RGBA", (width, height), (*base_rgb, 255))
    for y in range(height):
        ratio = y / (height - 1)
        target = (
            highlight_rgb
            if ratio < 0.35
            else shade_rgb
            if ratio > 0.72
            else base_rgb
        )
        color = tuple(
            round(base_rgb[channel] * 0.65 + target[channel] * 0.35)
            for channel in range(3)
        )
        for x in range(width):
            image.putpixel((x, y), (*color, 255))

    draw = ImageDraw.Draw(image)
    gold = "#d99535"
    cream = "#ffe9a3"
    glint = "#fff8cf"
    if kind == "spiral":
        # This path is authored at the delivered 10x14 face resolution: a
        # continuous C surrounds a burgundy void before curling inward.
        path = [
            (8, 2),
            (5, 1),
            (2, 3),
            (1, 6),
            (2, 10),
            (5, 12),
            (8, 10),
            (8, 7),
            (6, 6),
            (4, 7),
            (4, 9),
            (6, 9),
        ]
        draw.line(path, fill=gold, width=3)
        draw.line(path, fill=cream, width=2)
        draw.point((5, 1), fill=glint)
    elif kind == "flame":
        # One narrow grounded stem opens into three separated upward prongs.
        # Drawing at 13x22 prevents resampling from turning it into parallel
        # vertical bars in the evidence sheet.
        body = [
            (6, 21),
            (5, 18),
            (4, 14),
            (5, 11),
            (7, 10),
            (9, 13),
            (9, 16),
            (8, 19),
            (8, 21),
        ]
        left_prong = [(4, 14), (1, 8), (4, 10), (4, 3), (6, 12)]
        center_prong = [(5, 12), (6, 1), (8, 12)]
        right_prong = [(7, 13), (11, 6), (10, 13)]
        for shape in (body, left_prong, center_prong, right_prong):
            draw.polygon(shape, fill=cream)
        draw.polygon([(6, 19), (6, 14), (7, 11), (8, 14), (7, 19)], fill=gold)
        draw.point((6, 2), fill=glint)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return {
        "data_uri": "data:image/png;base64,"
        + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "repeat": [1, 1],
        "offset": [0, 0],
        "center": [0, 0],
        "rotation": 0,
        "wrap": [1001, 1001],
        "flip_y": True,
    }


def cube(
    name: str,
    bone: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    role: str,
    material_name: str,
    *,
    rotation: tuple[float, float, float] = (0, 0, 0),
    origin: tuple[float, float, float] | None = None,
    photo_region: list[float] | None = None,
) -> dict[str, Any]:
    """Create one semantic cuboid with optional mirrored side treatment."""
    faces: dict[str, Any] = {}
    if photo_region is not None:
        faces["south"] = {
            "material": "reference_photo",
            "source_region": photo_region,
        }
        faces["north"] = {
            "material": "reference_photo",
            "source_region": photo_region,
            "flip_x": True,
        }
    return {
        "name": name,
        "bone": bone,
        "center": list(center),
        "size": list(size),
        "rotation": list(rotation),
        "origin": list(origin or center),
        "role": role,
        "material": material_name,
        "faces": faces,
    }


def main() -> None:
    """Write an anatomy-driven static Nian with connected volumetric parts."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Nian reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (640, 480):
            raise ValueError(f"unexpected Nian reference size: {opened.size}")
    if not MASK.is_file():
        raise ValueError("run prepare-inputs.py before preparing the semantic model")

    materials = {
        "burgundy_fur": material("#9a3f58", "#421d35", "#df7d87", "gradient"),
        "deep_burgundy": material("#74283f", "#351324", "#b85870", "gradient"),
        "gold_mane": material("#f0a62b", "#c65d20", "#ffe064", "stripes"),
        "flame_tip": material("#ffd447", "#e86f22", "#fff08a", "gradient"),
        "green_skin": material("#a9c45b", "#566d32", "#d9df83"),
        "dark_green": material("#526b31", "#29391d", "#879b50"),
        "horn_brown": material("#6c463f", "#382724", "#c39a7d", "stripes"),
        "horn_tip": material("#d9b795", "#725447", "#f5dcc0", "gradient"),
        "cream_marking": material("#f4d68a", "#aa7542", "#fff2b4"),
        "belly_gray": material("#777873", "#454943", "#aaa99b", "gradient"),
        "mouth_red": material("#8f3138", "#43191e", "#d55a58"),
        "tooth_ivory": material("#f2e3ba", "#a99572", "#fff9df"),
        "nose_dark": material("#2c2427", "#100d10", "#5a4848"),
        "claw_ivory": material("#e8d6ad", "#8d765e", "#fff5d2"),
    }

    bones = [
        {"name": "root", "parent": None, "pivot": [0, 0, 0]},
        {"name": "body", "parent": "root", "pivot": [0, 13, 0]},
        {"name": "pelvis", "parent": "body", "pivot": [-7, 13, 0]},
        {"name": "chest", "parent": "body", "pivot": [5, 15, 0]},
        {"name": "neck", "parent": "chest", "pivot": [9, 20, 0]},
        {"name": "head", "parent": "neck", "pivot": [12, 23, 0]},
        {"name": "jaw", "parent": "head", "pivot": [16, 20, 0]},
        {"name": "mane", "parent": "chest", "pivot": [7, 21, 0]},
        {"name": "tail_base", "parent": "pelvis", "pivot": [-14, 14, 0]},
        {"name": "tail_tip", "parent": "tail_base", "pivot": [-17, 14, 0]},
    ]
    for pair_name, parent, pivot in (
        ("rear_near", "pelvis", (-9, 12, 4.2)),
        ("rear_far", "pelvis", (-7, 12, -4.2)),
        ("front_near", "chest", (6, 14, 4.8)),
        ("front_far", "chest", (8, 14, -4.8)),
    ):
        bones.extend(
            [
                {"name": f"{pair_name}_upper", "parent": parent, "pivot": list(pivot)},
                {
                    "name": f"{pair_name}_lower",
                    "parent": f"{pair_name}_upper",
                    "pivot": [pivot[0], 7, pivot[2]],
                },
                {
                    "name": f"{pair_name}_paw",
                    "parent": f"{pair_name}_lower",
                    "pivot": [pivot[0], 2, pivot[2]],
                },
            ]
        )
    for side, sign in (("near", 1), ("far", -1)):
        bones.extend(
            [
                {"name": f"horn_{side}_base", "parent": "head", "pivot": [10.5, 25, sign * 4.8]},
                {"name": f"horn_{side}_mid", "parent": f"horn_{side}_base", "pivot": [12.5, 27, sign * 5.8]},
                {"name": f"horn_{side}_curve", "parent": f"horn_{side}_mid", "pivot": [15.5, 26, sign * 7.0]},
                {"name": f"horn_{side}_return", "parent": f"horn_{side}_curve", "pivot": [17, 23, sign * 6.4]},
                {"name": f"horn_{side}_tip", "parent": f"horn_{side}_return", "pivot": [16, 22, sign * 5.8]},
            ]
        )

    cubes = [
        cube("torso_core", "body", (0, 14, 0), (14, 13, 11), "barrel torso", "burgundy_fur", photo_region=region(225, 140, 390, 365)),
        cube("ribcage", "body", (3.5, 15.5, 0), (10, 14, 12.5), "deep ribcage", "burgundy_fur", photo_region=region(275, 125, 420, 365)),
        cube("pelvis_mass", "pelvis", (-8, 13, 0), (12, 12, 10.5), "rounded pelvis", "burgundy_fur", rotation=(0, 0, -5), photo_region=region(145, 175, 305, 370)),
        cube("belly", "body", (0, 10.5, 0), (13, 6, 10), "gray belly", "belly_gray", photo_region=region(225, 270, 397, 352)),
        cube("shoulder_mass", "chest", (7, 16, 0), (9, 14, 13), "powerful shoulders", "deep_burgundy", rotation=(0, 0, -4), photo_region=region(320, 135, 440, 360)),
        cube("neck_core", "neck", (10, 20, 0), (7, 11, 10), "upright neck", "green_skin", rotation=(0, 0, -10), photo_region=region(365, 110, 455, 320)),
        cube("head_cranium", "head", (13, 24, 0), (8, 8, 9), "green cranium", "green_skin", photo_region=region(390, 115, 500, 245)),
        cube("brow", "head", (16, 23.5, 0), (5, 3, 8), "heavy brow", "dark_green", photo_region=region(425, 155, 500, 215)),
        cube("muzzle", "head", (18, 21.5, 0), (6, 5, 7), "broad muzzle", "green_skin", photo_region=region(435, 180, 510, 270)),
        cube("jaw", "jaw", (17.5, 18.7, 0), (6, 3.5, 6.5), "attached jaw", "green_skin", photo_region=region(425, 220, 505, 290)),
        cube("mouth", "jaw", (20, 19.8, 0), (1.5, 2.3, 5.2), "open red mouth", "mouth_red"),
        cube("nose", "head", (21, 22, 0), (1.8, 2.5, 5.5), "dark nose", "nose_dark"),
        cube("left_ear", "head", (11.5, 25, 4.7), (2, 4, 2.2), "near ear", "green_skin", rotation=(-8, 0, -18)),
        cube("right_ear", "head", (11.5, 25, -4.7), (2, 4, 2.2), "far ear", "green_skin", rotation=(8, 0, -18)),
        cube("mane_back", "mane", (2.5, 22, 0), (9, 13, 14), "rear mane volume", "gold_mane", rotation=(0, 0, -8), photo_region=region(255, 45, 400, 270)),
        cube("mane_shoulder", "mane", (7, 20, 0), (8, 15, 14.5), "shoulder mane volume", "gold_mane", photo_region=region(315, 75, 440, 345)),
        cube("mane_crown", "mane", (9, 28, 0), (8, 4, 10), "crown mane", "flame_tip", rotation=(0, 0, -6), photo_region=region(315, 35, 465, 145)),
        cube("mane_near_cheek", "mane", (11.5, 20, 5.2), (7, 12, 3.5), "near cheek mane", "gold_mane", rotation=(0, 0, -8), photo_region=region(350, 130, 455, 330)),
        cube("mane_far_cheek", "mane", (11.5, 20, -5.2), (7, 12, 3.5), "far cheek mane", "gold_mane", rotation=(0, 0, -8)),
        cube("mane_beard", "mane", (13, 14.8, 0), (7, 10, 10), "mane beard", "gold_mane", rotation=(0, 0, -5), photo_region=region(365, 225, 455, 365)),
        cube("mane_chest", "mane", (8.5, 13.5, 0), (5, 9, 13), "lower chest mane", "gold_mane", rotation=(0, 0, 8), photo_region=region(345, 245, 425, 385)),
        cube("mane_spike_high", "mane", (9, 31, 0), (3, 7, 3.5), "high crown flame", "flame_tip", rotation=(0, 0, 8)),
    ]

    for side, sign, photo in (
        ("near", 1, region(370, 92, 455, 225)),
        ("far", -1, region(425, 75, 575, 190)),
    ):
        cubes.extend(
            [
                cube(f"horn_{side}_base", f"horn_{side}_base", (10.8, 26.5, sign * 5.0), (3.4, 6, 3.4), f"{side} horn base", "horn_brown", rotation=(0, 0, -20), origin=(10.5, 25, sign * 4.8), photo_region=photo if side == "near" else None),
                cube(f"horn_{side}_mid", f"horn_{side}_mid", (13.4, 27.3, sign * 6.1), (6, 3.2, 3.1), f"{side} horn upper outward sweep", "horn_brown", rotation=(0, 0, -12), origin=(12.5, 27, sign * 5.8)),
                cube(f"horn_{side}_curve", f"horn_{side}_curve", (16.2, 25.2, sign * 7.1), (3.2, 6, 2.7), f"{side} horn descending curve", "horn_brown", rotation=(0, 0, 24), origin=(15.5, 26, sign * 7.0)),
                cube(f"horn_{side}_return", f"horn_{side}_return", (16.3, 22.8, sign * 6.5), (4.5, 2.4, 2.3), f"{side} horn lower return", "horn_brown", rotation=(0, 0, -18), origin=(17, 23, sign * 6.4)),
                cube(f"horn_{side}_tip", f"horn_{side}_tip", (18, 22.8, sign * 6.4), (3.8, 2.2, 2.1), f"{side} horn inward ivory tip", "horn_tip", rotation=(0, 0, -28), origin=(17, 23, sign * 6.4)),
            ]
        )

    leg_data = (
        ("rear_near", (-9, 9, 4.2), (-10.5, 4.5, 4.2), (-10, 1.2, 4.5), -12, region(140, 255, 235, 397)),
        ("rear_far", (-6.5, 9, -4.2), (-5.5, 4.6, -4.2), (-4.5, 1.2, -4.5), 10, region(205, 270, 295, 380)),
        ("front_near", (5.5, 9, 4.8), (6.8, 4.3, 4.8), (8, 1.2, 5.0), -4, region(265, 205, 365, 450)),
        ("front_far", (8, 9, -4.8), (9, 4.5, -4.8), (10, 1.2, -5.0), 5, region(375, 210, 470, 408)),
    )
    for name, upper, lower, paw, angle, photo in leg_data:
        parent = "pelvis" if name.startswith("rear") else "chest"
        base_material = "burgundy_fur" if name.startswith("rear") else "deep_burgundy"
        cubes.extend(
            [
                cube(f"{name}_upper", f"{name}_upper", upper, (5.5, 10, 5.5), f"{name} upper leg", base_material, rotation=(0, 0, angle), origin=tuple(next(bone["pivot"] for bone in bones if bone["name"] == f"{name}_upper")), photo_region=photo if name.endswith("near") else None),
                cube(f"{name}_lower", f"{name}_lower", lower, (4.5, 7, 4.8), f"{name} lower leg", base_material, rotation=(0, 0, -angle / 2), origin=tuple(next(bone["pivot"] for bone in bones if bone["name"] == f"{name}_lower")), photo_region=photo if name.endswith("near") else None),
                cube(f"{name}_paw", f"{name}_paw", paw, (7, 2.4, 6.2), f"{name} attached paw", base_material, origin=tuple(next(bone["pivot"] for bone in bones if bone["name"] == f"{name}_paw")), photo_region=photo if name.endswith("near") else None),
            ]
        )

    for leg, x, z in (
        ("rear_near", -7.6, 4.5),
        ("rear_far", -2.1, -4.5),
        ("front_near", 10.4, 5.0),
        ("front_far", 12.4, -5.0),
    ):
        for claw_index, offset_z in enumerate((-1.4, 1.4), start=1):
            cubes.append(
                cube(
                    f"{leg}_claw_{claw_index}",
                    f"{leg}_paw",
                    (x, 0.9, z + offset_z),
                    (2.4, 1.2, 1.1),
                    f"{leg} claw",
                    "claw_ivory",
                    rotation=(0, 0, -8),
                )
            )

    cubes.extend(
        [
            cube("tail_base", "tail_base", (-14.5, 14, 0), (6, 5, 6), "attached tail base", "burgundy_fur", rotation=(0, 0, -12), origin=(-14, 14, 0), photo_region=region(135, 215, 215, 315)),
            cube("tail_mid", "tail_base", (-17.5, 14.8, 0), (5, 4, 4.5), "short tail middle", "burgundy_fur", rotation=(0, 0, -16), origin=(-16, 14, 0)),
            cube("tail_tip", "tail_tip", (-20, 15.5, 0), (3.5, 3, 3.5), "gold tail tip", "flame_tip", rotation=(0, 0, -20), origin=(-18, 15, 0)),
            cube("upper_left_fang", "head", (19.6, 19.8, 1.8), (1.2, 3.2, 1.1), "upper near fang", "tooth_ivory", rotation=(0, 0, 8)),
            cube("upper_right_fang", "head", (19.6, 19.8, -1.8), (1.2, 3.2, 1.1), "upper far fang", "tooth_ivory", rotation=(0, 0, 8)),
        ]
    )

    landmarks = [
        {"name": "near_eye", "cube": "head_cranium", "face": "south", "center_uv": [0.72, 0.45], "size": [3, 3], "color": "#171215", "center_color": "#f2d35b"},
        {"name": "far_eye", "cube": "head_cranium", "face": "north", "center_uv": [0.28, 0.45], "size": [3, 3], "color": "#171215", "center_color": "#f2d35b"},
        {"name": "near_nostril", "cube": "nose", "face": "south", "center_uv": [0.65, 0.5], "size": [2, 1], "color": "#09080a", "center_color": "#352429"},
        {"name": "far_nostril", "cube": "nose", "face": "north", "center_uv": [0.35, 0.5], "size": [2, 1], "color": "#09080a", "center_color": "#352429"},
    ]

    # Authoring coordinates place the animal along +X for easy comparison with
    # the source profile. Rotate the finished anatomy rigidly so the delivered
    # model follows the compiler contract: +Z is the nose/front and X is width.
    face_rotation = {
        "north": "east",
        "east": "south",
        "south": "west",
        "west": "north",
        "up": "up",
        "down": "down",
    }
    for bone in bones:
        x, y, z = bone["pivot"]
        bone["pivot"] = [-z, y, x]
    for model_cube in cubes:
        x, y, z = model_cube["center"]
        size_x, size_y, size_z = model_cube["size"]
        rotation_x, rotation_y, rotation_z = model_cube["rotation"]
        origin_x, origin_y, origin_z = model_cube["origin"]
        model_cube["center"] = [-z, y, x]
        model_cube["size"] = [size_z, size_y, size_x]
        model_cube["rotation"] = [-rotation_z, rotation_y, rotation_x]
        model_cube["origin"] = [-origin_z, origin_y, origin_x]
        model_cube["faces"] = {
            face_rotation[face]: value for face, value in model_cube["faces"].items()
        }
    for landmark in landmarks:
        landmark["face"] = face_rotation[landmark["face"]]

    cube_by_name = {model_cube["name"]: model_cube for model_cube in cubes}
    bone_by_name = {bone["name"]: bone for bone in bones}

    def revise(
        name: str,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        rotation: tuple[float, float, float] = (0, 0, 0),
        origin: tuple[float, float, float] | None = None,
    ) -> None:
        """Apply a reviewed delivered-coordinate anatomy correction."""
        model_cube = cube_by_name[name]
        model_cube["center"] = list(center)
        model_cube["size"] = list(size)
        model_cube["rotation"] = list(rotation)
        model_cube["origin"] = list(origin or center)

    # The trunk is a short rising wedge: a low narrow rump feeds a deeper
    # ribcage and a much taller/wider shoulder instead of one level barrel.
    revise("torso_core", (0, 14.9, 0.8), (9, 9, 5.4), (-22, 0, 0))
    revise("ribcage", (0, 18.0, 4.4), (11.5, 12.5, 5), (-28, 0, 0))
    revise("pelvis_mass", (0, 12.0, -3.0), (7.5, 7, 4.8), (-26, 0, 0))
    revise("belly", (0, 11.4, 1.3), (8, 4, 5), (-16, 0, 0))
    revise("shoulder_mass", (0, 20.8, 8.1), (15.5, 17, 6), (-28, 0, 0))
    revise("neck_core", (0, 22.0, 11.5), (10.5, 7.5, 5.5), (-16, 0, 0))
    cube_by_name["pelvis_mass"]["material"] = "deep_burgundy"
    cube_by_name["shoulder_mass"]["material"] = "burgundy_fur"

    # A compact cranium, wide brow, paired jowls, and short projected muzzle
    # break the face into readable planes without losing its dominant snarl.
    revise("head_cranium", (0, 24.2, 14.5), (6.8, 5.8, 6), (-10, 0, 0))
    revise("brow", (0, 25.1, 18.0), (8.2, 2.6, 2.8), (-12, 0, 0))
    revise("muzzle", (0, 22.1, 19.5), (5.3, 3, 2.8), (-14, 0, 0))
    revise("jaw", (0, 20.5, 19.2), (5, 2.8, 3.2), (-8, 0, 0))

    # Stepped, sloped volumes form a crown, shoulder flames, cheek ruffs, and
    # a tapered beard. Their thin axes prevent a hat-like slab.
    revise("mane_back", (0, 25.0, 5.5), (9, 5.2, 4.2), (22, 0, 0))
    revise("mane_shoulder", (0, 22.2, 9.0), (10.8, 6.2, 4.5), (-18, 0, 0))
    revise("mane_crown", (0, 28.3, 11.0), (8, 4.4, 4), (-18, 0, 0))
    revise("mane_near_cheek", (-6.1, 21.0, 15.0), (2.8, 7.2, 3.6), (-24, 0, -28))
    revise("mane_far_cheek", (6.1, 21.0, 15.0), (2.8, 7.2, 3.6), (-24, 0, 28))
    revise("mane_beard", (0, 15.8, 16.2), (5.4, 5.2, 2.8), (-28, 0, 0))
    revise("mane_chest", (0, 14.0, 13.0), (7.2, 5.2, 3.6), (-30, 0, 0))
    revise("mane_spike_high", (0, 31.0, 9.5), (5, 5, 4), (-24, 0, 0))
    for mane_name in (
        "mane_back",
        "mane_shoulder",
        "mane_crown",
        "mane_near_cheek",
        "mane_far_cheek",
        "mane_beard",
        "mane_chest",
        "mane_spike_high",
    ):
        if mane_name != "mane_near_cheek":
            cube_by_name[mane_name]["faces"] = {}
    cube_by_name["mane_near_cheek"]["material"] = "flame_tip"
    cube_by_name["mane_far_cheek"]["material"] = "flame_tip"

    cubes.extend(
        [
            {
                "name": "mane_crown_near_flame",
                "bone": "mane",
                "center": [-3.2, 29.5, 10.0],
                "size": [2.5, 4.5, 2.7],
                "rotation": [12, 0, -20],
                "origin": [-3.2, 28.2, 10.0],
                "role": "near crown flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_crown_far_flame",
                "bone": "mane",
                "center": [3.2, 29.5, 10.0],
                "size": [2.5, 4.5, 2.7],
                "rotation": [12, 0, 20],
                "origin": [3.2, 28.2, 10.0],
                "role": "far crown flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_rear_flame",
                "bone": "mane",
                "center": [0, 27, 4.5],
                "size": [3.6, 4.5, 2.7],
                "rotation": [18, 0, 0],
                "origin": [0, 25.8, 5],
                "role": "rear mane flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_beard_tip",
                "bone": "mane",
                "center": [0, 12.5, 16.2],
                "size": [2.7, 4, 2.3],
                "rotation": [-18, 0, 0],
                "origin": [0, 13.8, 15.8],
                "role": "lower beard flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_near_rear_tuft",
                "bone": "mane",
                "center": [-6.7, 24.8, 6],
                "size": [2.7, 6.2, 3.2],
                "rotation": [25, 0, -24],
                "origin": [-6.1, 22.8, 6.5],
                "role": "near swept rear mane tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_far_rear_tuft",
                "bone": "mane",
                "center": [6.7, 24.8, 6],
                "size": [2.7, 6.2, 3.2],
                "rotation": [25, 0, 24],
                "origin": [6.1, 22.8, 6.5],
                "role": "far swept rear mane tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_near_lower_tuft",
                "bone": "mane",
                "center": [-6.3, 17.0, 15.2],
                "size": [2.7, 5.4, 2.7],
                "rotation": [-30, 0, -20],
                "origin": [-5.7, 18.8, 14.5],
                "role": "near lower mane tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_far_lower_tuft",
                "bone": "mane",
                "center": [6.3, 17.0, 15.2],
                "size": [2.7, 5.4, 2.7],
                "rotation": [-30, 0, 20],
                "origin": [5.7, 18.8, 14.5],
                "role": "far lower mane tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_near_crown_tuft",
                "bone": "mane",
                "center": [-3.6, 27.5, 7.0],
                "size": [2.7, 5, 2.7],
                "rotation": [18, 0, -18],
                "origin": [-3.6, 26.2, 7.5],
                "role": "near rear crown tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_far_crown_tuft",
                "bone": "mane",
                "center": [3.6, 27.5, 7.0],
                "size": [2.7, 5, 2.7],
                "rotation": [18, 0, 18],
                "origin": [3.6, 26.2, 7.5],
                "role": "far rear crown tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_near_shoulder_flame",
                "bone": "mane",
                "center": [-7.4, 22.3, 11.5],
                "size": [2.7, 7.2, 3.6],
                "rotation": [28, 0, -26],
                "origin": [-6.6, 20.2, 10.5],
                "role": "near shoulder flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_far_shoulder_flame",
                "bone": "mane",
                "center": [7.4, 22.3, 11.5],
                "size": [2.7, 7.2, 3.6],
                "rotation": [28, 0, 26],
                "origin": [6.6, 20.2, 10.5],
                "role": "far shoulder flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_near_chest_flame",
                "bone": "mane",
                "center": [-6.7, 14.5, 14.0],
                "size": [2.7, 5.4, 3.2],
                "rotation": [-30, 0, -24],
                "origin": [-5.9, 16.2, 13.5],
                "role": "near chest flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
            {
                "name": "mane_far_chest_flame",
                "bone": "mane",
                "center": [6.7, 14.5, 14.0],
                "size": [2.7, 5.4, 3.2],
                "rotation": [-30, 0, 24],
                "origin": [5.9, 16.2, 13.5],
                "role": "far chest flame tuft",
                "material": "flame_tip",
                "faces": {},
            },
        ]
    )

    cubes.extend(
        [
            {
                "name": "shoulder_near_cap",
                "bone": "chest",
                "center": [-5.2, 19.0, 7.8],
                "size": [6.2, 10.5, 6.5],
                "rotation": [-20, 0, -10],
                "origin": [-5.2, 19.0, 7.8],
                "role": "massive near shoulder cap",
                "material": "burgundy_fur",
                "faces": {},
            },
            {
                "name": "shoulder_far_cap",
                "bone": "chest",
                "center": [5.2, 19.0, 7.8],
                "size": [6.2, 10.5, 6.5],
                "rotation": [-20, 0, 10],
                "origin": [5.2, 19.0, 7.8],
                "role": "massive far shoulder cap",
                "material": "burgundy_fur",
                "faces": {},
            },
            {
                "name": "green_near_cheek",
                "bone": "head",
                "center": [-3.0, 21.8, 19.3],
                "size": [2.2, 4, 2.8],
                "rotation": [-10, 0, -10],
                "origin": [-3.0, 22.3, 18.5],
                "role": "near sculpted green cheek",
                "material": "green_skin",
                "faces": {},
            },
            {
                "name": "green_far_cheek",
                "bone": "head",
                "center": [3.0, 21.8, 19.3],
                "size": [2.2, 4, 2.8],
                "rotation": [-10, 0, 10],
                "origin": [3.0, 22.3, 18.5],
                "role": "far sculpted green cheek",
                "material": "green_skin",
                "faces": {},
            },
            {
                "name": "lower_left_fang",
                "bone": "jaw",
                "center": [-1.2, 19.8, 20.8],
                "size": [0.8, 1.8, 0.8],
                "rotation": [0, 0, 5],
                "origin": [-1.2, 20.3, 20.5],
                "role": "lower near fang",
                "material": "tooth_ivory",
                "faces": {},
            },
            {
                "name": "lower_right_fang",
                "bone": "jaw",
                "center": [1.2, 19.8, 20.8],
                "size": [0.8, 1.8, 0.8],
                "rotation": [0, 0, -5],
                "origin": [1.2, 20.3, 20.5],
                "role": "lower far fang",
                "material": "tooth_ivory",
                "faces": {},
            },
        ]
    )

    for side, sign in (("near", -1), ("far", 1)):
        # Five overlapping, steadily tapered segments follow one continuous C
        # from the skull, around a deliberately open aperture, and back to an
        # ivory point beside the cheek.  Each cuboid is centered on its own
        # rotation origin so its authored endpoints remain connected.
        bone_by_name[f"horn_{side}_base"]["pivot"] = [sign * 4.5, 27.0, 14.0]
        bone_by_name[f"horn_{side}_mid"]["pivot"] = [sign * 7.0, 30.0, 14.0]
        bone_by_name[f"horn_{side}_curve"]["pivot"] = [sign * 10.8, 30.0, 15.5]
        bone_by_name[f"horn_{side}_return"]["pivot"] = [sign * 11.3, 28.0, 18.5]
        bone_by_name[f"horn_{side}_tip"]["pivot"] = [sign * 10.8, 27.5, 20.8]
        revise(
            f"horn_{side}_base",
            (sign * 5.75, 28.5, 14.0),
            (3.7, 4.4, 3.7),
            (0, 0, -sign * 39.8),
            (sign * 5.75, 28.5, 14.0),
        )
        revise(
            f"horn_{side}_mid",
            (sign * 8.9, 30.0, 14.75),
            (3.0, 4.6, 3.0),
            (21.5, 0, -sign * 90.0),
            (sign * 8.9, 30.0, 14.75),
        )
        revise(
            f"horn_{side}_curve",
            (sign * 11.05, 29.0, 17.0),
            (2.3, 4.1, 2.3),
            (55.5, 0, -sign * 166.0),
            (sign * 11.05, 29.0, 17.0),
        )
        revise(
            f"horn_{side}_return",
            (sign * 11.05, 27.75, 19.65),
            (1.7, 2.9, 1.7),
            (72.9, 0, sign * 135.0),
            (sign * 11.05, 27.75, 19.65),
        )
        revise(
            f"horn_{side}_tip",
            (sign * 10.3, 28.35, 22.15),
            (1.1, 3.8, 1.1),
            (53.9, 0, sign * 30.5),
            (sign * 10.3, 28.35, 22.15),
        )
        for segment_name in ("base", "mid", "curve", "return"):
            cube_by_name[f"horn_{side}_{segment_name}"]["material"] = "horn_brown"

    revise("nose", (0, 23.0, 21.0), (3.8, 1.8, 0.9), (-14, 0, 0))
    revise("mouth", (0, 20.6, 20.9), (4.6, 2.2, 0.7), (-8, 0, 0))
    revise("upper_left_fang", (-1.5, 20.5, 21.1), (1.0, 2.8, 0.8), (0, 0, -6))
    revise("upper_right_fang", (1.5, 20.5, 21.1), (1.0, 2.8, 0.8), (0, 0, 6))

    revise("tail_base", (0, 13.5, -6.2), (3.2, 3, 3), (22, 0, 0), (0, 13.0, -5.4))
    revise("tail_mid", (0.2, 14.2, -7.5), (2.5, 2.3, 2.5), (26, -8, 0), (0, 13.7, -6.7))
    revise("tail_tip", (0.4, 14.7, -8.5), (2, 2, 2), (20, -10, 0), (0.2, 14.4, -7.7))
    bone_by_name["tail_base"]["pivot"] = [0, 13.0, -5.4]
    bone_by_name["tail_tip"]["pivot"] = [0.2, 14.4, -7.7]

    leg_revisions = {
        "rear_near": {
            "x": -3.6,
            "centers": ((-3.6, 10.3, -4.8), (-3.6, 5.1, -5.8), (-3.6, 1.25, -4.6)),
            "pivots": ((-3.6, 13.8, -4.0), (-3.6, 7.3, -5.8), (-3.6, 2.4, -5.0)),
            "rotations": ((28, 0, 0), (-35, 0, 0), (0, 0, 0)),
        },
        "rear_far": {
            "x": 3.6,
            "centers": ((3.6, 10.3, -2.6), (3.6, 5.1, -3.6), (3.6, 1.25, -2.4)),
            "pivots": ((3.6, 13.8, -2.0), (3.6, 7.3, -3.6), (3.6, 2.4, -2.8)),
            "rotations": ((28, 0, 0), (-35, 0, 0), (0, 0, 0)),
        },
        "front_near": {
            "x": -4.4,
            "centers": ((-4.5, 15.3, 9.5), (-4.3, 8.4, 8.8), (-4.1, 3.0, 6.0)),
            "pivots": ((-4.5, 20.0, 8.0), (-4.6, 11.8, 10.2), (-4.2, 5.0, 7.8)),
            "rotations": ((-10, 0, -2), (8, 0, 3), (-12, 0, -2)),
        },
        "front_far": {
            "x": 4.4,
            "centers": ((4.5, 15.3, 10.5), (4.3, 8.4, 11.0), (4.1, 3.0, 12.5)),
            "pivots": ((4.5, 20.0, 9.0), (4.6, 11.8, 11.0), (4.2, 5.0, 11.8)),
            "rotations": ((-10, 0, 2), (8, 0, -3), (-12, 0, 2)),
        },
    }
    for name, values in leg_revisions.items():
        upper_pivot, lower_pivot, paw_pivot = values["pivots"]
        bone_by_name[f"{name}_upper"]["pivot"] = list(upper_pivot)
        bone_by_name[f"{name}_lower"]["pivot"] = list(lower_pivot)
        bone_by_name[f"{name}_paw"]["pivot"] = list(paw_pivot)
        is_front = name.startswith("front")
        sizes = (
            (6.8, 11, 6.5) if is_front else (3.8, 6.5, 3.6),
            (5.7, 8.5, 5.5) if is_front else (3.2, 5.8, 3.2),
            (6.5, 4.8, 3.2) if is_front else (3.6, 2.5, 3),
        )
        for segment, center, size, rotation, pivot in zip(
            ("upper", "lower", "paw"),
            values["centers"],
            sizes,
            values["rotations"],
            values["pivots"],
        ):
            revise(f"{name}_{segment}", center, size, rotation, center)

    paw_centers = {
        "rear_near": (-3.6, -5.5),
        "rear_far": (3.6, -3.3),
        "front_near": (-4.1, 5.5),
        "front_far": (4.1, 10.7),
    }
    for leg_name, (center_x, center_z) in paw_centers.items():
        claw_offsets = (-1.25, 1.25) if leg_name.startswith("front") else (-0.9, 0.9)
        for claw_index, offset_x in enumerate(claw_offsets, start=1):
            claw_size = (
                (1.0, 1.1, 1.6)
                if leg_name.startswith("front")
                else (0.8, 1.0, 1.4)
            )
            revise(
                f"{leg_name}_claw_{claw_index}",
                (center_x + offset_x, 0.65, center_z + 2.7),
                claw_size,
                (0, 0, -8),
            )

    cubes.extend(
        [
            {
                "name": "front_near_paw_pad",
                "bone": "front_near_paw",
                "center": [-4.1, 0.7, 7.4],
                "size": [5.8, 1.4, 1.8],
                "rotation": [0, -5, 0],
                "origin": [-4.1, 0.7, 7.4],
                "role": "near front paw pad",
                "material": "deep_burgundy",
                "faces": {},
            },
            {
                "name": "front_far_paw_pad",
                "bone": "front_far_paw",
                "center": [4.1, 0.7, 13.9],
                "size": [5.8, 1.4, 1.8],
                "rotation": [0, 5, 0],
                "origin": [4.1, 0.7, 13.9],
                "role": "far front paw pad",
                "material": "deep_burgundy",
                "faces": {},
            },
            {
                "name": "rump_spiral_decal",
                "bone": "body",
                "center": [-4.56, 14.9, 0.8],
                "size": [0.1, 7.0, 4.6],
                "rotation": [-22, 0, 0],
                "origin": [-4.56, 14.9, 0.8],
                "role": "flush near-rump pixel texture decal",
                "material": "burgundy_fur",
                "faces": {},
            },
        ]
    )

    # The rejected contour pass mixed photographic fragments with flat sides.
    # Keep the source-derived palette and paint identity marks directly into
    # actual semantic faces instead of retaining photo billboards or relief.
    for model_cube in cubes:
        model_cube["faces"] = {
            face: override
            for face, override in model_cube.get("faces", {}).items()
            if "source_region" not in override
        }

    cube_by_name = {model_cube["name"]: model_cube for model_cube in cubes}
    motif_faces = {
        "rump_spiral_decal": motif_source_texture(
            "spiral", "#9a3f58", "#421d35", "#df7d87"
        ),
        "front_near_upper": motif_source_texture(
            "flame", "#74283f", "#351324", "#b85870"
        ),
    }
    for cube_name, source_texture in motif_faces.items():
        cube_by_name[cube_name]["faces"]["west"] = {
            "source_texture": source_texture,
        }

    landmarks.extend(
        [
            {"name": "front_left_eye", "cube": "brow", "face": "south", "center_uv": [0.28, 0.55], "size": [3, 2], "color": "#171215", "center_color": "#f2d35b"},
            {"name": "front_right_eye", "cube": "brow", "face": "south", "center_uv": [0.72, 0.55], "size": [3, 2], "color": "#171215", "center_color": "#f2d35b"},
            {"name": "front_left_nostril", "cube": "nose", "face": "south", "center_uv": [0.32, 0.5], "size": [1, 1], "color": "#09080a", "center_color": "#09080a"},
            {"name": "front_right_nostril", "cube": "nose", "face": "south", "center_uv": [0.68, 0.5], "size": [1, 1], "color": "#09080a", "center_color": "#09080a"},
            {"name": "mouth_center", "cube": "mouth", "face": "south", "center_uv": [0.5, 0.5], "size": [5, 2], "color": "#241319", "center_color": "#6e202b"},
        ]
    )
    for side, face in (("near", "west"), ("far", "east")):
        for segment_name in ("mid", "curve", "return"):
            landmarks.append(
                {
                    "name": f"horn_{side}_{segment_name}_cream_band",
                    "cube": f"horn_{side}_{segment_name}",
                    "face": face,
                    "center_uv": [0.52, 0.5],
                    "size": [2, 2],
                    "color": "#c99a72",
                    "center_color": "#f0d5ac",
                }
            )
    landmarks.extend(
        [
            {"name": "near_angry_brow", "cube": "brow", "face": "west", "center_uv": [0.58, 0.48], "size": [4, 1], "color": "#26321b", "center_color": "#13180f"},
            {"name": "far_angry_brow", "cube": "brow", "face": "east", "center_uv": [0.42, 0.48], "size": [4, 1], "color": "#26321b", "center_color": "#13180f"},
            {"name": "near_cheek_shadow", "cube": "green_near_cheek", "face": "west", "center_uv": [0.5, 0.62], "size": [2, 3], "color": "#526b31", "center_color": "#29391d"},
            {"name": "far_cheek_shadow", "cube": "green_far_cheek", "face": "east", "center_uv": [0.5, 0.62], "size": [2, 3], "color": "#526b31", "center_color": "#29391d"}
        ]
    )

    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    spec = {
        "schema_version": 1,
        "id": "nian_beast",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 640,
            "height": 480,
        },
        "subject": {
            "type": "mob",
            "description": "Agent-authored volumetric Nian with golden mane, ram horns, fanged green face, spiral-marked burgundy body, and four grounded legs",
            "symmetry": "bilateral",
            "uncertainties": [
                "The single source view does not reveal exact far-side markings",
                "The proprietary source-page .max mesh was not used",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [75, 85],
            "identity_features": [
                "paired curled ram horns",
                "golden flame mane and beard",
                "green fanged face",
                "cream spiral flank markings",
                "four attached heavy legs and paws",
            ],
            "required_views": ["reference-angle", "front", "back", "left", "right", "top-profile", "isometric", "head-closeups", "joint-closeup"],
            "review_targets": ["silhouette", "anatomical volume", "limb attachment", "horn attachment", "mane volume", "texture continuity"],
        },
        "geometry": {"precision": 16},
        "texture": {
            "density": 2,
            "palette_size": 32,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": True,
        },
        "materials": materials,
        "bones": bones,
        "cubes": cubes,
        "landmarks": landmarks,
        "collision": {"width": 1.05, "height": 2.05, "eye_height": 1.62},
        "generation": {
            "lane": "agent-authored-semantic-hybrid",
            "algorithm": "reviewed-semantic-volume-with-flush-pixel-motifs-v8",
            "source_mesh": None,
            "source_mesh_reason": "CADNav offers proprietary non-commercial .max only; no GLB/GLTF was used",
            "anatomical_axis": "head along positive Z; bilateral width along X; Y up",
            "source_view": "near side viewed primarily from negative X",
            "reference_view_direction": [-1.0, 0.32, 0.60],
            "semantic_parts": {
                "body_volumes": 8,
                "head_and_face": 10,
                "fangs": 4,
                "mane_volumes": 22,
                "horn_segments": 10,
                "limb_chains": 4,
                "limb_segments_per_chain": 3,
                "attached_claws": 8,
                "front_paw_pads": 2,
                "surface_decal_cuboids": 1,
                "pixel_motif_faces": 2,
                "tail_segments": 3,
            },
            "source_facing_texture": {
                "method": "source-derived procedural palette with flush embedded pixel motifs",
                "opaque_hidden_sides": True,
                "semantic_side_regions_mirrored": False,
                "bilateral_landmarks": True,
                "flush_motif_faces": [
                    "rump_spiral_decal/west",
                    "front_near_upper/west"
                ],
                "silhouette_skin_cuboids": 0,
                "mask_sha256": hashlib.sha256(MASK.read_bytes()).hexdigest(),
            },
        },
    }
    OUTPUT.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
