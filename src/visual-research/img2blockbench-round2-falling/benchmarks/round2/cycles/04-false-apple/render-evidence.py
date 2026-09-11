#!/usr/bin/env python3
"""Render and measure deterministic False Apple review evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

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
REFERENCE = ROOT / "image-2.png"
OUTPUT = CYCLE / "render"
LIGHT_BACKGROUND = (236, 238, 241, 255)
REFERENCE_DIRECTION = (0.0, 0.02, 1.0)
REFERENCE_RENDER_SIZE = (960, 480)


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return exact world bounds for all or selected oriented cuboids."""
    vertices = [
        cube_vertices(spec, cube)
        for cube in spec["cubes"]
        if names is None or cube["name"] in names
    ]
    if not vertices:
        raise ValueError("part selection contains no cuboids")
    joined = np.concatenate(vertices)
    return joined.min(axis=0), joined.max(axis=0)


def project_point(
    spec: dict[str, Any],
    point: Sequence[float],
    direction: tuple[float, float, float],
    size: tuple[int, int],
) -> tuple[float, float]:
    """Project one point with the exact full-model orthographic fit."""
    right, up, _ = camera_basis(direction)
    vertices = np.concatenate([cube_vertices(spec, cube) for cube in spec["cubes"]])
    projected = np.column_stack((vertices @ right, vertices @ up))
    lower = projected.min(axis=0)
    upper = projected.max(axis=0)
    margin = 42
    scale = min(
        (size[0] - margin * 2) / max(1e-6, upper[0] - lower[0]),
        (size[1] - margin * 2) / max(1e-6, upper[1] - lower[1]),
    )
    center = (lower + upper) / 2
    vector = np.asarray(tuple(float(value) for value in point), dtype=np.float64)
    return (
        float((vector @ right - center[0]) * scale + size[0] / 2),
        float(size[1] / 2 - (vector @ up - center[1]) * scale),
    )


def silhouette_overlay(reference: Image.Image, rendered: Image.Image) -> Image.Image:
    """Show source/model occupancy after the same height normalization as scoring."""
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
    pixels[source_canvas] = (207, 56, 61)
    pixels[model_canvas] = (43, 144, 182)
    pixels[source_canvas & model_canvas] = (38, 41, 45)
    return Image.fromarray(pixels, mode="RGB")


def exact_extents(
    spec: dict[str, Any], names: set[str]
) -> tuple[list[float], list[float], list[float]]:
    """Return selected cuboid lower, upper, and effective world extents."""
    lower, upper = bounds_for(spec, names)
    return (
        [round(float(value), 6) for value in lower],
        [round(float(value), 6) for value in upper],
        [round(float(value), 6) for value in upper - lower],
    )


def actual_inventory(spec: dict[str, Any]) -> dict[str, int]:
    """Count visible semantic assemblies independently from recorded totals."""
    names = [cube["name"] for cube in spec["cubes"]]
    ellipsoids = spec["generation"]["ellipsoids"]
    root_records = spec["generation"]["root_limbs"]
    graphs = spec["generation"]["branch_graphs"]
    return {
        "skull_cuboids": sum(name.startswith("skull_volume_") for name in names),
        "skull_removed_voxels": ellipsoids["skull"]["removed_voxels"],
        "skull_exposed_cut_faces": len(ellipsoids["skull"]["carved_faces"]),
        "lower_jaw_cuboids": sum(name.startswith("lower_jaw_volume_") for name in names),
        "maw_teeth": sum("_tooth_" in name for name in names),
        "apple_cuboids": sum(name.startswith("apple_lure_volume_") for name in names),
        "apple_removed_voxels": ellipsoids["apple_lure"]["removed_voxels"],
        "apple_exposed_cut_faces": len(ellipsoids["apple_lure"]["carved_faces"]),
        "apple_flesh_drips": sum(graph["name"].endswith("flesh_drip") for graph in graphs),
        "root_limbs": len(root_records),
        "near_root_limbs": sum(record["depth_layer"] == "near" for record in root_records),
        "far_root_limbs": sum(record["depth_layer"] == "far" for record in root_records),
        "root_segments": sum(len(record["segments"]) for record in root_records),
        "identity_patches": len(spec["landmarks"]),
    }


