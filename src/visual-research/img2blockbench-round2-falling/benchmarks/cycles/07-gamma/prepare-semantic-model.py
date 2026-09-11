#!/usr/bin/env python3
"""Author the Cycle 7 volumetric Gamma benchmark model."""

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
    point_to_cuboid_margin,
    segment_cube,
)


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "benchmarks" / "references" / "07-gamma.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "26cb7dea9090c5a1af9e9caba210472bffe0405bf2c17375132a3abb90dac63b"


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
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    role: str,
    material_name: str,
    *,
    rotation: tuple[float, float, float] = (0, 0, 0),
    origin: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """Create one semantic cuboid without source-image projection."""
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


def nearest_attachment(
    cubes: list[dict[str, Any]], point: tuple[float, float, float]
) -> tuple[str, tuple[float, float, float]]:
    """Resolve an intended joint to a safely inset point in a robe cuboid."""
    containing = [
        (point_to_cuboid_margin(cube, point), cube)
        for cube in cubes
        if point_to_cuboid_margin(cube, point) >= 0
    ]
    if containing:
        _, cube = max(containing, key=lambda item: item[0])
        return cube["name"], point
    best: tuple[float, dict[str, Any], tuple[float, float, float]] | None = None
    for cube in cubes:
        center = tuple(float(value) for value in cube["center"])
        size = tuple(float(value) for value in cube["size"])
        if any(float(value) for value in cube["rotation"]):
            continue
        inset = tuple(
            max(
                center[axis] - size[axis] / 2 + 0.2,
                min(center[axis] + size[axis] / 2 - 0.2, point[axis]),
            )
            for axis in range(3)
        )
        candidate = (math.dist(point, inset), cube, inset)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        raise ValueError("cannot attach to an empty robe")
    return best[1]["name"], best[2]


