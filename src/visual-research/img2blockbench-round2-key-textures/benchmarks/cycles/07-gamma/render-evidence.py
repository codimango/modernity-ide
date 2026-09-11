#!/usr/bin/env python3
"""Render and measure deterministic multi-view Gamma evidence."""

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


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "benchmarks" / "references" / "07-gamma.png"
OUTPUT = CYCLE / "render"
LIGHT_BACKGROUND = (236, 238, 241, 255)
REFERENCE_DIRECTION = (0.08, 0.02, 1.0)


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
    spec: dict[str, Any], point: tuple[float, float, float], direction: tuple[float, float, float]
) -> tuple[float, float]:
    """Project one world point with the same fit used by ``render_view``."""
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
    """Show normalized source/model occupancy and their intersection."""
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
    pixels[source_canvas] = (202, 63, 70)
    pixels[model_canvas] = (44, 143, 180)
    pixels[source_canvas & model_canvas] = (38, 42, 48)
    return Image.fromarray(pixels, mode="RGB")


def main() -> None:
    """Write full review coverage and machine-checkable Cycle 7 metrics."""
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

    names = {cube["name"] for cube in spec["cubes"]}
    detail_names = {
        "face split head": {
            name
            for name in names
            if name == "head_core" or name.startswith(("split_head_", "mask_"))
        },
        "maw eight claw": {
            name
            for name in names
            if name == "head_core"
            or name.startswith(("mandible_", "chest_maw", "maw_tooth_"))
        },
        "ring": {
            name
            for name in names
            if name.startswith(("upper_ring_", "lower_ring_"))
            or name in {"torso_core"}
        },
        "leg joint": {
            name
            for name in names
            if name.startswith("mechanical_leg_") or name.startswith("hem_")
        },
    }
    details = {
        label: render_view(
            spec,
            (0.18, 0.04, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=selection,
            background=LIGHT_BACKGROUND,
        )
        for label, selection in detail_names.items()
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
        "mask_center": (422, 148),
        "maw_center": (286, 220),
        "upper_ring_center": (340, 345),
        "lower_ring_center": (301, 510),
        "left_outer_knee": (59, 641),
        "right_outer_knee": (455, 646),
    }
    world_keypoints = {
        "mask_center": (12.25, 74.8, 9.1),
        "maw_center": (1.0, 65.5, 5.55),
        "upper_ring_center": (6.2, 53.5, 8.0),
        "lower_ring_center": (1.7, 36.5, 8.2),
        "left_outer_knee": (-19.0, 20.0, -4.5),
        "right_outer_knee": (20.5, 19.0, -4.5),
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
    full = all_upper - all_lower
    hem_names = {name for name in names if name.startswith("hem_")}
    torso_names = {"torso_core"}
    crown_names = {
        name for name in names if name.startswith(("mandible_", "split_head_"))
    }
    mechanical_names = {name for name in names if name.startswith("mechanical_leg_")}
    mask_names = {
        name for name in names if name.startswith("mask_") and name[-1:].isdigit()
    }
    hem_lower, hem_upper = bounds_for(spec, hem_names)
    torso_lower, torso_upper = bounds_for(spec, torso_names)
    crown_lower, crown_upper = bounds_for(spec, crown_names)
    mechanical_lower, mechanical_upper = bounds_for(spec, mechanical_names)
    mask_lower, mask_upper = bounds_for(spec, mask_names)

    graphs = spec["generation"]["branch_graphs"]
    mandible_graphs = [graph for graph in graphs if graph["name"].startswith("mandible_")]
    leg_graphs = [
        graph for graph in graphs if graph["name"].startswith("mechanical_leg_")
    ]
    split_graph = next(graph for graph in graphs if graph["name"] == "split_head")
    cube_names = [cube["name"] for cube in spec["cubes"]]
    required_mask = {
        "mask_mount",
        "mask_1",
        "mask_2",
        "mask_3",
        "mask_4",
        "mask_5",
        "mask_left_eye",
        "mask_right_eye",
        "mask_mouth",
    }
    actual_inventory = {
        "upper_mandible_chains": len(mandible_graphs),
        "mandible_segments": sum(name.startswith("mandible_") for name in cube_names),
        "mandible_depth_layers": len(
            {
                round(
                    float(
                        next(
                            node for node in graph["nodes"]
                            if node["name"] == graph["root_node"]
                        )["point"][2]
                    )
                )
                for graph in mandible_graphs
            }
        ),
        "split_head_halves": sum(
            edge["start"] == split_graph["root_node"] for edge in split_graph["edges"]
        ),
        "vertical_chest_maws": sum(name == "chest_maw" for name in cube_names),
        "maw_teeth": sum(name.startswith("maw_tooth_") for name in cube_names),
        "expressionless_masks": int(required_mask.issubset(names)),
        "silver_ring_assemblies": sum(
            f"{ring_name}_hanger" in names for ring_name in ("upper_ring", "lower_ring")
        ),
        "ring_segments": sum("_ring_segment_" in name for name in cube_names),
        "mechanical_leg_chains": len(leg_graphs),
        "mechanical_leg_segments": sum(
            name.startswith("mechanical_leg_")
            and any(token in name for token in ("_upper_", "_lower_", "_toe_"))
            for name in cube_names
        ),
        "mechanical_hinges": sum(name.endswith(("knee_hinge", "ankle_hinge")) for name in cube_names),
        "mechanical_leg_depth_layers": len(
            {
                round(
                    float(
                        next(
                            node for node in graph["nodes"]
                            if node["name"] == graph["root_node"]
                        )["point"][2]
                    )
                )
                for graph in leg_graphs
            }
        ),
    }
    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    proportions = {
        "full_width_to_height": round(float(full[0] / full[1]), 6),
        "hem_width_to_full_width": round(float((hem_upper - hem_lower)[0] / full[0]), 6),
        "torso_width_to_full_width": round(
            float((torso_upper - torso_lower)[0] / full[0]), 6
        ),
        "crown_width_to_full_width": round(
            float((crown_upper - crown_lower)[0] / full[0]), 6
        ),
        "mechanical_span_to_full_width": round(
            float((mechanical_upper - mechanical_lower)[0] / full[0]), 6
        ),
        "real_depth_to_full_width": round(float(full[2] / full[0]), 6),
        "mask_width_to_full_height": round(
            float((mask_upper - mask_lower)[0] / full[1]), 6
        ),
        "mask_height_to_full_height": round(
            float((mask_upper - mask_lower)[1] / full[1]), 6
        ),
        "ground_gap": round(max(0.0, float(all_lower[1])), 6),
    }
    proportion_gate = {
        "full_width_to_height_0.61_0.71": 0.61 <= proportions["full_width_to_height"] <= 0.71,
        "hem_width_to_full_width_0.72_0.86": 0.72 <= proportions["hem_width_to_full_width"] <= 0.86,
        "torso_width_to_full_width_0.32_0.44": 0.32 <= proportions["torso_width_to_full_width"] <= 0.44,
        "crown_width_to_full_width_0.52_0.66": 0.52 <= proportions["crown_width_to_full_width"] <= 0.66,
        "mechanical_span_at_least_0.93": proportions["mechanical_span_to_full_width"] >= 0.93,
        "real_depth_to_full_width_at_least_0.22": proportions["real_depth_to_full_width"] >= 0.22,
        "mask_width_to_full_height_0.04_0.075": 0.04 <= proportions["mask_width_to_full_height"] <= 0.075,
        "mask_height_to_full_height_0.075_0.12": 0.075 <= proportions["mask_height_to_full_height"] <= 0.12,
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
        "model_extents": [round(float(value), 6) for value in full],
        "proportion_metrics": proportions,
        "proportion_gate": proportion_gate,
        "all_proportion_gates_pass": all(proportion_gate.values()),
        "alpha_silhouette": silhouette,
        "source_iou_gate_at_least_0.58": silhouette["iou"] >= 0.58,
        "source_iou_aspiration_at_least_0.64": silhouette["iou"] >= 0.64,
        "feature_inventory": actual_inventory,
        "recorded_feature_inventory_matches": (
            actual_inventory == spec["generation"]["feature_inventory"]
        ),
        "feature_contract_pass": (
            actual_inventory == spec["generation"]["feature_inventory"]
            and actual_inventory["upper_mandible_chains"] == 8
            and actual_inventory["mechanical_leg_chains"] == 4
            and actual_inventory["silver_ring_assemblies"] == 2
            and actual_inventory["mandible_depth_layers"] == 3
            and actual_inventory["mechanical_leg_depth_layers"] == 2
        ),
        "attachments": attachment,
        "branch_graph_count": len(graphs),
        "views": [
            "reference-angle.png", "front.png", "back.png", "left.png", "right.png",
            "top.png", "isometric.png", "face-split-head.png", "maw-eight-claw.png",
            "ring.png", "leg-joint.png", "silhouette-overlap.png",
            "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