def main() -> None:
    """Write real multiview renders and machine-checkable Round 2 gates."""
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
        size=REFERENCE_RENDER_SIZE,
        background=LIGHT_BACKGROUND,
    )
    views["reference_angle"].save(OUTPUT / "reference-angle.png", optimize=True)

    names = {cube["name"] for cube in spec["cubes"]}
    skull_names = {name for name in names if name.startswith("skull_volume_")}
    jaw_names = {name for name in names if name.startswith("lower_jaw_volume_")}
    tooth_names = {name for name in names if "_tooth_" in name}
    gum_names = {name for name in names if name.startswith(("upper_gum_", "lower_gum_"))}
    head_names = skull_names | jaw_names | tooth_names | gum_names
    apple_names = {name for name in names if name.startswith("apple_lure_volume_")}
    apple_detail_names = {
        name
        for name in names
        if name.startswith(
            (
                "apple_lure_volume_", "crooked_stem_", "left_flesh_drip_",
                "middle_flesh_drip_", "right_flesh_drip_", "lure_support_",
            )
        )
    }
    root_records = spec["generation"]["root_limbs"]
    near_root_names = {
        segment
        for record in root_records
        if record["depth_layer"] == "near"
        for segment in record["segments"]
    }
    far_root_names = {
        segment
        for record in root_records
        if record["depth_layer"] == "far"
        for segment in record["segments"]
    }
    anchor_names = {"body_core"} | {name for name in names if name.startswith("spine_")}
    detail_selections = {
        "maw closeup": head_names | {graph_edge for graph_edge in names if graph_edge.startswith("spine_head_")},
        "apple closeup": apple_detail_names | {"body_core"},
        "near root closeup": near_root_names | anchor_names,
        "far root closeup": far_root_names | anchor_names,
    }
    details = {
        label: render_view(
            spec,
            REFERENCE_DIRECTION,
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
        tile=(360, 270),
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)
    silhouette_overlay(reference, views["reference_angle"]).save(
        OUTPUT / "silhouette-overlap.png", optimize=True
    )

    reference_keypoints: Mapping[str, tuple[float, float]] = {
        "apple_center": (351.0, 104.0),
        "apple_stem_tip": (338.0, 0.0),
        "head_body_socket": (205.0, 129.0),
        "maw_center": (99.0, 168.0),
        "near_hand_outer_tip": (221.0, 285.0),
        "rear_arch_crown": (498.0, 81.0),
        "rear_arch_outer_tip": (598.0, 239.0),
        "skull_crown": (128.0, 30.0),
    }
    world_keypoints = {
        "apple_center": (12.0, 39.0, 0.0),
        "apple_stem_tip": (9.0, 60.0, 0.0),
        "head_body_socket": (-20.0, 32.0, 0.0),
        "maw_center": (-44.0, 24.0, 8.0),
        "near_hand_outer_tip": (-17.0, 1.2, 24.0),
        "rear_arch_crown": (44.0, 42.0, -14.0),
        "rear_arch_outer_tip": (60.0, 9.0, -19.0),
        "skull_crown": (-38.0, 54.0, 0.0),
    }
    rendered_keypoints = {
        name: project_point(spec, point, REFERENCE_DIRECTION, REFERENCE_RENDER_SIZE)
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
    part_names = {
        "apple": apple_names,
        "head_and_maw": head_names,
        "trunk": anchor_names
        | {name for name in names if name.startswith("lure_support_")},
        "near_roots": near_root_names,
        "far_roots": far_root_names,
    }
    part_extents = {}
    for label, selection in part_names.items():
        lower, upper, extents = exact_extents(spec, selection)
        part_extents[label] = {
            "selection_rule": sorted(selection),
            "lower": lower,
            "upper": upper,
            "effective_world_extents": extents,
        }
    apple_extents = part_extents["apple"]["effective_world_extents"]
    head_extents = part_extents["head_and_maw"]["effective_world_extents"]

    layer_centers = {
        layer: (part_extents[f"{layer}_roots"]["lower"][2] + part_extents[f"{layer}_roots"]["upper"][2]) / 2
        for layer in ("near", "far")
    }
    layer_center_separation = abs(layer_centers["near"] - layer_centers["far"])
    root_layer_gate = len(near_root_names) > 0 and len(far_root_names) > 0 and layer_center_separation >= 10.0

    ground_contacts = {}
    for record in root_records:
        terminal_names = {name for name in record["segments"] if "digit" in name}
        lower, _, _ = exact_extents(spec, terminal_names)
        ground_contacts[record["name"]] = lower[1]
    all_roots_contact_ground_band = all(-0.75 <= value <= 0.75 for value in ground_contacts.values())

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    linked_names = {name for link in links for name in link[:2]}
    inventory = actual_inventory(spec)
    recorded_inventory = spec["generation"]["feature_inventory"]
    black_proxy_solids = sum(cube["material"] == "maw_shadow" for cube in spec["cubes"])
    proportions = {
        "model_extents": [round(float(value), 6) for value in full_extents],
        "apple_depth_to_width": round(float(apple_extents[2] / apple_extents[0]), 6),
        "head_maw_depth_to_height": round(float(head_extents[2] / head_extents[1]), 6),
        "root_layer_centers_z": {key: round(float(value), 6) for key, value in layer_centers.items()},
        "root_layer_center_separation": round(float(layer_center_separation), 6),
    }
    proportion_gates = {
        "apple_depth_to_width_at_least_0.75": proportions["apple_depth_to_width"] >= 0.75,
        "head_maw_depth_to_height_at_least_0.55": proportions["head_maw_depth_to_height"] >= 0.55,
        "at_least_two_limb_root_z_layers": root_layer_gate,
        "all_root_limbs_contact_ground_band": all_roots_contact_ground_band,
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
        "reference_frame_clipping": {
            "declared_edges": spec["generation"]["frame_clipping"],
            "measured_edges": silhouette["reference_transform"]["touches_frame_edges"],
            "iou_cannot_establish_off_frame_continuation": True,
        },
        "alpha_silhouette": silhouette,
        "source_iou_gate_at_least_0.62": silhouette["iou"] >= 0.62,
        "keypoint_mean_gate_at_most_0.06_subject_heights": (
            silhouette["keypoints"]["mean_error_subject_heights"] <= 0.06
        ),
        "part_local_depth_audit": {
            "method": "explicit selected-oriented-cuboid world bounds; no reusable API required",
            "selection_is_recorded": True,
            "parts": part_extents,
        },
        "proportions": proportions,
        "proportion_gates": proportion_gates,
        "all_proportion_gates_pass": all(proportion_gates.values()),
        "root_ground_contacts": ground_contacts,
        "negative_space": {
            "method": "voxel-center ellipsoid CSG subtraction before greedy cuboid merging",
            "skull_removed_voxels": spec["generation"]["ellipsoids"]["skull"]["removed_voxels"],
            "skull_exposed_cut_faces": len(spec["generation"]["ellipsoids"]["skull"]["carved_faces"]),
            "black_maw_proxy_solids": black_proxy_solids,
            "maw_is_empty_geometry_not_black_proxy": (
                spec["generation"]["ellipsoids"]["skull"]["removed_voxels"] > 0
                and black_proxy_solids == 0
            ),
        },
        "feature_inventory": inventory,
        "recorded_feature_inventory_matches": inventory == recorded_inventory,
        "attachments": attachment,
        "declared_link_tree_covers_every_cube": (
            len(links) == len(spec["cubes"]) - 1 and linked_names == names
        ),
        "views": [
            "reference-angle.png", "front.png", "back.png", "left.png", "right.png",
            "top.png", "isometric.png", "maw-closeup.png", "apple-closeup.png",
            "near-root-closeup.png", "far-root-closeup.png", "silhouette-overlap.png",
            "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