def main() -> None:
    """Write Gamma as a deep robe, split head, claws, rings, and four legs."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Gamma reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.mode != "RGBA" or opened.size != (592, 899):
            raise ValueError(f"unexpected Gamma reference: {opened.mode} {opened.size}")

    materials = {
        "void": material("#111217", "#07080b", "#282a31", "dither", 5),
        "robe": material("#24262e", "#101117", "#444752", "gradient", 7),
        "robe_mid": material("#30323a", "#15171d", "#555864", "stripes", 6),
        "robe_edge": material("#17191f", "#08090c", "#353844", "dither", 4),
        "flesh": material("#342024", "#130e12", "#603238", "dither", 3),
        "blood": material("#592124", "#280f13", "#943735", "stripes", 2),
        "maw": material("#170d12", "#050407", "#4a1e27", "gradient", 2),
        "tooth": material("#c7c2b4", "#74716c", "#f2eee1", "dither", 2),
        "mask": material("#d6d5d0", "#8c8b88", "#f5f3ed", "gradient", 4),
        "mask_shadow": material("#87888a", "#46474b", "#bababb", "dither", 3),
        "joint": material("#292d33", "#0d0f12", "#666d75", "dither", 2),
        "silver": material("#9ca4aa", "#41474d", "#e1e6e8", "stripes", 2),
        "silver_dark": material("#555d64", "#252a30", "#8d969d", "dither", 2),
    }

    builder = SemanticModelBuilder()
    builder.add_bone("robe", "root", (2.5, 34.0, 0.0))
    builder.add_bone("head", "robe", (4.0, 68.0, 0.0))

    robe_cubes: list[dict[str, Any]] = []

    def add_robe(cube: dict[str, Any]) -> None:
        builder.add_cube(cube)
        robe_cubes.append(cube)

    add_robe(box("torso_core", "robe", (3.0, 50.0, 0.0), (22.0, 40.0, 12.0),
                 "narrow deep upper robe torso", "robe"))
    add_robe(box("left_hanging_fold", "robe", (-7.5, 35.0, -1.0), (8.0, 52.0, 10.0),
                 "long viewer-left hanging robe fold", "robe_edge"))
    add_robe(box("center_hanging_fold", "robe", (0.5, 31.5, 2.0), (9.0, 57.0, 10.0),
                 "central hanging robe fold", "void"))
    add_robe(box("right_hanging_fold", "robe", (10.0, 36.0, -1.5), (8.0, 62.0, 10.0),
                 "long viewer-right hanging robe fold", "robe_mid"))

    hem_paths = (
        ("hem_far_left", (-6.0, 34.0, -1.8), (-22.0, 2.4, -1.5), 7.2, "robe_edge"),
        ("hem_left", (-3.0, 35.0, 2.6), (-11.0, 2.0, 3.8), 8.0, "robe_mid"),
        ("hem_center", (2.0, 34.0, -2.5), (1.0, 1.8, -3.8), 8.5, "void"),
        ("hem_right", (7.0, 38.0, 2.2), (12.5, 2.2, 3.8), 8.0, "robe"),
        ("hem_far_right", (10.0, 35.0, -2.0), (21.5, 2.6, -1.2), 7.2, "robe_edge"),
    )
    for name, start, end, width, paint in hem_paths:
        add_robe(
            segment_cube(
                name,
                "robe",
                start,
                end,
                (width, 8.5),
                "flared torn robe hem panel",
                paint,
                overlap=0.65,
            )
        )

    head_core = box(
        "head_core",
        "head",
        (4.0, 73.0, 0.0),
        (18.0, 12.0, 9.0),
        "deep split cranium and upper chest anchor",
        "robe_edge",
    )
    builder.add_cube(head_core)
    attachments: list[tuple[str, str, tuple[float, float, float]]] = [
        ("torso_core", "head_core", (4.0, 68.0, 0.0))
    ]
    for cube, joint in (
        ("left_hanging_fold", (-5.0, 60.0, 0.0)),
        ("center_hanging_fold", (1.0, 59.0, 1.0)),
        ("right_hanging_fold", (9.0, 62.0, -1.0)),
        ("hem_far_left", (-6.0, 34.0, -1.8)),
        ("hem_left", (-3.0, 35.0, 2.6)),
        ("hem_center", (2.0, 34.0, -2.5)),
        ("hem_right", (7.0, 38.0, 2.2)),
        ("hem_far_right", (10.0, 35.0, -2.0)),
    ):
        attachments.append(("torso_core", cube, joint))

    graph_manifests: list[dict[str, Any]] = []

    split = builder.add_branch_graph(
        "split_head",
        "head",
        "skull_root",
        (
            BranchNode("skull_root", (4.0, 74.0, 0.0)),
            BranchNode("left_cleft", (0.0, 80.0, 1.5)),
            BranchNode("left_peak", (-2.0, 86.0, 2.5)),
            BranchNode("right_cleft", (8.0, 80.5, -1.5)),
            BranchNode("right_peak", (11.0, 87.0, -2.5)),
        ),
        (
            BranchEdge("left_base", "skull_root", "left_cleft", 4.5, 3.4,
                       "flesh", "viewer-left half of split cranium", 2, 5.2, 4.2),
            BranchEdge("left_peak", "left_cleft", "left_peak", 3.2, 1.7,
                       "blood", "bloodied viewer-left split head peak", 2, 4.0, 2.4),
            BranchEdge("right_base", "skull_root", "right_cleft", 4.5, 3.2,
                       "robe_edge", "viewer-right half of split cranium", 2, 5.2, 4.0),
            BranchEdge("right_peak", "right_cleft", "right_peak", 3.0, 1.6,
                       "flesh", "viewer-right split head peak", 2, 3.8, 2.2),
        ),
        overlap=0.45,
        parent_cube="head_core",
    )
    attachments.extend(split.attachments)
    graph_manifests.append(split.manifest)

    # Eight independent hooked chains reproduce the asymmetric upper fan. The
    # three explicit Z layers ensure that this reads as a deep maw rather than
    # a flat antler silhouette.
    mandible_paths = (
        ("mandible_1", (-3.5, 70.0, -4.0), (-12.5, 66.5, -5.0),
         (-21.0, 66.5, -5.2), (-18.0, 62.5, -5.0)),
        ("mandible_2", (-2.0, 72.0, 0.0), (-13.0, 72.0, 0.2),
         (-21.0, 77.0, 0.0), (-18.5, 73.5, 0.2)),
        ("mandible_3", (-0.5, 74.0, 4.0), (-10.0, 77.5, 5.0),
         (-18.0, 84.0, 5.2), (-15.5, 80.2, 5.0)),
        ("mandible_4", (2.0, 75.5, -4.0), (-1.5, 83.0, -5.0),
         (-4.0, 90.0, -5.2), (-2.2, 86.7, -5.0)),
        ("mandible_5", (4.0, 76.0, 0.0), (3.0, 84.0, 0.4),
         (6.0, 89.0, 0.0), (4.8, 85.6, 0.2)),
        ("mandible_6", (6.0, 75.5, 4.0), (8.5, 83.5, 5.0),
         (7.0, 90.0, 5.2), (8.8, 86.6, 5.0)),
        ("mandible_7", (8.0, 74.0, -4.0), (13.0, 82.0, -5.0),
         (12.0, 89.5, -5.2), (13.8, 86.0, -5.0)),
        ("mandible_8", (10.0, 71.0, 4.0), (16.0, 77.0, 5.0),
         (17.0, 84.5, 5.2), (15.5, 80.8, 5.0)),
    )
    for chain_name, root, knuckle, tip, hook in mandible_paths:
        result = builder.add_branch_graph(
            chain_name,
            "head",
            "root",
            (
                BranchNode("root", root),
                BranchNode("knuckle", knuckle),
                BranchNode("tip", tip),
                BranchNode("hook", hook),
            ),
            (
                BranchEdge("inner", "root", "knuckle", 3.1, 2.0,
                           "robe_edge", "upper hooked jaw mandible not an antler", 2,
                           3.2, 2.1),
                BranchEdge("outer", "knuckle", "tip", 1.95, 0.72,
                           "flesh", "blood-darkened cutting arm of upper mandible", 2,
                           2.05, 0.82),
                BranchEdge("hook", "tip", "hook", 0.85, 0.38,
                           "blood", "inward hooked bloodied terminal fang", 1,
                           0.9, 0.44),
            ),
            overlap=0.42,
            parent_cube="head_core",
        )
        attachments.extend(result.attachments)
        graph_manifests.append(result.manifest)

    # A narrow vertical cavity and alternating hard teeth are the torso's
    # second face. All pieces project forward from real body depth.
    builder.add_bone("chest_maw", "head", (1.0, 66.0, 4.0))
    builder.add_cube(box("chest_maw", "chest_maw", (1.0, 65.5, 4.7), (5.0, 17.0, 1.4),
                         "vertical chest maw cavity", "maw"))
    attachments.append(("torso_core", "chest_maw", (1.0, 65.0, 4.0)))
    for index, y in enumerate((59.7, 62.3, 64.9, 67.5, 70.1), start=1):
        side = -1 if index % 2 else 1
        name = f"maw_tooth_{index}"
        center = (1.0 + side * 1.65, y, 5.55)
        builder.add_cube(
            box(name, "chest_maw", center, (1.25, 1.5, 0.8),
                "alternating tooth in vertical chest maw", "tooth",
                rotation=(0, 0, side * 18), origin=(1.0 + side * 2.05, y, 5.1))
        )
        attachments.append(("chest_maw", name, (center[0], y, 5.2)))

    # High off-center expressionless white mask, built as a stepped oval.
    builder.add_bone("mask", "head", (12.5, 74.5, 4.4))
    builder.add_cube(
        segment_cube(
            "mask_mount",
            "mask",
            (12.5, 74.5, 4.2),
            (12.5, 74.5, 7.2),
            (0.7, 0.7),
            "short hidden mount holding mask ahead of mandibles",
            "mask_shadow",
            overlap=0.2,
        )
    )
    attachments.append(("head_core", "mask_mount", (12.5, 74.5, 4.2)))
    mask_layers = (
        ("mask_1", (12.5, 71.1, 8.0), (3.6, 1.7, 2.0)),
        ("mask_2", (12.7, 72.8, 8.0), (5.0, 2.0, 2.0)),
        ("mask_3", (12.85, 74.8, 8.0), (6.0, 2.1, 2.0)),
        ("mask_4", (12.8, 76.8, 8.0), (5.5, 2.0, 2.0)),
        ("mask_5", (12.5, 78.5, 8.0), (3.8, 1.5, 2.0)),
    )
    for name, center, size in mask_layers:
        builder.add_cube(box(name, "mask", center, size, "stepped expressionless mask oval", "mask"))
    attachments.extend(
        [
            ("mask_mount", "mask_3", (12.5, 74.5, 7.2)),
            ("mask_1", "mask_2", (12.3, 71.87, 8.0)),
            ("mask_2", "mask_3", (12.3, 73.775, 8.0)),
            ("mask_3", "mask_4", (12.3, 75.825, 8.0)),
            ("mask_4", "mask_5", (12.3, 77.775, 8.0)),
        ]
    )
    for name, center, size, role in (
        ("mask_left_eye", (11.45, 76.0, 9.1), (0.95, 0.45, 0.35), "left blank mask eye"),
        ("mask_right_eye", (14.0, 76.0, 9.1), (0.95, 0.45, 0.35), "right blank mask eye"),
        ("mask_mouth", (12.75, 73.1, 9.1), (1.9, 0.3, 0.35), "expressionless mask mouth"),
    ):
        builder.add_cube(box(name, "mask", center, size, role, "mask_shadow"))
        attachments.append(("mask_3" if "eye" in name else "mask_2", name,
                            (center[0], 75.82 if "eye" in name else center[1], 8.97)))

    # Four and only four articulated mechanical legs emerge under the robe.
    leg_paths = (
        ("mechanical_leg_1", (-9.0, 29.0, -4.0), (-21.0, 21.0, -5.0),
         (-28.0, 11.0, -5.5), (-31.0, 0.7, -6.0)),
        ("mechanical_leg_2", (-5.0, 28.0, 6.5), (-14.0, 18.0, 7.5),
         (-16.0, 8.0, 8.0), (-23.0, 0.7, 8.5)),
        ("mechanical_leg_3", (9.0, 28.5, 6.5), (17.0, 18.0, 7.5),
         (17.0, 8.0, 8.0), (23.0, 0.7, 8.5)),
        ("mechanical_leg_4", (13.0, 29.5, -4.0), (23.0, 21.0, -5.0),
         (29.0, 11.0, -5.5), (31.0, 0.7, -6.0)),
    )
    leg_graphs = []
    for leg_name, intended_root, knee, ankle, toe in leg_paths:
        parent_cube, root = nearest_attachment(robe_cubes, intended_root)
        result = builder.add_branch_graph(
            leg_name,
            "robe",
            "hip",
            (
                BranchNode("hip", root),
                BranchNode("knee", knee),
                BranchNode("ankle", ankle),
                BranchNode("toe", toe),
            ),
            (
                BranchEdge("upper", "hip", "knee", 4.0, 3.2, "joint",
                           "upper mechanical leg strut", 1, 3.2, 2.5),
                BranchEdge("lower", "knee", "ankle", 3.2, 2.2, "robe_edge",
                           "lower mechanical leg strut", 1, 2.5, 1.8),
                BranchEdge("toe", "ankle", "toe", 2.2, 0.8, "silver_dark",
                           "terminal hooked mechanical claw toe", 1, 1.8, 0.85),
            ),
            overlap=0.5,
            parent_cube=parent_cube,
        )
        attachments.extend(result.attachments)
        graph_manifests.append(result.manifest)
        leg_graphs.append(result)
        cube_by_name = {cube["name"]: cube for cube in builder.cubes}
        for label, joint, first, second, size in (
            ("knee_hinge", knee, result.cubes[0], result.cubes[1], 4.2),
            ("ankle_hinge", ankle, result.cubes[1], result.cubes[2], 3.2),
        ):
            hinge_name = f"{leg_name}_{label}"
            builder.add_cube(box(hinge_name, cube_by_name[first]["bone"], joint,
                                 (size, size, size), "visible mechanical pivot hinge", "joint"))
            attachments.append((first, hinge_name, joint))
            attachments.append((hinge_name, second, joint))

    # Two unequal hanging silver rings, each with an octagonal connected loop.
    ring_inventory = []
    for ring_name, center, radius in (
        ("upper_ring", (6.2, 53.5, 8.0), 1.25),
        ("lower_ring", (1.7, 36.5, 8.2), 1.65),
    ):
        builder.add_bone(ring_name, "robe", (center[0], center[1] + radius, 4.0))
        hanger_name = f"{ring_name}_hanger"
        hanger_start = (center[0], center[1] + radius, 5.8)
        hanger_end = (center[0], center[1] + radius, center[2])
        builder.add_cube(segment_cube(hanger_name, ring_name, hanger_start, hanger_end,
                                      (0.45, 0.45), "silver ring hanger", "silver_dark",
                                      overlap=0.2))
        attachments.append(("torso_core", hanger_name, hanger_start))
        points = [
            (
                center[0] + math.cos(math.radians(90 - index * 45)) * radius,
                center[1] + math.sin(math.radians(90 - index * 45)) * radius,
                center[2],
            )
            for index in range(8)
        ]
        segment_names = []
        for index in range(8):
            segment_name = f"{ring_name}_segment_{index + 1}"
            builder.add_cube(segment_cube(segment_name, ring_name, points[index],
                                          points[(index + 1) % 8], (0.38, 0.38),
                                          "octagonal silver hanging ring", "silver",
                                          overlap=0.12))
            segment_names.append(segment_name)
            if index == 0:
                attachments.append((hanger_name, segment_name, points[0]))
            else:
                attachments.append((segment_names[index - 1], segment_name, points[index]))
        attachments.append((segment_names[-1], segment_names[0], points[0]))
        ring_inventory.append({"name": ring_name, "radius": radius, "segments": segment_names})

    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    feature_inventory = {
        "upper_mandible_chains": 8,
        "mandible_segments": 40,
        "mandible_depth_layers": 3,
        "split_head_halves": 2,
        "vertical_chest_maws": 1,
        "maw_teeth": 5,
        "expressionless_masks": 1,
        "silver_ring_assemblies": 2,
        "ring_segments": 16,
        "mechanical_leg_chains": 4,
        "mechanical_leg_segments": 12,
        "mechanical_hinges": 8,
        "mechanical_leg_depth_layers": 2,
    }
    spec = {
        "schema_version": 1,
        "id": "gamma_abnormality",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 592,
            "height": 899,
        },
        "subject": {
            "type": "character",
            "description": (
                "Tall flared black-robed Gamma with an off-center white mask, split "
                "head, vertical chest maw, eight bloodied upper mandibles, two silver "
                "rings, and four hinged mechanical legs"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "The transparent source supplies only one oblique frontal view; back "
                "surfaces and exact appendage depth are conservative semantic inference",
                "Source rights and original character licensing are unknown; the reference "
                "is retained only in the private ignored benchmark workspace",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [95, 150],
            "identity_features": [
                "tall wide grey-black flared robe",
                "high off-center expressionless white mask",
                "split head halves framing a vertical chest maw",
                "exactly eight bloodied upper mandible claw chains",
                "two unequal hanging silver ring assemblies",
                "exactly four clawed mechanical leg chains with visible hinges and toes",
                "three upper appendage depth layers and two leg depth layers",
            ],
            "required_views": [
                "reference-angle", "front", "back", "left", "right", "top",
                "isometric", "face-split-head", "maw-eight-claw", "ring",
                "leg-joint",
            ],
            "review_targets": [
                "source silhouette", "mask placement", "mandible count", "split head",
                "maw identity", "ring asymmetry", "mechanical leg topology", "true depth",
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
        "landmarks": [],
        "collision": {"width": 1.4, "height": 5.4, "eye_height": 4.7},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "validated-tapered-attachment-graph-gamma-v1",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "single_view_hidden_geometry": "inferred_conservatively_not_observed",
            "upper_fan_interpretation": "mandibles and split head, not antlers or weapons",
            "lower_strut_interpretation": "four mechanical legs, not antlers or weapons",
            "feature_inventory": feature_inventory,
            "branch_graphs": graph_manifests,
            "ring_assemblies": ring_inventory,
            "attachment_contract": {
                "method": "named graph joints plus compiled oriented-cuboid margin audit",
                "external_root_attachments_included": True,
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
