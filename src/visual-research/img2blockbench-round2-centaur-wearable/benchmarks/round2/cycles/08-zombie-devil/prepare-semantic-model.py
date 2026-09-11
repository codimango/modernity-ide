#!/usr/bin/env python3
"""Author the Round 2 Zombie Devil as a deep, non-biped semantic volume."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from semantic_geometry import (
    EllipsoidCutout,
    EllipsoidResult,
    SemanticModelBuilder,
    ellipsoid_cuboids,
    point_to_cuboid_margin,
    segment_cube,
)


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "image-11.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "e3c594bc2fc60a63fa7f510fd6557e761219b731be2654a599fc751d024c96df"
REAR_DEPTH_ADDITIONS = {
    "torso_core": 12.0,
    "left_arm_mass": 10.0,
    "left_fist_volume": 10.0,
    "right_arm_upper_mass": 10.0,
    "right_forearm_mass": 10.0,
    "right_fist_volume": 10.0,
    "face_volume": 8.0,
    "jaw_mass": 8.0,
    "mouth_cavity": 6.0,
    "left_bulging_eye": 3.0,
    "right_bulging_eye": 3.0,
    "brain_neck_mass": 8.0,
    "brain_volume": 8.0,
    "visceral_bridge": 10.0,
    "organ_bulge_left_upper": 6.0,
    "organ_bulge_left_lower": 6.0,
    "organ_bulge_right_upper": 6.0,
    "organ_bulge_right_lower": 6.0,
}


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
    center: Sequence[float],
    size: Sequence[float],
    role: str,
    material_name: str,
    *,
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    origin: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Create one named semantic cuboid."""
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


