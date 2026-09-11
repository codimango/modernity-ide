#!/usr/bin/env python3
"""Render and measure deterministic multi-view Greta evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

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
REFERENCE = ROOT / "image-9.png"
OUTPUT = CYCLE / "render"
LIGHT_BACKGROUND = (236, 238, 241, 255)
REFERENCE_DIRECTION = (-0.75, 0.0, 1.0)
RENDER_SIZE = (640, 640)


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return world bounds for all or selected oriented cuboids."""
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
    size: tuple[int, int] = RENDER_SIZE,
) -> tuple[float, float]:
    """Project a world point through the same orthographic fit as the renderer."""
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
    vector = np.asarray(point, dtype=np.float64)
    return (
        float((vector @ right - center[0]) * scale + size[0] / 2),
        float(size[1] / 2 - (vector @ up - center[1]) * scale),
    )


def silhouette_overlay(reference: Image.Image, rendered: Image.Image) -> Image.Image:
    """Show source-only, model-only, and shared normalized silhouette pixels."""
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


def actual_inventory(spec: dict[str, Any]) -> dict[str, int]:
    """Count identity assemblies independently from recorded metadata."""
    names = {cube["name"] for cube in spec["cubes"]}
    landmarks = spec["landmarks"]
    tail_graph = spec["generation"]["tail_graph"]
    return {
        "toothed_mouth_assemblies": sum(name.startswith("mouth_") for name in names),
        "head_mouths": int("mouth_head" in names),
        "hand_mouths": int("mouth_hand" in names),
        "tail_mouths": sum(name.startswith("mouth_tail_") for name in names),
        "tooth_row_landmarks": sum(mark["name"].endswith("_teeth") for mark in landmarks),
        "red_eye_landmarks": sum(mark["name"] == "single_red_eye" for mark in landmarks),
        "blue_tattoo_landmarks": sum(
            mark["name"].startswith("right_shoulder_blue_tattoo_") for mark in landmarks
        ),
        "chef_hat_cuboids": sum(name.startswith("hat_") for name in names),
        "dorsal_fin_segments": sum(name.startswith("dorsal_fin_") for name in names),
        "humanoid_arm_chains": len(spec["generation"]["arm_chains"]),
        "biped_leg_chains": len(spec["generation"]["leg_chains"]),
        "grounded_feet": sum(name.endswith("_foot") for name in names),
        "tail_segments": sum(
            len(edge["segments"]) for edge in tail_graph["edges"]
        ),
        "caudal_fin_branches": sum(
            edge["name"] in {"upper_fin", "lower_fin"} for edge in tail_graph["edges"]
        ),
        "held_axes": int({"axe_handle", "axe_head", "axe_hook"}.issubset(names)),
    }


