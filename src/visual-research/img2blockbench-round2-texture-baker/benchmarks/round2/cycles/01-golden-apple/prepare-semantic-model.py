#!/usr/bin/env python3
"""Author the Round 2 Cycle 1 Golden Apple benchmark model."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image

from semantic_geometry import (
    BranchEdge,
    BranchNode,
    EllipsoidCutout,
    SemanticModelBuilder,
    ellipsoid_cuboids,
    point_to_cuboid_margin,
)


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "image-1.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "228b2a37073397cd167486e5720a21a22f97d89e35e78e7e52f5aeb49207b10f"


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


def axis_aligned_spanning_links(
    cubes: list[dict[str, Any]],
) -> list[tuple[str, str, tuple[float, float, float]]]:
    """Return a deterministic touching-box tree for an occupied volume."""

    def bounds(cube: dict[str, Any]) -> tuple[tuple[float, ...], tuple[float, ...]]:
        center = tuple(float(value) for value in cube["center"])
        size = tuple(float(value) for value in cube["size"])
        return (
            tuple(center[axis] - size[axis] / 2 for axis in range(3)),
            tuple(center[axis] + size[axis] / 2 for axis in range(3)),
        )

    cube_bounds = {cube["name"]: bounds(cube) for cube in cubes}
    cube_names = sorted(cube_bounds)
    reached = {cube_names[0]}
    pending = set(cube_names[1:])
    links: list[tuple[str, str, tuple[float, float, float]]] = []
    while pending:
        candidate = None
        for first in sorted(reached):
            first_lower, first_upper = cube_bounds[first]
            for second in sorted(pending):
                second_lower, second_upper = cube_bounds[second]
                lower = tuple(max(first_lower[axis], second_lower[axis]) for axis in range(3))
                upper = tuple(min(first_upper[axis], second_upper[axis]) for axis in range(3))
                if all(lower[axis] <= upper[axis] + 1e-6 for axis in range(3)):
                    joint = tuple((lower[axis] + upper[axis]) / 2 for axis in range(3))
                    candidate = (first, second, joint)
                    break
            if candidate is not None:
                break
        if candidate is None:
            raise ValueError("apple ellipsoid cuboids are not one connected volume")
        links.append(candidate)
        reached.add(candidate[1])
        pending.remove(candidate[1])
    return links


def main() -> None:
    """Write a deep golden apple with a bitten rim, stem, and four roots."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Golden Apple reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.mode != "RGBA" or opened.size != (600, 704):
            raise ValueError(f"unexpected Golden Apple reference: {opened.mode} {opened.size}")

    materials = {
        "gold": material("#f2b916", "#a96805", "#ffe96a", "gradient", 5),
        "cut_shadow": material("#211511", "#0a0808", "#4a2b20", "gradient", 2),
        "bark": material("#543126", "#261813", "#80503a", "stripes", 3),
        "bark_dark": material("#35221c", "#17100e", "#654033", "solid", 1),
        "bark_light": material("#76503a", "#35231c", "#a06c48", "stripes", 2),
    }

    builder = SemanticModelBuilder()
    builder.add_bone("apple", "root", (0.0, 25.0, 0.0))

    cutouts = (
        EllipsoidCutout(
            center=(-20.5, 26.0, 0.0),
            radii=(8.5, 11.5, 60.0),
            exponent=2.0,
        ),
        EllipsoidCutout(
            center=(0.0, 44.5, 0.0),
            radii=(4.5, 3.5, 60.0),
            exponent=2.0,
        ),
    )
    apple_volume = ellipsoid_cuboids(
        "apple_volume",
        "apple",
        (0.0, 25.0, 0.0),
        (22.0, 20.0, 21.0),
        (20, 20, 18),
        "carved stepped near-spherical golden apple",
        "gold",
        max_cuboids=145,
        exponent=2.05,
        cutouts=cutouts,
    )
    apple_cubes = list(apple_volume.cubes)
    cube_by_name = {cube["name"]: cube for cube in apple_cubes}
    face_axes = {
        "west": (1, 2),
        "east": (1, 2),
        "down": (0, 2),
        "up": (0, 2),
        "north": (0, 1),
        "south": (0, 1),
    }
    carved_face_overrides = []
    for cube_name, face in apple_volume.carved_faces:
        cube = cube_by_name[cube_name]
        axes = face_axes[face]
        face_area = float(cube["size"][axes[0]]) * float(cube["size"][axes[1]])
        if face_area <= 20.0:
            cube["faces"][face] = {"material": "cut_shadow"}
            carved_face_overrides.append((cube_name, face))
    for cube in apple_cubes:
        builder.add_cube(cube)

    attachments = axis_aligned_spanning_links(apple_cubes)
    branch_graphs: list[dict[str, Any]] = []

    def body_attachment(
        point: tuple[float, float, float],
    ) -> tuple[str, tuple[float, float, float]]:
        """Resolve a desired joint to a safely inset carved-body cuboid."""
        containing = [
            (point_to_cuboid_margin(cube, point), cube)
            for cube in apple_cubes
            if point_to_cuboid_margin(cube, point) >= 0
        ]
        if containing:
            _, cube = max(containing, key=lambda item: item[0])
            return cube["name"], point
        best = None
        for cube in apple_cubes:
            center = tuple(float(value) for value in cube["center"])
            size = tuple(float(value) for value in cube["size"])
            inset = tuple(
                max(
                    center[axis] - size[axis] / 2 + 0.2,
                    min(center[axis] + size[axis] / 2 - 0.2, point[axis]),
                )
                for axis in range(3)
            )
            candidate = (sum((inset[axis] - point[axis]) ** 2 for axis in range(3)), cube, inset)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None:
            raise ValueError("carved apple contains no attachment cuboid")
        return best[1]["name"], best[2]

    stem_parent, stem_root = body_attachment((0.0, 40.0, 0.0))
    stem = builder.add_branch_graph(
        "crooked_stem",
        "apple",
        "socket",
        (
            BranchNode("socket", stem_root),
            BranchNode("lower_bend", (-1.45, 45.5, 0.35)),
            BranchNode("middle_bend", (0.3, 48.35, -0.35)),
            BranchNode("upper_bend", (-0.85, 51.0, 0.2)),
            BranchNode("tip", (-0.55, 54.0, 0.0)),
        ),
        (
            BranchEdge(
                "lower", "socket", "lower_bend", 1.55, 1.25,
                "bark_dark", "crooked lower stem", 1, 1.5, 1.2,
            ),
            BranchEdge(
                "middle", "lower_bend", "middle_bend", 1.25, 0.95,
                "bark", "crooked middle stem", 1, 1.2, 0.9,
            ),
            BranchEdge(
                "upper", "middle_bend", "upper_bend", 0.95, 0.7,
                "bark_dark", "crooked upper stem", 1, 0.9, 0.65,
            ),
            BranchEdge(
                "tip", "upper_bend", "tip", 0.7, 0.45,
                "bark_light", "broken stem tip", 1, 0.65, 0.4,
            ),
        ),
        overlap=0.35,
        parent_cube=stem_parent,
    )
    attachments.extend(stem.attachments)
    branch_graphs.append(stem.manifest)

    root_graph_data = (
        (
            "root_back_left",
            -1,
            -1,
            ((-15.5, 15.0, -9.0), (-18.0, 11.5, -12.0), (-20.0, 7.0, -14.5),
             (-22.0, 2.5, -16.0), (-24.0, 0.5, -17.0), (-27.0, 0.0, -18.0),
             (-20.5, -1.2, -21.0), (-23.0, 4.0, -20.0)),
        ),
        (
            "root_front_left",
            -1,
            1,
            ((-5.0, 8.8, 10.0), (-7.0, 4.0, 13.5), (-9.5, -1.0, 16.5),
             (-8.5, -6.0, 19.0), (-11.5, -9.0, 21.5), (-16.0, -8.1, 22.5),
             (-8.5, -9.8, 24.5), (-5.8, -6.8, 21.0)),
        ),
        (
            "root_front_right",
            1,
            1,
            ((5.0, 8.8, 10.0), (7.0, 4.2, 13.5), (9.8, -0.8, 16.5),
             (8.8, -5.8, 19.0), (11.8, -9.0, 21.5), (16.0, -8.0, 22.8),
             (8.8, -9.8, 24.5), (6.0, -6.7, 20.8)),
        ),
        (
            "root_back_right",
            1,
            -1,
            ((15.5, 17.0, -9.0), (18.0, 12.5, -12.0), (20.0, 7.5, -14.5),
             (22.0, 2.5, -16.0), (24.0, 0.5, -17.0), (27.0, 0.0, -18.0),
             (20.5, -1.1, -21.0), (23.0, 4.0, -20.0)),
        ),
    )
    root_quadrants = []
    for root_name, x_sign, z_sign, points in root_graph_data:
        parent_cube, root_point = body_attachment(points[0])
        points = (root_point, *points[1:])
        nodes = tuple(
            BranchNode(name, point)
            for name, point in zip(
                ("root", "knuckle", "elbow", "wrist", "toe", "outer_tip", "inner_tip", "spur"),
                points,
            )
        )
        graph = builder.add_branch_graph(
            root_name,
            "apple",
            "root",
            nodes,
            (
                BranchEdge(
                    "root_knuckle", "root", "knuckle", 4.5, 3.8,
                    "bark", "gnarled weight-bearing root shoulder", 2, 4.2, 3.5,
                ),
                BranchEdge(
                    "knuckle_elbow", "knuckle", "elbow", 3.8, 3.15,
                    "bark_dark", "angular root upper limb", 1, 3.5, 2.85,
                ),
                BranchEdge(
                    "elbow_wrist", "elbow", "wrist", 3.15, 2.4,
                    "bark", "gnarled root lower limb", 2, 2.85, 2.15,
                ),
                BranchEdge(
                    "wrist_toe", "wrist", "toe", 2.4, 1.8,
                    "bark_light", "broad root palm", 1, 2.15, 1.55,
                ),
                BranchEdge(
                    "outer_rootlet", "toe", "outer_tip", 1.8, 0.75,
                    "bark_dark", "outer splayed rootlet", 1, 1.55, 0.6,
                ),
                BranchEdge(
                    "inner_rootlet", "toe", "inner_tip", 1.65, 0.7,
                    "bark", "inner splayed rootlet", 1, 1.4, 0.55,
                ),
                BranchEdge(
                    "raised_spur", "wrist", "spur", 1.45, 0.6,
                    "bark_light", "raised broken root spur", 1, 1.2, 0.5,
                ),
            ),
            overlap=0.45,
            parent_cube=parent_cube,
        )
        attachments.extend(graph.attachments)
        branch_graphs.append(graph.manifest)
        root_quadrants.append(
            {
                "name": root_name,
                "x_sign": x_sign,
                "z_sign": z_sign,
                "root": list(points[0]),
                "terminal": list(points[4]),
            }
        )

    def front_cube_name(x: float, y: float) -> str:
        """Choose the frontmost apple cuboid containing an X/Y paint point."""
        candidates = []
        for cube in apple_cubes:
            center = tuple(float(value) for value in cube["center"])
            size = tuple(float(value) for value in cube["size"])
            if (
                center[0] - size[0] / 2 <= x <= center[0] + size[0] / 2
                and center[1] - size[1] / 2 <= y <= center[1] + size[1] / 2
            ):
                candidates.append((center[2] + size[2] / 2, cube["name"]))
        if not candidates:
            raise ValueError(f"no front apple face contains paint point {(x, y)}")
        return max(candidates)[1]

    landmarks = [
        {
            "name": "broad_upper_glint_top",
            "cube": front_cube_name(4.0, 36.0),
            "face": "south",
            "center_uv": [0.63, 0.36],
            "size": [15, 2],
            "color": "#ffef86",
            "center_color": "#fffbd2",
        },
        {
            "name": "broad_upper_glint_middle",
            "cube": front_cube_name(5.0, 34.0),
            "face": "south",
            "center_uv": [0.64, 0.5],
            "size": [13, 2],
            "color": "#ffef86",
            "center_color": "#fffbd2",
        },
        {
            "name": "broad_upper_glint_lower",
            "cube": front_cube_name(5.0, 32.0),
            "face": "south",
            "center_uv": [0.65, 0.64],
            "size": [10, 2],
            "color": "#ffe66b",
            "center_color": "#fffbd2",
        },
        {
            "name": "right_glint_top",
            "cube": front_cube_name(13.0, 34.0),
            "face": "south",
            "center_uv": [0.48, 0.4],
            "size": [5, 2],
            "color": "#ffe66b",
            "center_color": "#fffbd2",
        },
        {
            "name": "right_glint_middle",
            "cube": front_cube_name(13.0, 32.0),
            "face": "south",
            "center_uv": [0.52, 0.5],
            "size": [5, 2],
            "color": "#ffe66b",
            "center_color": "#fffbd2",
        },
        {
            "name": "right_glint_lower",
            "cube": front_cube_name(13.0, 30.0),
            "face": "south",
            "center_uv": [0.56, 0.6],
            "size": [4, 2],
            "color": "#ffe66b",
            "center_color": "#fffbd2",
        },
        {
            "name": "left_bruise",
            "cube": front_cube_name(-8.0, 34.0),
            "face": "south",
            "center_uv": [0.46, 0.35],
            "size": [5, 4],
            "color": "#a86711",
            "center_color": "#c88718",
        },
        {
            "name": "lower_bruise",
            "cube": front_cube_name(3.0, 11.0),
            "face": "south",
            "center_uv": [0.66, 0.46],
            "size": [7, 3],
            "color": "#aa6d13",
            "center_color": "#d99b21",
        },
    ]

    feature_inventory = {
        "apple_volume_cuboids": len(apple_cubes),
        "negative_space_cutouts": len(cutouts),
        "carved_voxels": apple_volume.removed_voxels,
        "dark_exposed_cut_faces": len(carved_face_overrides),
        "stem_segments": len(stem.cubes),
        "root_limbs": 4,
        "root_segments": sum(
            len(graph["edges"][edge_index]["segments"])
            for graph in branch_graphs[1:]
            for edge_index in range(len(graph["edges"]))
        ),
        "identity_patches": len(landmarks),
    }
    reference_name = Path(os.path.relpath(REFERENCE.resolve(), OUTPUT.parent.resolve())).as_posix()
    spec = {
        "schema_version": 1,
        "id": "golden_apple_rooted",
        "reference": {
            "image": reference_name,
            "sha256": EXPECTED_SHA256,
            "width": 600,
            "height": 704,
        },
        "subject": {
            "type": "prop_creature",
            "description": (
                "Near-spherical luminous golden apple with a left bite-like dark cut, "
                "top dimple, crooked stem, and four gnarled walking roots"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "The single frontal illustration does not observe the rear apple "
                "surface or exact root depth",
                "The source is clipped by the left, right, and bottom frame edges, "
                "so root continuation is unknown",
            ],
        },
        "quality_contract": {
            "complexity": "moderate",
            "target_cuboids": [145, 180],
            "identity_features": [
                "deep near-spherical golden apple body",
                "top dimple with crooked brown stem",
                "dark bite-like cut into the viewer-left face",
                "four connected gnarled roots occupying all X/Z quadrants",
                "pale highlights and ochre bruise patches",
            ],
            "required_views": [
                "reference-angle", "front", "back", "left", "right", "top", "isometric",
                "bite-closeup", "stem-closeup", "root-joints-closeup",
            ],
            "review_targets": [
                "alpha silhouette", "apple roundness", "true body depth", "bite identity",
                "stem connection", "four root quadrants", "root joints", "texture patches",
            ],
        },
        "geometry": {"precision": 60},
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
        "collision": {"width": 2.55, "height": 3.65, "eye_height": 2.8},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "carved-ellipsoid-plus-branch-graphs-golden-apple-v2",
            "source_mesh": None,
            "source_projection": False,
            "source_skin_cuboids": 0,
            "anatomical_axis": "+Z front, X width, Y up",
            "single_view_hidden_geometry": "inferred_conservatively_not_observed",
            "frame_clipping": ["left", "right", "bottom"],
            "ellipsoid": {
                "center": [0.0, 25.0, 0.0],
                "radii": [22.0, 20.0, 21.0],
                "subdivisions": list(apple_volume.grid_shape),
                "exponent": 2.05,
                "base_occupied_voxels": apple_volume.base_occupied_voxels,
                "occupied_voxels": apple_volume.occupied_voxels,
                "removed_voxels": apple_volume.removed_voxels,
                "greedy_cuboids_after_carving": len(apple_volume.cubes),
                "voxel_size": list(apple_volume.voxel_size),
                "cutouts": [
                    {
                        "role": "viewer-left bite",
                        "center": [-20.5, 26.0, 0.0],
                        "radii": [8.5, 11.5, 60.0],
                        "exponent": 2.0,
                    },
                    {
                        "role": "top stem dimple",
                        "center": [0.0, 44.5, 0.0],
                        "radii": [4.5, 3.5, 60.0],
                        "exponent": 2.0,
                    },
                ],
                "dark_exposed_faces": [list(value) for value in carved_face_overrides],
            },
            "feature_inventory": feature_inventory,
            "root_quadrants": root_quadrants,
            "branch_graphs": branch_graphs,
            "attachment_contract": {
                "method": (
                    "ellipsoid touching-box tree plus named graph joints and "
                    "compiled oriented-cuboid audit"
                ),
                "all_semantic_appendage_links_declared": True,
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