def cube_bounds(cube: dict[str, Any]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return bounds for an axis-aligned volume cuboid."""
    if any(abs(float(value)) > 1e-9 for value in cube["rotation"]):
        raise ValueError(f"{cube['name']} is not axis aligned")
    center = tuple(float(value) for value in cube["center"])
    size = tuple(float(value) for value in cube["size"])
    return (
        tuple(center[axis] - size[axis] / 2 for axis in range(3)),
        tuple(center[axis] + size[axis] / 2 for axis in range(3)),
    )


def axis_aligned_spanning_links(
    cubes: Sequence[dict[str, Any]],
) -> list[tuple[str, str, tuple[float, float, float]]]:
    """Return a deterministic contact tree over one voxelized volume."""
    bounds = {cube["name"]: cube_bounds(cube) for cube in cubes}
    if not bounds:
        raise ValueError("volume cannot be empty")
    names = sorted(bounds)
    reached = {names[0]}
    pending = set(names[1:])
    links: list[tuple[str, str, tuple[float, float, float]]] = []
    while pending:
        candidate = None
        for first in sorted(reached):
            first_lower, first_upper = bounds[first]
            for second in sorted(pending):
                second_lower, second_upper = bounds[second]
                lower = tuple(max(first_lower[axis], second_lower[axis]) for axis in range(3))
                upper = tuple(min(first_upper[axis], second_upper[axis]) for axis in range(3))
                if all(lower[axis] <= upper[axis] + 1e-6 for axis in range(3)):
                    joint = tuple((lower[axis] + upper[axis]) / 2 for axis in range(3))
                    candidate = first, second, joint
                    break
            if candidate is not None:
                break
        if candidate is None:
            raise ValueError("ellipsoid cuboids are not one connected volume")
        links.append(candidate)
        reached.add(candidate[1])
        pending.remove(candidate[1])
    return links


def add_volume(
    builder: SemanticModelBuilder,
    result: EllipsoidResult,
    attachments: list[tuple[str, str, tuple[float, float, float]]],
) -> list[dict[str, Any]]:
    """Add one ellipsoid and its exact internal contact tree."""
    cubes = list(result.cubes)
    for cube in cubes:
        builder.add_cube(cube)
    attachments.extend(axis_aligned_spanning_links(cubes))
    return cubes


def containing_cube(
    cubes: Sequence[dict[str, Any]], point: Sequence[float]
) -> dict[str, Any]:
    """Return the cuboid containing a semantic joint most deeply."""
    candidates = [
        (point_to_cuboid_margin(cube, point), cube)
        for cube in cubes
        if point_to_cuboid_margin(cube, point) >= -1e-6
    ]
    if not candidates:
        raise ValueError(f"no volume cuboid contains joint {tuple(point)}")
    return max(candidates, key=lambda item: (item[0], item[1]["name"]))[1]


def bridge_volumes(
    first: Sequence[dict[str, Any]], second: Sequence[dict[str, Any]]
) -> tuple[str, str, tuple[float, float, float]]:
    """Choose the broadest physical overlap between two volumes."""
    candidates = []
    for first_cube in first:
        first_lower, first_upper = cube_bounds(first_cube)
        for second_cube in second:
            second_lower, second_upper = cube_bounds(second_cube)
            lower = tuple(max(first_lower[axis], second_lower[axis]) for axis in range(3))
            upper = tuple(min(first_upper[axis], second_upper[axis]) for axis in range(3))
            overlap = tuple(upper[axis] - lower[axis] for axis in range(3))
            if all(value >= -1e-6 for value in overlap):
                joint = tuple((lower[axis] + upper[axis]) / 2 for axis in range(3))
                candidates.append((min(overlap), first_cube["name"], second_cube["name"], joint))
    if not candidates:
        raise ValueError("semantic volumes do not overlap")
    _, first_name, second_name, joint = max(candidates)
    return first_name, second_name, joint


def main() -> None:
    """Rebuild the Devil as one broad organic mass instead of an upright biped."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Zombie Devil reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.mode != "RGB" or opened.size != (513, 754):
            raise ValueError(f"unexpected Zombie Devil reference: {opened.mode} {opened.size}")

    materials = {
        "flesh": material("#d2cec3", "#706e69", "#f5f1e8", "solid", 1),
        "flesh_light": material("#e5e0d5", "#918e87", "#fffdf5", "solid", 1),
        "flesh_shadow": material("#88837c", "#343333", "#bbb5aa", "stripes", 3),
        "fold": material("#484748", "#161619", "#85817b", "solid", 1),
        "wound": material("#762a34", "#1e0a0f", "#b94b55", "gradient", 2),
        "mouth": material("#180d12", "#030203", "#55202a", "solid", 1),
        "tooth": material("#f0e9d5", "#8b8374", "#ffffff", "solid", 1),
        "eye": material("#fff8d8", "#807b6c", "#ffffff", "solid", 1),
        "pupil": material("#141418", "#020203", "#4b4b50", "solid", 1),
        "hair": material("#4b4948", "#171719", "#88837d", "stripes", 2),
        "brain": material("#b97f86", "#59343b", "#e9b6b3", "stripes", 2),
        "brain_groove": material("#5a3039", "#1d1015", "#9a5863", "solid", 1),
        "organ_dark": material("#8d6567", "#3e2c30", "#c0938f", "solid", 1),
        "organ_light": material("#c1a09a", "#69504e", "#e6c7b9", "solid", 1),
        "intestine": material("#a87b77", "#493532", "#d4aaa0", "stripes", 3),
        "intestine_dark": material("#825a5c", "#342427", "#b88984", "solid", 1),
    }
    builder = SemanticModelBuilder()
    for name, parent, pivot in (
        ("torso", "root", (0.0, 43.0, 0.0)),
        ("head", "torso", (-10.0, 48.0, 7.0)),
        ("jaw", "head", (-10.0, 37.0, 8.0)),
        ("left_arm", "torso", (-13.0, 54.0, 0.0)),
        ("right_arm", "torso", (12.0, 46.0, 1.0)),
        ("brain_neck", "torso", (7.0, 53.0, 0.0)),
        ("brain", "brain_neck", (15.0, 66.0, 0.0)),
        ("viscera", "torso", (-1.0, 31.0, 1.0)),
    ):
        builder.add_bone(name, parent, pivot)
    attachments: list[tuple[str, str, tuple[float, float, float]]] = []

    def volume(
        name: str,
        bone: str,
        center: Sequence[float],
        radii: Sequence[float],
        subdivisions: Sequence[int],
        role: str,
        paint: str,
        *,
        parent_cubes: Sequence[dict[str, Any]] | None = None,
        max_cuboids: int = 64,
        exponent: float = 2.4,
        cutouts: Sequence[EllipsoidCutout] = (),
        rear_depth_add: float = 0.0,
    ) -> tuple[EllipsoidResult, list[dict[str, Any]]]:
        """Add a voxelized volume, optionally extruded only into inferred rear space."""
        if rear_depth_add < 0:
            raise ValueError("rear depth addition cannot be negative")
        result = ellipsoid_cuboids(
            name,
            bone,
            center,
            radii,
            subdivisions,
            role,
            paint,
            max_cuboids=max_cuboids,
            exponent=exponent,
            cutouts=cutouts,
        )
        for cube in result.cubes:
            cube["center"][2] -= rear_depth_add / 2
            cube["origin"][2] -= rear_depth_add / 2
            cube["size"][2] += rear_depth_add
        cubes = add_volume(builder, result, attachments)
        if parent_cubes is not None:
            attachments.append(bridge_volumes(parent_cubes, cubes))
        return result, cubes

    def surface_segment(
        name: str,
        bone: str,
        start: Sequence[float],
        end: Sequence[float],
        source: Sequence[dict[str, Any]],
        role: str,
        paint: str,
        thickness: tuple[float, float] = (0.9, 0.7),
    ) -> None:
        builder.add_cube(
            segment_cube(
                name,
                bone,
                start,
                end,
                thickness,
                role,
                paint,
                overlap=0.2,
            )
        )
        attachments.append((containing_cube(source, start)["name"], name, tuple(start)))

    _, torso_cubes = volume(
        "torso_core", "torso", (0.0, 44.0, 0.0), (24.0, 16.0, 12.0),
        (10, 8, 8), "wide fused shoulder and trunk mass", "flesh",
        exponent=2.6, rear_depth_add=REAR_DEPTH_ADDITIONS["torso_core"],
    )
    _, left_arm_cubes = volume(
        "left_arm_mass", "left_arm", (-22.0, 56.5, -0.5), (18.0, 10.5, 11.0),
        (6, 6, 4), "foreshortened left shoulder and forearm mass", "flesh_light",
        parent_cubes=torso_cubes, exponent=2.5,
        rear_depth_add=REAR_DEPTH_ADDITIONS["left_arm_mass"],
    )
    _, left_fist_cubes = volume(
        "left_fist_volume", "left_arm", (-40.0, 59.5, 1.0), (10.0, 8.5, 9.5),
        (6, 5, 4), "huge end-on left clenched fist", "flesh",
        parent_cubes=left_arm_cubes, exponent=2.8,
        rear_depth_add=REAR_DEPTH_ADDITIONS["left_fist_volume"],
    )
    _, right_upper_cubes = volume(
        "right_arm_upper_mass", "right_arm", (17.0, 41.5, 1.0), (17.0, 12.5, 12.0),
        (6, 6, 4), "fused right shoulder and upper arm", "flesh",
        parent_cubes=torso_cubes, exponent=2.55,
        rear_depth_add=REAR_DEPTH_ADDITIONS["right_arm_upper_mass"],
    )
    _, right_forearm_cubes = volume(
        "right_forearm_mass", "right_arm", (31.0, 32.5, 3.0), (14.0, 10.5, 10.5),
        (6, 6, 4), "massive downward-sweeping right forearm", "flesh_light",
        parent_cubes=right_upper_cubes, exponent=2.55,
        rear_depth_add=REAR_DEPTH_ADDITIONS["right_forearm_mass"],
    )
    _, right_fist_cubes = volume(
        "right_fist_volume", "right_arm", (43.0, 25.5, 4.0), (9.5, 9.5, 9.5),
        (6, 5, 4), "huge three-quarter right clenched fist", "flesh",
        parent_cubes=right_forearm_cubes, exponent=2.7,
        rear_depth_add=REAR_DEPTH_ADDITIONS["right_fist_volume"],
    )
    for side, fist_cubes, positions in (
        ("left", left_fist_cubes, ((-45.0, 61.0), (-41.5, 59.5), (-38.0, 58.0))),
        ("right", right_fist_cubes, ((39.5, 27.0), (43.0, 25.5), (46.5, 24.0))),
    ):
        for index, (x, y) in enumerate(positions, start=1):
            name = f"{side}_fist_knuckle_{index}"
            probe = (x, y, 8.2)
            builder.add_cube(
                box(
                    name,
                    f"{side}_arm",
                    (x, y, 10.5),
                    (3.6, 3.8, 5.0),
                    f"{side} fist organic knuckle",
                    "flesh_light",
                )
            )
            attachments.append((containing_cube(fist_cubes, probe)["name"], name, probe))

    head, head_cubes = volume(
        "face_volume", "head", (-16.0, 37.5, 7.0), (18.0, 20.0, 11.0),
        (9, 9, 5), "embedded screaming face and cheek mass", "flesh_light",
        parent_cubes=torso_cubes,
        max_cuboids=96,
        exponent=1.8,
        cutouts=(EllipsoidCutout(center=(-16.0, 32.0, 16.5), radii=(6.8, 8.2, 8.5)),),
        rear_depth_add=REAR_DEPTH_ADDITIONS["face_volume"],
    )
    head_by_name = {cube["name"]: cube for cube in head_cubes}
    for cube_name, face in head.carved_faces:
        head_by_name[cube_name]["faces"][face] = {"material": "flesh_shadow"}
    _, jaw_cubes = volume(
        "jaw_mass", "jaw", (-16.0, 21.5, 6.0), (11.0, 7.0, 9.5),
        (6, 6, 4), "wide fleshy lower jaw fused into the trunk", "flesh_light",
        parent_cubes=head_cubes, exponent=2.45,
        rear_depth_add=REAR_DEPTH_ADDITIONS["jaw_mass"],
    )
    _, mouth_cubes = volume(
        "mouth_cavity", "jaw", (-16.0, 32.0, 10.4), (6.3, 7.8, 1.5),
        (6, 8, 3), "deep circular scream cavity", "mouth",
        parent_cubes=jaw_cubes, max_cuboids=44, exponent=2.0,
        rear_depth_add=REAR_DEPTH_ADDITIONS["mouth_cavity"],
    )
    for row, y in (("upper", 37.8), ("lower", 26.2)):
        for index, x in enumerate((-19.3, -16.0, -12.7), start=1):
            name = f"{row}_mouth_tooth_{index}"
            probe = (x, y, 10.8)
            builder.add_cube(
                box(
                    name,
                    "jaw",
                    (x, y, 12.0),
                    (1.6, 2.8, 2.6),
                    f"irregular {row} tooth in the circular scream",
                    "tooth",
                    rotation=(0.0, 0.0, -7.0 if (index + (row == "lower")) % 2 else 7.0),
                    origin=probe,
                )
            )
            attachments.append((containing_cube(mouth_cubes, probe)["name"], name, probe))

    for side, x, y, radii in (
        ("left", -23.0, 43.0, (4.2, 4.2, 2.3)),
        ("right", -9.0, 43.5, (4.4, 4.4, 2.3)),
    ):
        _, eye_cubes = volume(
            f"{side}_bulging_eye", "head", (x, y, 16.3), radii, (4, 4, 4),
            f"{side} bulging terrified eye", "eye",
            parent_cubes=head_cubes, max_cuboids=28, exponent=2.1,
            rear_depth_add=REAR_DEPTH_ADDITIONS[f"{side}_bulging_eye"],
        )
        pupil = f"{side}_pupil"
        probe = (x, y, 17.9)
        builder.add_cube(
            box(pupil, "head", (x, y, 18.5), (2.0, 2.4, 1.2), "dilated forward pupil", "pupil")
        )
        attachments.append((containing_cube(eye_cubes, probe)["name"], pupil, probe))

    facial_folds = (
        ("left_brow_fold", (-27.0, 44.0, 12.0), (-23.0, 47.5, 16.5), head_cubes),
        ("left_inner_brow_fold", (-21.5, 46.0, 14.0), (-18.0, 49.0, 16.0), head_cubes),
        ("right_inner_brow_fold", (-10.5, 47.0, 14.0), (-13.0, 49.5, 16.0), head_cubes),
        ("right_brow_fold", (-4.5, 44.0, 12.0), (-8.5, 47.5, 16.5), head_cubes),
        ("left_cheek_fold", (-27.0, 37.0, 13.2), (-25.0, 31.0, 16.5), head_cubes),
        ("right_cheek_fold", (-5.0, 38.0, 13.2), (-6.0, 32.0, 16.5), head_cubes),
        ("left_nasolabial_fold", (-25.0, 38.0, 14.0), (-21.0, 29.0, 16.2), head_cubes),
        ("right_nasolabial_fold", (-6.0, 38.0, 14.0), (-11.0, 29.0, 16.2), head_cubes),
        ("chin_fold", (-21.0, 21.0, 10.0), (-11.0, 21.5, 12.0), jaw_cubes),
    )
    for name, start, end, source in facial_folds:
        surface_segment(name, "head", start, end, source, "deep expressive face fold", "fold")
    builder.add_cube(
        box("broken_nose", "head", (-16.0, 38.5, 15.3), (3.2, 5.0, 4.4), "flattened torn nose", "flesh_shadow")
    )
    attachments.append(
        (containing_cube(head_cubes, (-16.0, 40.0, 13.2))["name"], "broken_nose", (-16.0, 40.0, 13.2))
    )
    for index, (start, end) in enumerate(
        (
            ((-30.0, 43.0, 9.0), (-33.0, 45.0, 10.0)),
            ((-26.0, 49.0, 8.0), (-28.0, 52.0, 8.7)),
            ((-20.0, 53.0, 7.0), (-21.0, 57.0, 7.7)),
            ((-12.0, 52.0, 8.0), (-10.5, 56.0, 8.8)),
            ((-4.0, 47.0, 8.0), (-1.0, 50.0, 9.0)),
        ),
        start=1,
    ):
        surface_segment(
            f"hair_tuft_{index}", "head", start, end, head_cubes,
            "ragged hair spike", "hair", (1.2, 0.9),
        )

    _, neck_cubes = volume(
        "brain_neck_mass", "brain_neck", (12.0, 61.0, -0.5), (11.5, 16.0, 10.5),
        (6, 6, 4), "thick fused neck supporting the exposed brain", "flesh",
        parent_cubes=torso_cubes, exponent=2.5,
        rear_depth_add=REAR_DEPTH_ADDITIONS["brain_neck_mass"],
    )
    _, brain_cubes = volume(
        "brain_volume", "brain", (17.0, 76.0, 0.5), (12.0, 11.0, 10.0),
        (6, 8, 5), "large exposed brain fused into the neck", "brain",
        parent_cubes=neck_cubes, exponent=1.7,
        rear_depth_add=REAR_DEPTH_ADDITIONS["brain_volume"],
    )
    grooves = (
        ((9.2, 78.0, 6.4), (12.0, 82.0, 9.0)),
        ((11.5, 83.0, 6.4), (16.0, 80.0, 9.5)),
        ((15.5, 80.0, 6.4), (20.0, 84.0, 8.8)),
        ((20.0, 83.0, 6.4), (24.0, 80.0, 8.0)),
        ((9.2, 74.0, 6.4), (11.5, 70.5, 9.0)),
        ((11.5, 70.5, 6.4), (16.0, 74.0, 10.0)),
        ((16.0, 74.0, 6.4), (20.5, 70.0, 9.0)),
        ((20.5, 70.0, 6.4), (26.0, 73.0, 7.5)),
        ((10.0, 69.0, 5.5), (14.0, 71.0, 8.0)),
        ((19.5, 69.0, 6.4), (17.0, 72.0, 9.5)),
    )
    for index, (start, end) in enumerate(grooves, start=1):
        surface_segment(
            f"brain_groove_{index}", "brain", start, end, brain_cubes,
            "raised cerebral fissure", "brain_groove", (1.25, 0.8),
        )

    _, bridge_cubes = volume(
        "visceral_bridge", "viscera", (-1.0, 28.0, 1.5), (16.0, 11.0, 12.0),
        (6, 6, 4), "torn lower trunk blending into exposed organs", "flesh",
        parent_cubes=torso_cubes, exponent=2.5,
        rear_depth_add=REAR_DEPTH_ADDITIONS["visceral_bridge"],
    )
    organ_specs = (
        (
            "organ_lobe_left_upper", (-8.0, 21.0, 5.0), (-14.0, 8.0, 7.0),
            (14.0, 10.0), "organ_light", None,
        ),
        (
            "organ_lobe_left_lower", (-14.0, 8.0, 7.0), (-9.0, -8.0, 8.0),
            (12.0, 9.0), "organ_dark", "organ_lobe_left_upper",
        ),
        (
            "organ_lobe_right_upper", (0.0, 21.0, 8.0), (7.0, 7.0, 10.0),
            (15.0, 11.0), "organ_dark", None,
        ),
        (
            "organ_lobe_right_lower", (7.0, 7.0, 10.0), (2.0, -10.0, 11.0),
            (12.0, 9.0), "organ_light", "organ_lobe_right_upper",
        ),
    )
    organ_cubes: dict[str, dict[str, Any]] = {}
    for name, start, end, thickness, paint, parent in organ_specs:
        cube = segment_cube(
            name,
            "viscera",
            start,
            end,
            thickness,
            f"broad asymmetric {name.replace('_', ' ')} flesh ribbon",
            paint,
            overlap=0.8,
        )
        builder.add_cube(cube)
        organ_cubes[name] = cube
        if parent is None:
            attachments.append((containing_cube(bridge_cubes, start)["name"], name, start))
        else:
            attachments.append((parent, name, start))

    for name, parent, center, radii, paint in (
        ("organ_bulge_left_upper", "organ_lobe_left_upper", (-11.0, 14.0, 7.0), (8.0, 9.0, 7.0), "organ_light"),
        ("organ_bulge_left_lower", "organ_lobe_left_lower", (-11.0, 0.0, 9.0), (7.0, 8.0, 7.0), "organ_dark"),
        ("organ_bulge_right_upper", "organ_lobe_right_upper", (3.0, 14.0, 10.0), (9.0, 10.0, 7.0), "organ_dark"),
        ("organ_bulge_right_lower", "organ_lobe_right_lower", (4.0, -3.0, 12.0), (7.0, 9.0, 6.0), "organ_light"),
    ):
        _, cubes = volume(
            name,
            "viscera",
            center,
            radii,
            (4, 4, 3),
            "rounded asymmetric organ swelling over a flesh ribbon",
            paint,
            max_cuboids=16,
            exponent=1.8,
            rear_depth_add=REAR_DEPTH_ADDITIONS[name],
        )
        attachments.append((parent, containing_cube(cubes, center)["name"], center))

    tendril_records = []
    tendrils = (
        (
            "left_visceral_continuation", "organ_lobe_left_lower",
            ((-9.0, -8.0, 8.0), (-19.0, -23.0, 8.0), (-15.0, -39.0, 7.0),
             (-27.0, -54.0, 7.0), (-22.0, -72.0, 6.0), (-30.0, -92.0, 5.0)),
            (7.5, 7.0, 6.2, 5.2, 4.5), (8.0, 7.5, 6.8, 5.8, 5.0), "intestine_dark",
        ),
        (
            "central_intertwined_loop", "organ_lobe_left_upper",
            ((-14.0, 8.0, 7.0), (-2.0, -20.0, 13.0), (8.0, -33.0, 14.0),
             (19.0, -25.0, 12.0), (14.0, -12.0, 10.0), (6.0, -5.0, 9.0)),
            (9.0, 8.5, 8.0, 7.5, 7.0), (9.5, 9.0, 8.5, 8.0, 7.5), "intestine",
        ),
        (
            "right_visceral_continuation", "organ_lobe_right_lower",
            ((2.0, -10.0, 11.0), (13.0, -25.0, 13.0), (6.0, -42.0, 12.0),
             (20.0, -57.0, 11.0), (13.0, -75.0, 9.0), (9.0, -92.0, 8.0)),
            (8.0, 7.5, 6.5, 5.5, 4.5), (8.5, 8.0, 7.0, 6.0, 5.0), "intestine",
        ),
    )
    for name, organ_name, points, widths, depths, paint in tendrils:
        chain = builder.add_chain(
            name,
            "viscera",
            points,
            widths,
            (paint,) * (len(points) - 1),
            "thick cropped visceral continuation",
            overlap=0.65,
            depths=depths,
        )
        attachments.append((organ_name, chain.cubes[0], points[0]))
        attachments.extend(chain.attachments)
        tendril_records.append(
            {
                "name": name,
                "joints": [list(point) for point in points],
                "segments": list(chain.cubes),
                "endpoint_is_frame_cropped": name != "central_intertwined_loop",
                "forms_closed_visual_loop": name == "central_intertwined_loop",
            }
        )

    for index, (start, end, source) in enumerate(
        (
            ((-1.0, 35.0, 6.0), (5.0, 32.0, 12.0), torso_cubes),
            ((3.0, 40.0, 6.0), (9.0, 37.0, 11.8), torso_cubes),
            ((8.0, 46.0, 6.0), (13.5, 43.0, 11.2), torso_cubes),
            ((18.0, 40.0, 4.0), (23.0, 37.0, 10.0), torso_cubes),
            ((-4.0, 29.0, 6.0), (2.0, 27.0, 11.0), bridge_cubes),
        ),
        start=1,
    ):
        surface_segment(
            f"torso_fold_{index}", "torso", start, end, source,
            "deep stretched flesh fold", "fold", (1.0, 0.75),
        )

    landmarks = [
        {
            "name": "left_eye_glint",
            "cube": "left_pupil",
            "face": "south",
            "center_uv": [0.42, 0.38],
            "size": [1, 1],
            "color": "#ffffff",
            "center_color": "#17171a",
        },
        {
            "name": "right_eye_glint",
            "cube": "right_pupil",
            "face": "south",
            "center_uv": [0.42, 0.38],
            "size": [1, 1],
            "color": "#ffffff",
            "center_color": "#17171a",
        },
        {
            "name": "nose_wound",
            "cube": "broken_nose",
            "face": "south",
            "center_uv": [0.5, 0.55],
            "size": [2, 2],
            "color": "#5f1e27",
            "center_color": "#19070b",
        },
    ]
    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    feature_inventory = {
        "massive_arm_chains": 2,
        "fists": 2,
        "fist_fingers": 6,
        "exposed_brains": 1,
        "brain_grooves": len(grooves),
        "carved_screaming_mouths": 1,
        "mouth_teeth": 6,
        "hanging_organ_lobes": len(organ_specs),
        "visceral_tendrils": len(tendril_records),
        "grounded_feet": 0,
        "observed_camera_axes": 1,
    }
    spec = {
        "schema_version": 1,
        "id": "zombie_devil_exposed_brain",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 513,
            "height": 754,
        },
        "subject": {
            "type": "creature",
            "description": (
                "A broad fused flesh mass with an embedded screaming face, exposed brain, "
                "two immense asymmetric fists, and cropped intertwined viscera"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "The supplied files are near-duplicate crops and establish one camera axis only",
                "The lower anatomy is cropped and occluded; two continuations extend beyond the evidence frame",
                "Rear material placement and exact hidden depth are conservative semantic inference",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [120, 192],
            "identity_features": [
                "deep circular carved scream with bulging eyes, torn nose, six teeth, and face folds",
                "large exposed brain fused into a broad neck with ten cerebral grooves",
                "wide shoulder field and two enormous asymmetric clenched fists",
                "four overlapping organ sacs and three thick intertwined visceral paths",
                "no invented biped legs or grounded feet",
                "substantial head, torso, arm, and brain depth",
            ],
            "required_views": [
                "reference-angle", "front", "back", "left", "right", "top",
                "isometric", "face-closeup", "brain-closeup", "viscera-closeup",
            ],
            "review_targets": [
                "duplicate-view disclosure", "fused horizontal silhouette", "circular screaming face",
                "integrated brain crown", "massive fists", "overlapping viscera",
                "frame-cropped continuations", "part-local depth", "attachments",
            ],
        },
        "geometry": {"precision": 240},
        "texture": {
            "density": 1,
            "palette_size": 24,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": landmarks,
        "collision": {"width": 6.5, "height": 5.5, "eye_height": 4.0},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "duplicate-aware-fused-zombie-anatomy-v3",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "observed_view_count": 2,
            "independent_observed_camera_axes": 1,
            "hidden_geometry_established_from_observed_views": False,
            "palette_contract": {
                "name": "user-selected-stylized-color",
                "source_is_grayscale": True,
                "source_projection_remains_grayscale": True,
                "colorization_is_authored_fallback": True,
                "warm_flesh_brain_and_viscera_palette": True,
            },
            "rear_depth_policy": {
                "method": "front-surface-preserving-rear-extrusion-v1",
                "observed_positive_z_surfaces_preserved": True,
                "rear_depth_is_inferred": True,
                "per_volume_additions": REAR_DEPTH_ADDITIONS,
            },
            "feature_inventory": feature_inventory,
            "head_cutout": {
                "removed_voxels": head.removed_voxels,
                "carved_faces": [list(value) for value in head.carved_faces],
            },
            "arm_chains": [
                {"side": "left", "volumes": ["left_arm_mass", "left_fist_volume"]},
                {
                    "side": "right",
                    "volumes": ["right_arm_upper_mass", "right_forearm_mass", "right_fist_volume"],
                },
            ],
            "visceral_tendrils": tendril_records,
            "source_frame_crop_world_y": -65.0,
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