def main() -> None:
    """Write review renders and machine-checkable source-fidelity evidence."""
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
        size=RENDER_SIZE,
        background=LIGHT_BACKGROUND,
    )
    views["reference_angle"].save(OUTPUT / "reference-angle.png", optimize=True)

    names = {cube["name"] for cube in spec["cubes"]}
    detail_names = {
        "head mouth": {
            name
            for name in names
            if name.startswith(("head_", "lower_jaw", "mouth_head", "hat_", "shark_throat"))
        },
        "hand mouth": {
            name
            for name in names
            if name.startswith(("right_arm_", "right_hand", "right_finger_", "mouth_hand"))
        },
        "tail mouths": {
            name for name in names if name.startswith(("tail_", "mouth_tail_"))
        },
        "axe contact": {
            name
            for name in names
            if name.startswith(("left_arm_", "left_hand", "axe_"))
        },
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
        for label, selection in detail_names.items()
    }
    for label, image in details.items():
        image.save(OUTPUT / f"{label.replace(' ', '-')}.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    flattened = Image.new("RGBA", reference.size, LIGHT_BACKGROUND)
    flattened.alpha_composite(reference)
    contact_sheet(
        flattened,
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

    reference_keypoints: Mapping[str, tuple[float, float]] = {
        "hat_top": (260, 8),
        "red_eye": (237, 109),
        "snout_tip": (150, 126),
        "head_mouth": (233, 154),
        "hand_mouth": (394, 414),
        "tail_base_mouth": (286, 565),
        "tail_mid_mouth": (429, 549),
        "tail_tip": (593, 680),
        "axe_head": (52, 578),
        "right_foot": (381, 750),
    }
    world_keypoints = {
        "hat_top": (-2.3, 69.35, 0.0),
        "red_eye": (-5.4, 60.4, 5.25),
        "snout_tip": (-17.5, 57.5, 1.0),
        "head_mouth": (-8.7, 55.7, 5.825),
        "hand_mouth": (12.4, 31.8, 5.05),
        "tail_base_mouth": (5.7, 22.2, 0.075),
        "tail_mid_mouth": (16.1, 19.45, -0.3),
        "tail_tip": (36.0, 6.0, -3.5),
        "axe_head": (-26.0, 16.5, 2.0),
        "right_foot": (8.0, 0.0, 5.0),
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
    silhouette["limitation"] = (
        "One observed illustrated view constrains the front silhouette and named landmarks. "
        "The source alpha is complete and does not touch the frame; rear materials and exact "
        "appendage depth remain conservative semantic inference requiring canonical views."
    )

    all_lower, all_upper = bounds_for(spec)
    full_extents = all_upper - all_lower
    torso_names = {"chest_core", "shoulder_core"}
    head_names = {
        name for name in names if name.startswith("head_snout_")
    } | {"head_cranium", "lower_jaw", "mouth_head"}
    tail_names = {name for name in names if name.startswith("tail_")}
    torso_lower, torso_upper = bounds_for(spec, torso_names)
    head_lower, head_upper = bounds_for(spec, head_names)
    tail_lower, tail_upper = bounds_for(spec, tail_names)
    body_width = float((torso_upper - torso_lower)[0])
    foot_ground_heights = []
    for foot_name in ("left_foot", "right_foot"):
        lower, _ = bounds_for(spec, {foot_name})
        foot_ground_heights.append(round(float(lower[1]), 6))

    inventory = actual_inventory(spec)
    recorded_inventory = spec["generation"]["feature_inventory"]
    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    contact = spec["generation"]["held_prop_contacts"]
    axe_contact_present = (
        len(contact) == 1
        and contact[0]["hand_cube"] == "left_hand"
        and contact[0]["prop_cube"] == "axe_handle"
        and any(first == "left_hand" and second == "axe_handle" for first, second, _ in links)
    )
    proportions = {
        "full_width_to_height": round(float(full_extents[0] / full_extents[1]), 6),
        "torso_depth_to_body_width": round(float((torso_upper - torso_lower)[2] / body_width), 6),
        "head_depth_to_body_width": round(float((head_upper - head_lower)[2] / body_width), 6),
        "tail_span_to_body_width": round(float((tail_upper - tail_lower)[0] / body_width), 6),
        "foot_ground_heights": foot_ground_heights,
    }
    proportion_gates = {
        "source_aspect_delta_at_most_0.04": (
            abs(silhouette["rendered_aspect_ratio"] - silhouette["reference_aspect_ratio"])
            <= 0.04
        ),
        "torso_depth_to_body_width_at_least_0.35": (
            proportions["torso_depth_to_body_width"] >= 0.35
        ),
        "head_depth_to_body_width_at_least_0.35": (
            proportions["head_depth_to_body_width"] >= 0.35
        ),
        "tail_span_to_body_width_at_least_1.0": proportions["tail_span_to_body_width"] >= 1.0,
        "two_grounded_feet_within_0.05": (
            len(foot_ground_heights) == 2
            and max(abs(value) for value in foot_ground_heights) <= 0.05
        ),
    }
    feature_contract = (
        inventory == recorded_inventory
        and inventory["toothed_mouth_assemblies"] == 4
        and inventory["head_mouths"] == 1
        and inventory["hand_mouths"] == 1
        and inventory["tail_mouths"] == 2
        and inventory["tooth_row_landmarks"] == 8
        and inventory["caudal_fin_branches"] == 2
        and inventory["held_axes"] == 1
    )
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
        "model_extents": [round(float(value), 6) for value in full_extents],
        "proportion_metrics": proportions,
        "proportion_gates": proportion_gates,
        "all_proportion_gates_pass": all(proportion_gates.values()),
        "alpha_silhouette": silhouette,
        "source_iou_gate_at_least_0.68": silhouette["iou"] >= 0.68,
        "keypoint_mean_error_gate_at_most_0.05": (
            silhouette["keypoints"]["mean_error_subject_heights"] <= 0.05
        ),
        "feature_inventory": inventory,
        "recorded_feature_inventory_matches": inventory == recorded_inventory,
        "feature_contract_pass": feature_contract,
        "axe_contact_present": axe_contact_present,
        "attachments": attachment,
        "views": [
            "reference-angle.png", "front.png", "back.png", "left.png", "right.png",
            "top.png", "isometric.png", "head-mouth.png", "hand-mouth.png",
            "tail-mouths.png", "axe-contact.png", "silhouette-overlap.png",
            "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
