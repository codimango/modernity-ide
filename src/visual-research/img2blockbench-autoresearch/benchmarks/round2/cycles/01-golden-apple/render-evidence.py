#!/usr/bin/env python3
"""Render and measure deterministic Golden Apple review evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from img2blockbench import build_texture, read_json
from semantic_evidence import (
    STANDARD_VIEWS,
    alpha_mask,
    alpha_silhouette_metrics,
    camera_basis,
    contact_sheet,
    cube_vertices,
    foreground_mask,
    height_normalized_mask,
    render_view,
)
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "image-1.png"
OUTPUT = CYCLE / "render"
LIGHT_BACKGROUND = (236, 238, 241, 255)
REFERENCE_DIRECTION = (0.0, 0.025, 1.0)


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return exact world bounds for all or selected oriented cuboids."""
    vertices = np.concatenate(
        [
            cube_vertices(spec, cube)
            for cube in spec["cubes"]
            if names is None or cube["name"] in names
        ]
    )
    return vertices.min(axis=0), vertices.max(axis=0)


def project_point(
    spec: dict[str, Any],
    point: tuple[float, float, float],
    direction: tuple[float, float, float],
) -> tuple[float, float]:
    """Project one world point using the full-model render transform."""
    right, up, _ = camera_basis(direction)
    all_vertices = np.concatenate([cube_vertices(spec, cube) for cube in spec["cubes"]])
    projected = np.column_stack((all_vertices @ right, all_vertices @ up))
    lower = projected.min(axis=0)
    upper = projected.max(axis=0)
    margin = 42
    scale = min(
        (640 - margin * 2) / max(1e-6, upper[0] - lower[0]),
        (640 - margin * 2) / max(1e-6, upper[1] - lower[1]),
    )
    center = (lower + upper) / 2
    vector = np.asarray(point, dtype=np.float64)
    return (
        float((vector @ right - center[0]) * scale + 320),
        float(320 - (vector @ up - center[1]) * scale),
    )


def silhouette_overlay(reference: Image.Image, rendered: Image.Image) -> Image.Image:
    """Show source/model occupancy and intersection after height normalization."""
    source, _ = height_normalized_mask(alpha_mask(reference), target_height=496)
    model, _ = height_normalized_mask(
        foreground_mask(rendered, LIGHT_BACKGROUND[:3]), target_height=496
    )
    width = max(source.shape[1], model.shape[1]) + 16
    source_canvas = np.zeros((496, width), dtype=bool)
    model_canvas = np.zeros((496, width), dtype=bool)
    source_left = (width - source.shape[1]) // 2
    model_left = (width - model.shape[1]) // 2
    source_canvas[:, source_left : source_left + source.shape[1]] = source
    model_canvas[:, model_left : model_left + model.shape[1]] = model
    pixels = np.full((496, width, 3), 245, dtype=np.uint8)
    pixels[source_canvas] = (214, 74, 66)
    pixels[model_canvas] = (47, 144, 185)
    pixels[source_canvas & model_canvas] = (41, 44, 48)
    return Image.fromarray(pixels, mode="RGB")


