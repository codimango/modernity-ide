#!/usr/bin/env python3
"""Author the Round 2 False Apple as a native volumetric root creature."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from semantic_geometry import (
    BranchEdge,
    BranchNode,
    EllipsoidCutout,
    EllipsoidResult,
    SemanticModelBuilder,
    ellipsoid_cuboids,
    point_to_cuboid_margin,
    segment_cube,
)


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "image-2.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "c6061900b7e45c555a5c3d94ca5584d2c06d91e9d8144f302c881fc3f42fdaae"


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "dither",
    scale: int = 3,
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
    center: Sequence[float],
    size: Sequence[float],
    role: str,
    material_name: str,
    *,
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    origin: Sequence[float] | None = None,
    faces: dict[str, Any] | None = None,
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
        "faces": dict(faces or {}),
    }


def cube_bounds(cube: dict[str, Any]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return authored bounds for an axis-aligned volume cuboid."""
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
    """Return a deterministic touching-box tree for one voxelized volume."""
    if not cubes:
        raise ValueError("volume cannot be empty")
    bounds = {cube["name"]: cube_bounds(cube) for cube in cubes}
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
                    candidate = (first, second, joint)
                    break
            if candidate is not None:
                break
        if candidate is None:
            raise ValueError("ellipsoid cuboids are not one connected volume")
        links.append(candidate)
        reached.add(candidate[1])
        pending.remove(candidate[1])
    return links


def containing_cube(
    cubes: Sequence[dict[str, Any]], point: Sequence[float]
) -> dict[str, Any]:
    """Return the most deeply containing cuboid for an authored joint."""
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
    """Choose the broadest real overlap between two axis-aligned volumes."""
    candidates = []
    for first_cube in first:
        first_lower, first_upper = cube_bounds(first_cube)
        for second_cube in second:
            second_lower, second_upper = cube_bounds(second_cube)
            lower = tuple(max(first_lower[axis], second_lower[axis]) for axis in range(3))
            upper = tuple(min(first_upper[axis], second_upper[axis]) for axis in range(3))
            overlap = tuple(upper[axis] - lower[axis] for axis in range(3))
            if all(value >= -1e-6 for value in overlap):
                score = min(overlap)
                joint = tuple((lower[axis] + upper[axis]) / 2 for axis in range(3))
                candidates.append((score, first_cube["name"], second_cube["name"], joint))
    if not candidates:
        raise ValueError("semantic volumes do not overlap")
    _, first_name, second_name, joint = max(candidates)
    return first_name, second_name, joint


def add_volume(
    builder: SemanticModelBuilder,
    result: EllipsoidResult,
    attachments: list[tuple[str, str, tuple[float, float, float]]],
) -> list[dict[str, Any]]:
    """Add an ellipsoid result and its exact internal contact tree."""
    cubes = list(result.cubes)
    for cube in cubes:
        builder.add_cube(cube)
    attachments.extend(axis_aligned_spanning_links(cubes))
    return cubes


def graph_edge_last(graph: dict[str, Any], edge_name: str) -> str:
    """Resolve the terminal cuboid emitted for a named branch edge."""
    edge = next(edge for edge in graph["edges"] if edge["name"] == edge_name)
    return edge["segments"][-1]


def front_cube_name(cubes: Sequence[dict[str, Any]], x: float, y: float) -> str:
    """Choose the frontmost occupied cuboid at one semantic paint point."""
    candidates = []
    for cube in cubes:
        center = tuple(float(value) for value in cube["center"])
        size = tuple(float(value) for value in cube["size"])
        if (
            center[0] - size[0] / 2 <= x <= center[0] + size[0] / 2
            and center[1] - size[1] / 2 <= y <= center[1] + size[1] / 2
        ):
            candidates.append((center[2] + size[2] / 2, cube["name"]))
    if not candidates:
        raise ValueError(f"no front surface contains paint point {(x, y)}")
    return max(candidates)[1]