def main() -> None:
    """Write real multiview renders and machine-checkable benchmark metrics."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    views: dict[str, Image.Image] = {}
    for name, direction in STANDARD_VIEWS.items():
        views[name] = render_view(
            spec,
            direction,
            atlas_image=atlas,
            placements=placements,
            background=LIGHT_BACKGROUND,
        )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)
    views["reference_angle"] = render_view(
        spec,
        REFERENCE_DIRECTION,
        atlas_image=atlas,
        placements=placements,
        background=LIGHT_BACKGROUND,
    )
    views["reference_angle"].save(OUTPUT / "reference-angle.png", optimize=True)

    cube_names = {cube["name"] for cube in spec["cubes"]}
    cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
    branch_graphs = spec["generation"]["branch_graphs"]
    stem_graph = next(graph for graph in branch_graphs if graph["name"] == "crooked_stem")
    right_root_graph = next(
        graph for graph in branch_graphs if graph["name"] == "root_front_right"
    )
    dark_cut_names = {
        name
        for name, _ in spec["generation"]["ellipsoid"]["dark_exposed_faces"]
        if float(cube_by_name[name]["center"][0]) < -8.0
    }
    top_dimple_names = {
        name
        for name, _ in spec["generation"]["ellipsoid"]["dark_exposed_faces"]
        if float(cube_by_name[name]["center"][1]) > 35.0
    }
    detail_selections = {
        "bite closeup": {
            name
            for name in cube_names
            if name in dark_cut_names
            or (
                name.startswith("apple_volume_")
                and float(cube_by_name[name]["center"][0]) < -8.0
            )
        },
        "stem closeup": {
            name
            for name in cube_names
            if name.startswith("crooked_stem")
            or name == stem_graph["parent_cube"]
            or name in top_dimple_names
        },
        "root joints closeup": {
            name
            for name in cube_names
            if name.startswith("root_front_right")
            or name == right_root_graph["parent_cube"]
        },
    }
    details = {
        label: render_view(
            spec,
            (0.2, 0.08, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=selection,
            background=LIGHT_BACKGROUND,
        )
        for label, selection in detail_selections.items()
    }
    for label, image in details.items():
        image.save(OUTPUT / f"{label.replace(' ', '-')}.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    flattened_reference = Image.new("RGBA", reference.size, LIGHT_BACKGROUND)
    flattened_reference.alpha_composite(reference)
    contact_sheet(
        flattened_reference,
        {
            "reference angle": views["reference_angle"],
            "front": views["front"],
            "back": views["back"],
            "left": views["left"],
            "right": views["right"],
            "top": views["top"],
            "isometric": views["isometric"],
            **details,
        },
        tile=(340, 300),
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)
    silhouette_overlay(reference, views["reference_angle"]).save(
        OUTPUT / "silhouette-overlap.png", optimize=True
    )

    reference_keypoints = {
        "apple_bottom": (327, 529),
        "apple_right_equator": (554, 300),
        "bite_inner_cusp": (151, 354),
        "left_outer_root_tip": (8, 590),
        "right_outer_root_tip": (593, 580),
        "stem_socket": (294, 145),
        "stem_tip": (294, 2),
    }
    world_keypoints = {
        "apple_bottom": (0.0, 5.0, 0.0),
        "apple_right_equator": (22.0, 25.0, 8.0),
        "bite_inner_cusp": (-13.75, 25.0, 18.0),
        "left_outer_root_tip": (-27.0, 0.0, -18.0),
        "right_outer_root_tip": (27.0, 0.0, -18.0),
        "stem_socket": (0.0, 41.5, 1.7),
        "stem_tip": (-0.55, 54.0, 0.0),
    }
    rendered_keypoints = {
        name: project_point(spec, point, REFERENCE_DIRECTION)
        for name, point in world_keypoints.items()
    }
    silhouette = alpha_silhouette_metrics(
        reference,
        views["reference_angle"],
        reference_keypoints=reference_keypoints,
        rendered_keypoints=rendered_keypoints,
        rendered_background=LIGHT_BACKGROUND[:3],
    )

    all_lower, all_upper = bounds_for(spec)
    full_extents = all_upper - all_lower
    apple_names = {
        name
        for name in cube_names
        if name.startswith("apple_volume_")
    }
    apple_lower, apple_upper = bounds_for(spec, apple_names)
    apple_extents = apple_upper - apple_lower
    root_names = {name for name in cube_names if name.startswith("root_")}
    root_lower, root_upper = bounds_for(spec, root_names)

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    quadrants = {
        (int(record["x_sign"]), int(record["z_sign"]))
        for record in spec["generation"]["root_quadrants"]
    }
    actual_inventory = {
        "apple_volume_cuboids": sum(name.startswith("apple_volume_") for name in cube_names),
        "negative_space_cutouts": len(spec["generation"]["ellipsoid"]["cutouts"]),
        "carved_voxels": spec["generation"]["ellipsoid"]["removed_voxels"],
        "dark_exposed_cut_faces": len(
            spec["generation"]["ellipsoid"]["dark_exposed_faces"]
        ),
        "stem_segments": sum(name.startswith("crooked_stem_") for name in cube_names),
        "root_limbs": len(spec["generation"]["root_quadrants"]),
        "root_segments": sum(name.startswith("root_") for name in cube_names),
        "identity_patches": len(spec["landmarks"]),
    }
    proportions = {
        "model_extents": [round(float(value), 6) for value in full_extents],
        "apple_extents": [round(float(value), 6) for value in apple_extents],
        "apple_depth_to_width": round(float(apple_extents[2] / apple_extents[0]), 6),
        "apple_width_to_height": round(float(apple_extents[0] / apple_extents[1]), 6),
        "root_extents": [round(float(value), 6) for value in root_upper - root_lower],
    }
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v2-light-review",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "source_projection": False,
        "reference_rights": "unknown; private ignored benchmark reference only",
        "single_view_hidden_geometry": spec["generation"]["single_view_hidden_geometry"],
        "negative_space": {
            "method": "voxel-center ellipsoid CSG subtraction before greedy cuboid merging",
            "base_occupied_voxels": spec["generation"]["ellipsoid"][
                "base_occupied_voxels"
            ],
            "occupied_voxels_after_carving": spec["generation"]["ellipsoid"][
                "occupied_voxels"
            ],
            "removed_voxels": spec["generation"]["ellipsoid"]["removed_voxels"],
            "black_proxy_solids": sum(
                cube["material"] == "cut_shadow" for cube in spec["cubes"]
            ),
            "dark_exposed_surface_overrides": len(
                spec["generation"]["ellipsoid"]["dark_exposed_faces"]
            ),
            "cutout_is_empty_geometry_not_a_black_proxy": (
                spec["generation"]["ellipsoid"]["removed_voxels"] > 0
                and spec["generation"]["ellipsoid"]["base_occupied_voxels"]
                - spec["generation"]["ellipsoid"]["occupied_voxels"]
                == spec["generation"]["ellipsoid"]["removed_voxels"]
                and not any(cube["material"] == "cut_shadow" for cube in spec["cubes"])
            ),
        },
        "reference_frame_clipping": {
            "declared_edges": spec["generation"]["frame_clipping"],
            "measured_edges": silhouette["reference_transform"]["touches_frame_edges"],
            "iou_cannot_establish_off_frame_continuation": True,
        },
        "alpha_silhouette": silhouette,
        "source_iou_gate_at_least_0.70": silhouette["iou"] >= 0.70,
        "keypoint_mean_gate_at_most_0.05_subject_heights": (
            silhouette["keypoints"]["mean_error_subject_heights"] <= 0.05
        ),
        "proportions": proportions,
        "apple_depth_width_gate_0.8_to_1.1": (
            0.8 <= proportions["apple_depth_to_width"] <= 1.1
        ),
        "root_quadrants": [list(value) for value in sorted(quadrants)],
        "four_roots_in_four_xz_quadrants": quadrants == {(-1, -1), (-1, 1), (1, -1), (1, 1)},
        "feature_inventory": actual_inventory,
        "recorded_feature_inventory_matches": (
            actual_inventory == spec["generation"]["feature_inventory"]
        ),
        "attachments": attachment,
        "declared_link_tree_covers_every_cube": len(links) == len(spec["cubes"]) - 1,
        "views": [
            "reference-angle.png", "front.png", "back.png", "left.png", "right.png",
            "top.png", "isometric.png", "bite-closeup.png", "stem-closeup.png",
            "root-joints-closeup.png", "silhouette-overlap.png", "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