def main() -> None:
    """Write a deep apple lure on a sprawling, gaping root-and-bark predator."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected False Apple reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.mode != "RGBA" or opened.size != (599, 290):
            raise ValueError(f"unexpected False Apple reference: {opened.mode} {opened.size}")

    materials = {
        "bark": material("#716151", "#302820", "#b8aa91", "stripes", 3),
        "bark_light": material("#a49277", "#4b4034", "#d7ccb3", "dither", 3),
        "bark_dark": material("#3c352d", "#171512", "#706255", "stripes", 4),
        "bark_wet": material("#51453b", "#1d1a17", "#8d7865", "gradient", 3),
        "maw_shadow": material("#241516", "#080707", "#5a292a", "gradient", 2),
        "gum": material("#71302d", "#281011", "#b8614f", "dither", 2),
        "flesh": material("#b5212d", "#4b1019", "#ed5860", "gradient", 3),
        "apple_red": material("#bd202a", "#5e1018", "#f05a5d", "dither", 4),
        "apple_dark": material("#75151e", "#2c0a0f", "#b82c38", "gradient", 3),
        "apple_light": material("#df3940", "#8a1520", "#ff8b82", "dither", 2),
        "tooth": material("#d7ccb0", "#726956", "#fff4d4", "gradient", 2),
        "root_tip": material("#8b795f", "#3d3329", "#cbbda0", "dither", 2),
        "stem": material("#3a241d", "#130d0b", "#795342", "stripes", 2),
    }

    builder = SemanticModelBuilder()
    builder.add_bone("body", "root", (2.0, 23.0, 0.0))
    body_core = box(
        "body_core",
        "body",
        (2.0, 23.0, 0.0),
        (17.0, 14.0, 18.0),
        "deep central knot joining trunk, lure, and roots",
        "bark_dark",
    )
    builder.add_cube(body_core)
    attachments: list[tuple[str, str, tuple[float, float, float]]] = []
    branch_graphs: list[dict[str, Any]] = []

    spine = builder.add_branch_graph(
        "spine",
        "body",
        "core",
        (
            BranchNode("core", (0.0, 25.0, 0.0)),
            BranchNode("neck_mid", (-9.0, 28.0, 0.5)),
            BranchNode("head_socket", (-20.0, 32.0, 0.0)),
            BranchNode("rear_mid", (16.0, 24.0, -1.5)),
            BranchNode("rear_socket", (31.0, 21.0, -5.0)),
        ),
        (
            BranchEdge(
                "headward", "core", "neck_mid", 13.0, 11.0,
                "bark_light", "arched head-bearing trunk", 2, 17.0, 15.0,
            ),
            BranchEdge(
                "head_socket", "neck_mid", "head_socket", 11.0, 8.0,
                "bark", "tapered skull junction", 2, 15.0, 12.0,
            ),
            BranchEdge(
                "rearward", "core", "rear_mid", 13.0, 10.0,
                "bark", "long horizontal arched trunk", 3, 17.0, 14.0,
            ),
            BranchEdge(
                "rear_arch", "rear_mid", "rear_socket", 10.0, 6.5,
                "bark_dark", "rear load path into the arched support", 2, 14.0, 10.0,
            ),
        ),
        overlap=0.8,
        parent_cube="body_core",
    )
    attachments.extend(spine.attachments)
    branch_graphs.append(spine.manifest)

    lure_support = builder.add_branch_graph(
        "lure_support",
        "body",
        "root",
        (
            BranchNode("root", (5.0, 27.0, 0.0)),
            BranchNode("rise", (8.0, 30.0, 0.0)),
            BranchNode("apple_socket", (10.0, 32.0, 0.0)),
        ),
        (
            BranchEdge(
                "lower", "root", "rise", 7.5, 6.2,
                "flesh", "fleshy false-apple peduncle", 1, 9.0, 8.0,
            ),
            BranchEdge(
                "upper", "rise", "apple_socket", 6.2, 5.0,
                "apple_dark", "apple-to-body socket", 1, 8.0, 6.5,
            ),
        ),
        overlap=0.65,
        parent_cube="body_core",
    )
    attachments.extend(lure_support.attachments)
    branch_graphs.append(lure_support.manifest)

    builder.add_bone("head", graph_edge_last(spine.manifest, "head_socket"), (-20, 32, 0))
    skull_cutouts = (
        EllipsoidCutout(center=(-44.0, 24.0, 8.0), radii=(15.5, 12.0, 10.5)),
        EllipsoidCutout(center=(-42.0, 38.5, 12.0), radii=(5.0, 4.5, 4.5)),
    )
    skull = ellipsoid_cuboids(
        "skull_volume",
        "head",
        (-38.0, 36.0, 0.0),
        (21.0, 18.0, 14.0),
        (10, 10, 8),
        "carved domed bark skull surrounding a recessed maw",
        "bark",
        max_cuboids=80,
        exponent=2.12,
        cutouts=skull_cutouts,
    )
    skull_cubes = list(skull.cubes)
    carved_skull_faces = []
    skull_by_name = {cube["name"]: cube for cube in skull_cubes}
    for cube_name, face in skull.carved_faces:
        skull_by_name[cube_name]["faces"][face] = {"material": "maw_shadow"}
        carved_skull_faces.append((cube_name, face))
    for index, cube in enumerate(skull_cubes):
        if index % 5 == 0 and not cube["faces"]:
            cube["material"] = "bark_light"
    add_volume(builder, skull, attachments)
    skull_socket = (-20.0, 32.0, 0.0)
    attachments.append(
        (
            graph_edge_last(spine.manifest, "head_socket"),
            containing_cube(skull_cubes, skull_socket)["name"],
            skull_socket,
        )
    )

    builder.add_bone("jaw", "head", (-32.0, 19.0, -2.0))
    jaw = ellipsoid_cuboids(
        "lower_jaw_volume",
        "jaw",
        (-43.0, 14.0, 1.5),
        (17.0, 8.0, 11.5),
        (10, 6, 8),
        "broad deep lower bark jaw",
        "bark_dark",
        max_cuboids=45,
        exponent=2.2,
    )
    jaw_cubes = add_volume(builder, jaw, attachments)
    attachments.append(bridge_volumes(skull_cubes, jaw_cubes))

    upper_gum_points = ((-25.0, 30.0, 5.0), (-38.0, 25.5, 10.5), (-53.0, 24.0, 8.0))
    upper_gum = builder.add_chain(
        "upper_gum",
        "head",
        upper_gum_points,
        (4.2, 3.2),
        ("gum", "gum"),
        "ragged upper gum rail around the open maw",
        overlap=0.55,
        depths=(4.5, 3.5),
    )
    attachments.append(
        (
            containing_cube(skull_cubes, upper_gum_points[0])["name"],
            upper_gum.cubes[0],
            upper_gum_points[0],
        )
    )
    attachments.extend(upper_gum.attachments)

    lower_gum_points = ((-30.0, 17.0, 4.0), (-41.0, 18.0, 10.5), (-55.0, 16.5, 7.5))
    lower_gum = builder.add_chain(
        "lower_gum",
        "jaw",
        lower_gum_points,
        (3.8, 3.0),
        ("gum", "gum"),
        "forward lower gum rail",
        overlap=0.55,
        depths=(4.2, 3.2),
    )
    attachments.append(
        (
            containing_cube(jaw_cubes, lower_gum_points[0])["name"],
            lower_gum.cubes[0],
            lower_gum_points[0],
        )
    )
    attachments.extend(lower_gum.attachments)

    upper_teeth = (
        ("upper_tooth_1", upper_gum.cubes[0], (-28.0, 28.9, 6.3), (-29.0, 20.0, 7.5), 1.55),
        ("upper_tooth_2", upper_gum.cubes[0], (-33.0, 27.2, 8.4), (-34.0, 16.5, 9.0), 1.75),
        ("upper_tooth_3", upper_gum.cubes[0], (-37.0, 25.9, 10.0), (-38.0, 19.0, 10.8), 1.4),
        ("upper_tooth_4", upper_gum.cubes[1], (-42.0, 25.1, 10.0), (-43.0, 13.0, 10.5), 1.9),
        ("upper_tooth_5", upper_gum.cubes[1], (-47.0, 24.6, 9.2), (-48.0, 17.0, 9.0), 1.45),
        ("upper_tooth_6", upper_gum.cubes[1], (-51.5, 24.1, 8.2), (-53.0, 18.5, 7.5), 1.2),
    )
    lower_teeth = (
        ("lower_tooth_1", lower_gum.cubes[0], (-31.0, 17.2, 5.1), (-31.5, 23.5, 6.5), 1.25),
        ("lower_tooth_2", lower_gum.cubes[0], (-36.0, 17.6, 7.8), (-36.5, 26.0, 9.0), 1.55),
        ("lower_tooth_3", lower_gum.cubes[0], (-40.0, 17.9, 10.0), (-41.0, 23.5, 11.0), 1.2),
        ("lower_tooth_4", lower_gum.cubes[1], (-45.0, 17.6, 9.7), (-46.0, 27.0, 10.0), 1.65),
        ("lower_tooth_5", lower_gum.cubes[1], (-50.0, 17.0, 8.6), (-51.5, 23.5, 8.5), 1.25),
        ("lower_tooth_6", lower_gum.cubes[1], (-53.5, 16.7, 7.8), (-55.0, 21.5, 7.2), 1.05),
    )
    for name, gum_cube, start, end, thickness in (*upper_teeth, *lower_teeth):
        builder.add_cube(
            segment_cube(
                name,
                "head" if name.startswith("upper") else "jaw",
                start,
                end,
                (thickness, thickness * 0.8),
                "irregular conical-equivalent maw fang",
                "tooth",
                overlap=0.28,
            )
        )
        attachments.append((gum_cube, name, start))

    apple_parent_bone = graph_edge_last(lure_support.manifest, "upper")
    builder.add_bone("apple", apple_parent_bone, (10.0, 32.0, 0.0))
    apple_cutouts = (
        EllipsoidCutout(center=(12.0, 52.5, 0.0), radii=(4.5, 3.0, 16.0)),
        EllipsoidCutout(center=(11.0, 25.0, 8.0), radii=(8.0, 4.5, 9.0)),
    )
    apple = ellipsoid_cuboids(
        "apple_lure_volume",
        "apple",
        (12.0, 39.0, 0.0),
        (16.0, 14.0, 12.0),
        (12, 10, 8),
        "deep red false-apple lure with a torn lower notch",
        "apple_red",
        max_cuboids=70,
        exponent=2.18,
        cutouts=apple_cutouts,
    )
    apple_cubes = list(apple.cubes)
    apple_by_name = {cube["name"]: cube for cube in apple_cubes}
    carved_apple_faces = []
    for cube_name, face in apple.carved_faces:
        apple_by_name[cube_name]["faces"][face] = {"material": "apple_dark"}
        carved_apple_faces.append((cube_name, face))
    for cube in apple_cubes:
        center = tuple(float(value) for value in cube["center"])
        if center[0] > 17.0 and center[1] > 42.0:
            cube["material"] = "apple_light"
    add_volume(builder, apple, attachments)
    apple_socket = (10.0, 32.0, 0.0)
    attachments.append(
        (
            graph_edge_last(lure_support.manifest, "upper"),
            containing_cube(apple_cubes, apple_socket)["name"],
            apple_socket,
        )
    )

    stem_root = (17.0, 50.0, 0.0)
    stem_parent = containing_cube(apple_cubes, stem_root)["name"]
    stem = builder.add_branch_graph(
        "crooked_stem",
        "apple",
        "socket",
        (
            BranchNode("socket", stem_root),
            BranchNode("lower", (14.5, 54.0, -0.5)),
            BranchNode("upper", (12.5, 57.0, 0.25)),
            BranchNode("tip", (9.0, 60.0, 0.0)),
        ),
        (
            BranchEdge("lower", "socket", "lower", 1.7, 1.25, "stem", "crooked stem base", 1, 1.5, 1.1),
            BranchEdge("middle", "lower", "upper", 1.25, 0.8, "stem", "crooked stem middle", 1, 1.1, 0.7),
            BranchEdge("tip", "upper", "tip", 0.8, 0.35, "stem", "broken stem tip", 1, 0.7, 0.3),
        ),
        overlap=0.3,
        parent_cube=stem_parent,
    )
    attachments.extend(stem.attachments)
    branch_graphs.append(stem.manifest)

    drip_data = (
        ("left_flesh_drip", (1.0, 32.0, 5.0), (-1.0, 25.0, 7.0), (-2.0, 20.0, 7.5)),
        ("middle_flesh_drip", (13.0, 31.0, -5.0), (14.0, 24.0, -7.0), (11.0, 19.0, -8.0)),
        ("right_flesh_drip", (24.0, 32.0, 4.0), (27.0, 26.0, 6.0), (27.0, 21.0, 7.0)),
    )
    for name, root, bend, tip in drip_data:
        parent_cube = containing_cube(apple_cubes, root)["name"]
        graph = builder.add_branch_graph(
            name,
            "apple",
            "root",
            (BranchNode("root", root), BranchNode("bend", bend), BranchNode("tip", tip)),
            (
                BranchEdge("lower", "bend", "tip", 2.0, 0.7, "flesh", "ragged flesh taper", 1, 2.0, 0.65),
                BranchEdge("upper", "root", "bend", 3.2, 2.0, "apple_dark", "torn apple lobe", 1, 3.0, 2.0),
            ),
            overlap=0.35,
            parent_cube=parent_cube,
        )
        attachments.extend(graph.attachments)
        branch_graphs.append(graph.manifest)

    root_records: list[dict[str, Any]] = []

    def add_root_graph(
        name: str,
        layer: str,
        parent_bone: str,
        parent_cube: str,
        nodes: Sequence[BranchNode],
        edges: Sequence[BranchEdge],
    ) -> None:
        graph = builder.add_branch_graph(
            name,
            parent_bone,
            "root",
            nodes,
            edges,
            overlap=0.55,
            parent_cube=parent_cube,
        )
        attachments.extend(graph.attachments)
        branch_graphs.append(graph.manifest)
        root_records.append(
            {
                "name": name,
                "depth_layer": layer,
                "root": list(next(node.point for node in nodes if node.name == "root")),
                "terminal_nodes": [
                    list(node.point)
                    for node in nodes
                    if node.name.endswith("tip")
                ],
                "segments": list(graph.cubes),
            }
        )

    add_root_graph(
        "near_fore_hand",
        "near",
        "body",
        "body_core",
        (
            BranchNode("root", (-1.0, 20.0, 7.0)),
            BranchNode("shoulder", (7.0, 17.0, 12.0)),
            BranchNode("elbow", (18.0, 10.0, 16.0)),
            BranchNode("wrist", (11.0, 4.0, 19.0)),
            BranchNode("palm", (0.0, 1.8, 21.0)),
            BranchNode("outer_tip", (-17.0, 1.2, 24.0)),
            BranchNode("middle_tip", (-7.0, 1.0, 27.0)),
            BranchNode("inner_tip", (7.0, 1.1, 25.0)),
            BranchNode("spur_tip", (15.0, 3.0, 21.0)),
        ),
        (
            BranchEdge("arm", "shoulder", "elbow", 7.0, 5.2, "bark", "massive reaching root arm", 2, 8.0, 6.2),
            BranchEdge("forearm", "elbow", "wrist", 5.2, 4.0, "bark_light", "foreground root forearm", 2, 6.2, 4.8),
            BranchEdge("inner_digit", "palm", "inner_tip", 2.7, 0.85, "root_tip", "inner grasping root finger", 2, 2.5, 0.7),
            BranchEdge("middle_digit", "palm", "middle_tip", 2.9, 0.9, "root_tip", "middle grasping root finger", 2, 2.6, 0.75),
            BranchEdge("outer_digit", "palm", "outer_tip", 3.0, 0.9, "root_tip", "long outer root finger", 2, 2.7, 0.75),
            BranchEdge("palm", "wrist", "palm", 4.0, 3.0, "bark_wet", "broad foreground root palm", 2, 4.8, 3.5),
            BranchEdge("root", "root", "shoulder", 8.5, 7.0, "bark_dark", "near-layer root shoulder", 2, 9.0, 8.0),
            BranchEdge("spur", "wrist", "spur_tip", 2.6, 0.7, "root_tip", "raised wrist spur", 1, 2.2, 0.6),
        ),
    )

    add_root_graph(
        "far_under_root",
        "far",
        "body",
        "body_core",
        (
            BranchNode("root", (-4.0, 20.0, -7.0)),
            BranchNode("shoulder", (-13.0, 15.0, -11.0)),
            BranchNode("wrist", (-17.0, 7.0, -15.0)),
            BranchNode("palm", (-20.0, 1.8, -17.0)),
            BranchNode("outer_tip", (-29.0, 1.2, -20.0)),
            BranchNode("inner_tip", (-14.0, 1.1, -22.0)),
        ),
        (
            BranchEdge("arm", "shoulder", "wrist", 5.3, 3.6, "bark", "shadowed far root arm", 2, 5.5, 3.8),
            BranchEdge("inner_digit", "palm", "inner_tip", 2.2, 0.7, "root_tip", "far inner rootlet", 2, 2.0, 0.6),
            BranchEdge("outer_digit", "palm", "outer_tip", 2.4, 0.75, "root_tip", "far outer rootlet", 2, 2.1, 0.65),
            BranchEdge("palm", "wrist", "palm", 3.6, 2.4, "bark_dark", "far root palm", 1, 3.8, 2.5),
            BranchEdge("root", "root", "shoulder", 6.4, 5.3, "bark_dark", "far-layer root shoulder", 2, 6.5, 5.5),
        ),
    )

    add_root_graph(
        "near_right_root",
        "near",
        "body",
        "body_core",
        (
            BranchNode("root", (7.0, 20.0, 7.0)),
            BranchNode("shoulder", (20.0, 16.0, 11.0)),
            BranchNode("elbow", (30.0, 8.0, 15.0)),
            BranchNode("palm", (37.0, 1.8, 17.0)),
            BranchNode("outer_tip", (50.0, 1.2, 19.0)),
            BranchNode("middle_tip", (43.0, 1.0, 23.0)),
            BranchNode("inner_tip", (34.0, 1.1, 24.0)),
        ),
        (
            BranchEdge("arm", "shoulder", "elbow", 6.8, 4.4, "bark_light", "near right support arm", 2, 7.5, 5.2),
            BranchEdge("forearm", "elbow", "palm", 4.4, 3.0, "bark", "near right root forearm", 2, 5.2, 3.4),
            BranchEdge("inner_digit", "palm", "inner_tip", 2.5, 0.7, "root_tip", "near right inner rootlet", 2, 2.2, 0.6),
            BranchEdge("middle_digit", "palm", "middle_tip", 2.6, 0.75, "root_tip", "near right middle rootlet", 2, 2.3, 0.65),
            BranchEdge("outer_digit", "palm", "outer_tip", 2.8, 0.8, "root_tip", "near right outer rootlet", 2, 2.4, 0.7),
            BranchEdge("root", "root", "shoulder", 7.8, 6.8, "bark_dark", "near right root shoulder", 2, 8.5, 7.5),
        ),
    )

    rear_parent = graph_edge_last(spine.manifest, "rear_arch")
    add_root_graph(
        "far_rear_arch",
        "far",
        rear_parent,
        rear_parent,
        (
            BranchNode("root", (31.0, 21.0, -5.0)),
            BranchNode("upper", (37.0, 36.0, -11.0)),
            BranchNode("crown", (44.0, 42.0, -14.0)),
            BranchNode("shin", (43.0, 16.0, -16.0)),
            BranchNode("palm", (45.0, 2.0, -17.0)),
            BranchNode("outer_tip", (60.0, 9.0, -19.0)),
            BranchNode("middle_tip", (52.0, 1.0, -24.0)),
            BranchNode("inner_tip", (39.0, 1.1, -25.0)),
        ),
        (
            BranchEdge("arch", "root", "upper", 7.2, 6.0, "bark", "rising rear root arch", 2, 8.5, 7.0),
            BranchEdge("crown", "upper", "crown", 6.0, 5.2, "bark_light", "high rear arch crown", 1, 7.0, 6.0),
            BranchEdge("inner_digit", "palm", "inner_tip", 2.6, 0.75, "root_tip", "far rear inner rootlet", 2, 2.3, 0.65),
            BranchEdge("middle_digit", "palm", "middle_tip", 2.7, 0.8, "root_tip", "far rear middle rootlet", 2, 2.4, 0.7),
            BranchEdge("outer_digit", "palm", "outer_tip", 3.0, 0.85, "root_tip", "far rear outer rootlet", 2, 2.6, 0.7),
            BranchEdge("shin", "crown", "shin", 5.2, 4.0, "bark_dark", "descending rear support", 3, 6.0, 4.5),
            BranchEdge("wrist", "shin", "palm", 4.0, 2.8, "bark", "rear grounded wrist", 2, 4.5, 3.0),
        ),
    )

    landmarks = [
        {
            "name": "recessed_watching_eye",
            "cube": front_cube_name(skull_cubes, -42.0, 38.5),
            "face": "south",
            "center_uv": [0.5, 0.5],
            "size": [3, 2],
            "color": "#130909",
            "center_color": "#9d3a2e",
        },
        {
            "name": "apple_highlight_upper",
            "cube": front_cube_name(apple_cubes, 18.0, 47.0),
            "face": "south",
            "center_uv": [0.5, 0.5],
            "size": [8, 3],
            "color": "#ff9a8b",
            "center_color": "#ffd0b4",
        },
        {
            "name": "apple_highlight_lower",
            "cube": front_cube_name(apple_cubes, 21.0, 44.0),
            "face": "south",
            "center_uv": [0.5, 0.5],
            "size": [5, 2],
            "color": "#f47a70",
            "center_color": "#ffc1a8",
        },
    ]

    feature_inventory = {
        "skull_cuboids": len(skull_cubes),
        "skull_removed_voxels": skull.removed_voxels,
        "skull_exposed_cut_faces": len(carved_skull_faces),
        "lower_jaw_cuboids": len(jaw_cubes),
        "maw_teeth": len(upper_teeth) + len(lower_teeth),
        "apple_cuboids": len(apple_cubes),
        "apple_removed_voxels": apple.removed_voxels,
        "apple_exposed_cut_faces": len(carved_apple_faces),
        "apple_flesh_drips": len(drip_data),
        "root_limbs": len(root_records),
        "near_root_limbs": sum(record["depth_layer"] == "near" for record in root_records),
        "far_root_limbs": sum(record["depth_layer"] == "far" for record in root_records),
        "root_segments": sum(len(record["segments"]) for record in root_records),
        "identity_patches": len(landmarks),
    }
    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    spec = {
        "schema_version": 1,
        "id": "false_apple_root_beast",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 599,
            "height": 290,
        },
        "subject": {
            "type": "prop_creature",
            "description": (
                "A red apple lure fused to a huge low crawling bark-and-flesh predator, "
                "with a viewer-left gaping maw, a long arched trunk, and splayed root supports"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "Only one flattened three-quarter illustration is observed; rear surfaces and exact limb order are inferred conservatively.",
                "The left, right, top, and bottom alpha silhouettes touch the frame, so every off-frame continuation is unknown.",
                "The dark overlap beneath the apple does not reveal whether it is torso, tongue, or a separate root; it is modeled as a connected fleshy peduncle.",
                "Near and far root assignment follows occlusion and value cues, not a calibrated camera or recovered depth map.",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [170, 192],
            "identity_features": [
                "deep red apple lure joined into the torso",
                "huge carved viewer-left skull with genuine maw negative space",
                "two ragged gum rails and twelve irregular teeth",
                "long arched load-bearing trunk across the body",
                "large foreground root hand and high rear root arch",
                "root limbs separated into observed near and inferred far Z layers",
            ],
            "required_views": [
                "reference-angle", "front", "back", "left", "right", "top", "isometric",
                "maw-closeup", "apple-closeup", "near-root-closeup", "far-root-closeup",
            ],
            "review_targets": [
                "alpha silhouette", "maw negative space", "tooth readability", "apple depth",
                "apple-body junction", "trunk arch", "near/far root separation", "all contacts",
            ],
        },
        "geometry": {"precision": 240},
        "texture": {
            "density": 1,
            "palette_size": 28,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": landmarks,
        "collision": {"width": 7.5, "height": 3.8, "eye_height": 2.65},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "carved-maw-ellipsoids-plus-layered-root-branch-graphs-v1",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z is viewer-facing depth, X spans head-to-rear, Y is up",
            "single_view_hidden_geometry": "inferred_conservatively_not_observed",
            "frame_clipping": ["left", "right", "top", "bottom"],
            "ellipsoids": {
                "skull": {
                    "center": [-38.0, 36.0, 0.0],
                    "radii": [21.0, 18.0, 14.0],
                    "subdivisions": list(skull.grid_shape),
                    "base_occupied_voxels": skull.base_occupied_voxels,
                    "occupied_voxels": skull.occupied_voxels,
                    "removed_voxels": skull.removed_voxels,
                    "greedy_cuboids": len(skull_cubes),
                    "carved_faces": [list(value) for value in carved_skull_faces],
                    "cutouts": [
                        {"role": "open maw scoop", "center": [-44.0, 24.0, 8.0], "radii": [15.5, 12.0, 10.5]},
                        {"role": "recessed eye socket", "center": [-42.0, 38.5, 12.0], "radii": [5.0, 4.5, 4.5]},
                    ],
                },
                "lower_jaw": {
                    "center": [-43.0, 14.0, 1.5],
                    "radii": [17.0, 8.0, 11.5],
                    "subdivisions": list(jaw.grid_shape),
                    "occupied_voxels": jaw.occupied_voxels,
                    "greedy_cuboids": len(jaw_cubes),
                },
                "apple_lure": {
                    "center": [12.0, 39.0, 0.0],
                    "radii": [16.0, 14.0, 12.0],
                    "subdivisions": list(apple.grid_shape),
                    "base_occupied_voxels": apple.base_occupied_voxels,
                    "occupied_voxels": apple.occupied_voxels,
                    "removed_voxels": apple.removed_voxels,
                    "greedy_cuboids": len(apple_cubes),
                    "carved_faces": [list(value) for value in carved_apple_faces],
                    "cutouts": [
                        {"role": "stem dimple", "center": [12.0, 52.5, 0.0], "radii": [4.5, 3.0, 16.0]},
                        {"role": "torn lower-front notch", "center": [11.0, 25.0, 8.0], "radii": [8.0, 4.5, 9.0]},
                    ],
                },
            },
            "branch_graphs": branch_graphs,
            "root_limbs": root_records,
            "feature_inventory": feature_inventory,
            "attachment_contract": {
                "method": "declared shared joints audited against compiler-snapped oriented cuboids",
                "all_semantic_links_declared": True,
                "tree_expected": True,
            },
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        },
    }
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
