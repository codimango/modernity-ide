#!/usr/bin/env python3
"""Render and measure deterministic Militech Chimera evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from img2blockbench import build_texture, read_json
from semantic_evidence import (
    STANDARD_VIEWS,
    PerspectiveCamera,
    alpha_silhouette_metrics,
    camera_basis,
    contact_sheet,
    cube_vertices,
    fixed_camera_perspective_evidence,
    foreground_mask,
    height_normalized_mask,
    render_view,
)
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "image.png"
ALT_REFERENCE = ROOT / "benchmarks" / "round2" / "references" / "chimera-alt.png"
SOURCE_MASK = CYCLE / "inputs" / "foreground-mask.png"
ALT_SOURCE_MASK = CYCLE / "inputs" / "alternate-foreground-mask.png"
OUTPUT = CYCLE / "render"
LIGHT_BACKGROUND = (236, 238, 241, 255)
REFERENCE_DIRECTION = (0.4, 0.08, 1.0)
REFERENCE_RENDER_SIZE = (720, 520)
ORIGINAL_PERSPECTIVE_ORBIT = {
    "yaw_degrees": 28.0,
    "pitch_degrees": 10.0,
    "roll_degrees": 0.0,
    "vertical_fov_degrees": 40.8,
    "target": (0.0, 13.0, 0.0),
    "distance": 110.0,
    "near": 0.1,
    "principal_point": (325.0, 367.0),
}
ALT_PERSPECTIVE_ORBIT = {
    "yaw_degrees": -35.0,
    "pitch_degrees": 10.0,
    "roll_degrees": 0.0,
    "vertical_fov_degrees": 12.991603690835271,
    "target": (0.0, 13.0, 0.0),
    "distance": 180.0,
    "near": 0.1,
    "principal_point": (375.0, 170.0),
}


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
    point: Sequence[float],
    direction: tuple[float, float, float],
    size: tuple[int, int],
) -> tuple[float, float]:
    """Project one point with the orthographic fit used by ``render_view``."""
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


def silhouette_overlay(source_mask: Image.Image, rendered: Image.Image) -> Image.Image:
    """Show reviewed source/model occupancy and their intersection."""
    source, _ = height_normalized_mask(source_mask, target_height=496)
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


def aligned_silhouette_overlay(
    source_mask: Image.Image, rendered: Image.Image
) -> Image.Image:
    """Show raw source/model occupancy without crop, scale, or recentering."""
    if source_mask.size != rendered.size:
        raise ValueError("aligned silhouette inputs must have identical dimensions")
    source = np.asarray(source_mask.convert("L"), dtype=np.uint8) >= 128
    model = np.asarray(
        foreground_mask(rendered, LIGHT_BACKGROUND[:3]), dtype=np.uint8
    ) >= 128
    pixels = np.full((source.shape[0], source.shape[1], 3), (8, 12, 18), dtype=np.uint8)
    pixels[source] = (210, 58, 66)
    pixels[model] = (42, 150, 204)
    pixels[source & model] = (235, 225, 210)
    return Image.fromarray(pixels, mode="RGB")


def camera_record(
    camera: PerspectiveCamera,
    orbit: Mapping[str, Any],
    reference_name: str,
) -> dict[str, Any]:
    """Describe one frozen manual calibration without implying reconstruction."""
    return {
        "schema_version": 1,
        "method": "manual-fixed-camera-calibration-v1",
        "reference": reference_name,
        "camera_parameters_are_estimated": True,
        "runtime_camera_fitting": False,
        "geometry_modified_for_calibration": False,
        "calibration_basis": (
            "Manual visual alignment constrained by visible roof, turret, chassis, "
            "and grounded leg geometry; no camera optimization runs here."
        ),
        "orbit_parameters": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in orbit.items()
        },
        "resolved_camera": camera.as_dict(),
    }


def union_crop(
    source_mask: Image.Image,
    rendered: Image.Image,
    *,
    padding: int = 8,
) -> tuple[int, int, int, int]:
    """Return a review crop containing both raw aligned silhouettes."""
    source_bbox = source_mask.getbbox()
    model_bbox = foreground_mask(rendered, LIGHT_BACKGROUND[:3]).getbbox()
    if source_bbox is None or model_bbox is None:
        raise ValueError("comparison silhouettes must not be empty")
    width, height = source_mask.size
    return (
        max(0, min(source_bbox[0], model_bbox[0]) - padding),
        max(0, min(source_bbox[1], model_bbox[1]) - padding),
        min(width, max(source_bbox[2], model_bbox[2]) + padding),
        min(height, max(source_bbox[3], model_bbox[3]) + padding),
    )


def actual_inventory(spec: dict[str, Any]) -> dict[str, int]:
    """Count identity assemblies independently from recorded metadata."""
    names = [cube["name"] for cube in spec["cubes"]]
    body_names = {
        "belly_core", "lower_hull", "center_deck", "front_deck", "prow_mid",
        "prow_tip", "lower_glacis", "rear_hull", "rear_engine_cap",
        "left_side_rail", "right_side_rail", "left_mid_cheek", "right_mid_cheek",
        "left_belly_skid", "right_belly_skid", "belly_front_plate",
        "belly_rear_plate", "left_lower_side_skirt", "right_lower_side_skirt",
        "left_front_fender", "right_front_fender",
        "left_front_cheek", "right_front_cheek", "left_rear_cheek",
        "right_rear_cheek", "front_sensor_bar", "nose_hatch",
    }
    turret_names = {
        name
        for name in names
        if name.startswith(("turret_", "cabin_", "roof_", "radar_"))
    }
    legs = spec["generation"]["leg_chains"]
    landmarks = spec["landmarks"]
    return {
        "body_volumes": len(body_names & set(names)),
        "upper_turret_cuboids": len(turret_names),
        "mechanical_leg_chains": len(legs),
        "mechanical_leg_segments": sum(len(record["segments"]) for record in legs),
        "mechanical_hinges": sum(len(record["hinges"]) for record in legs),
        "hip_housings": sum(name.endswith("_hip_housing") for name in names),
        "shin_shields": sum(name.endswith("_shin_shield") for name in names),
        "shin_armor_layers": sum(
            name.endswith(("_shin_shield", "_shin_upper_plate", "_shin_lower_plate"))
            for name in names
        ),
        "grounded_feet": sum(name.endswith("_foot_pad") for name in names),
        "foot_armor_blocks": sum(name.endswith("_foot_armor") for name in names),
        "toe_claws": sum("_toe_" in name for name in names),
        "turret_collar_segments": sum(name.startswith("turret_collar_") for name in names),
        "radar_pod_cuboids": sum(name.startswith("radar_") for name in names),
        "roof_antennae": sum(name.startswith("antenna_") for name in names),
        "amber_status_lights": sum("_amber_" in mark["name"] for mark in landmarks),
        "front_optics": sum(mark["name"].startswith("front_sensor_") for mark in landmarks),
        "panel_bolts": sum("_bolt_" in mark["name"] for mark in landmarks),
        "panel_seams": sum("_seam" in mark["name"] for mark in landmarks),
    }


def main() -> None:
    """Write canonical views, source comparison, and machine-checkable gates."""
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
    leg_prefixes = tuple(
        f"{record['name']}_" for record in spec["generation"]["leg_chains"]
    )
    leg_names = {
        name
        for name in names
        if name.startswith(leg_prefixes)
    } | {"lower_hull", "left_side_rail", "right_side_rail"}
    chassis_names = {
        name
        for name in names
        if not name.startswith(leg_prefixes)
    }
    turret_names = {
        name
        for name in names
        if name.startswith(("turret_", "cabin_", "roof_", "radar_", "antenna_"))
    }
    details = {
        "leg closeup": render_view(
            spec,
            REFERENCE_DIRECTION,
            atlas_image=atlas,
            placements=placements,
            selected_names=leg_names,
            background=LIGHT_BACKGROUND,
        ),
        "chassis closeup": render_view(
            spec,
            REFERENCE_DIRECTION,
            atlas_image=atlas,
            placements=placements,
            selected_names=chassis_names,
            background=LIGHT_BACKGROUND,
        ),
        "turret closeup": render_view(
            spec,
            (-0.55, 0.3, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=turret_names,
            background=LIGHT_BACKGROUND,
        ),
    }
    for label, image in details.items():
        image.save(OUTPUT / f"{label.replace(' ', '-')}.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        source = opened.convert("RGB")
    with Image.open(SOURCE_MASK) as opened:
        source_mask = opened.convert("L")
    with Image.open(ALT_REFERENCE) as opened:
        alternate_source = opened.convert("RGB")
    with Image.open(ALT_SOURCE_MASK) as opened:
        alternate_source_mask = opened.convert("L")

    reference_keypoints: Mapping[str, tuple[float, float]] = {
        "cabin_center": (349, 319),
        "nose_tip": (188, 394),
        "roof_center": (346, 247),
        "front_left_foot": (34, 507),
        "front_right_foot": (420, 557),
        "rear_right_foot": (550, 475),
    }
    leg_by_name = {record["name"]: record for record in spec["generation"]["leg_chains"]}
    world_keypoints = {
        "cabin_center": (0.0, 20.4, -2.0),
        "nose_tip": (0.0, 11.5, 20.2),
        "roof_center": (0.0, 23.0, -2.2),
        "front_left_foot": tuple(leg_by_name["front_left"]["joints"][-1]),
        "front_right_foot": tuple(leg_by_name["front_right"]["joints"][-1]),
        "rear_right_foot": tuple(leg_by_name["rear_right"]["joints"][-1]),
    }
    alternate_reference_keypoints: Mapping[str, tuple[float, float]] = {
        "radar_center": (365, 57),
        "turret_front_corner": (487, 143),
        "turret_rear_corner": (218, 108),
        "chassis_nose": (497, 232),
        "front_left_foot": (319, 343),
        "front_right_foot": (604, 299),
        "rear_left_foot": (159, 287),
    }
    alternate_world_keypoints = {
        "radar_center": (0.0, 26.2, -2.6),
        "turret_front_corner": (7.0, 20.0, 6.5),
        "turret_rear_corner": (-7.0, 20.3, -9.4),
        "chassis_nose": (0.0, 11.5, 20.2),
        "front_left_foot": tuple(leg_by_name["front_left"]["joints"][-1]),
        "front_right_foot": tuple(leg_by_name["front_right"]["joints"][-1]),
        "rear_left_foot": tuple(leg_by_name["rear_left"]["joints"][-1]),
    }
    perspective_camera = PerspectiveCamera.from_orbit(
        source_mask.size,
        **ORIGINAL_PERSPECTIVE_ORBIT,
    )
    perspective_render, perspective_evidence = fixed_camera_perspective_evidence(
        spec,
        perspective_camera,
        source_mask,
        reference_keypoints=reference_keypoints,
        world_keypoints=world_keypoints,
        atlas_image=atlas,
        placements=placements,
        background=LIGHT_BACKGROUND,
    )
    perspective_render.save(OUTPUT / "source-perspective.png", optimize=True)
    aligned_silhouette_overlay(source_mask, perspective_render).save(
        OUTPUT / "perspective-silhouette-overlap.png", optimize=True
    )
    original_camera_record = camera_record(
        perspective_camera, ORIGINAL_PERSPECTIVE_ORBIT, "original olive photograph"
    )
    (OUTPUT / "perspective-camera.json").write_text(
        json.dumps(original_camera_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    alternate_camera = PerspectiveCamera.from_orbit(
        alternate_source_mask.size,
        **ALT_PERSPECTIVE_ORBIT,
    )
    alternate_render, alternate_perspective_evidence = fixed_camera_perspective_evidence(
        spec,
        alternate_camera,
        alternate_source_mask,
        reference_keypoints=alternate_reference_keypoints,
        world_keypoints=alternate_world_keypoints,
        atlas_image=atlas,
        placements=placements,
        background=LIGHT_BACKGROUND,
    )
    alternate_render.save(OUTPUT / "alternate-source-perspective.png", optimize=True)
    aligned_silhouette_overlay(alternate_source_mask, alternate_render).save(
        OUTPUT / "alternate-perspective-silhouette-overlap.png", optimize=True
    )
    alternate_camera_record = camera_record(
        alternate_camera, ALT_PERSPECTIVE_ORBIT, "alternate white concept render"
    )
    (OUTPUT / "alternate-perspective-camera.json").write_text(
        json.dumps(alternate_camera_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    crop_bbox = union_crop(source_mask, perspective_render)
    alternate_crop_bbox = union_crop(alternate_source_mask, alternate_render)
    contact_sheet(
        source.crop(crop_bbox).convert("RGBA"),
        {
            "reference angle": views["reference_angle"],
            "fixed perspective": perspective_render.crop(crop_bbox),
            "alternate reference": alternate_source.crop(alternate_crop_bbox).convert("RGBA"),
            "alternate fixed perspective": alternate_render.crop(alternate_crop_bbox),
            "front": views["front"],
            "back": views["back"],
            "left": views["left"],
            "right": views["right"],
            "top": views["top"],
            "isometric": views["isometric"],
            **details,
        },
        tile=(360, 300),
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)
    contact_sheet(
        alternate_source.crop(alternate_crop_bbox).convert("RGBA"),
        {
            "alternate fixed perspective": alternate_render.crop(alternate_crop_bbox),
            "top": views["top"],
            "isometric": views["isometric"],
            "leg shields": details["leg closeup"],
            "turret and radar": details["turret closeup"],
        },
        columns=3,
        tile=(360, 300),
    ).save(OUTPUT / "alternate-comparison-sheet.png", optimize=True)
    silhouette_overlay(source_mask, views["reference_angle"]).save(
        OUTPUT / "silhouette-overlap.png", optimize=True
    )

    source_cutout = source.convert("RGBA")
    source_cutout.putalpha(source_mask)
    rendered_keypoints = {
        name: project_point(spec, point, REFERENCE_DIRECTION, REFERENCE_RENDER_SIZE)
        for name, point in world_keypoints.items()
    }
    silhouette = alpha_silhouette_metrics(
        source_cutout,
        views["reference_angle"],
        reference_keypoints=reference_keypoints,
        rendered_keypoints=rendered_keypoints,
        rendered_background=LIGHT_BACKGROUND[:3],
    )
    silhouette["method"] = "reviewed-mask-aspect-preserving-height-normalized-centered-iou-v1"
    silhouette["limitation"] = (
        "This is an orthographic proxy for one observed perspective photograph. "
        "Near and far legs have different perspective scale and elevation in the "
        "source, so this diagnostic cannot satisfy the final perspective gate. The "
        "reviewed mask excludes the display plinth; rear articulation and hidden "
        "surfaces remain inferred."
    )

    all_lower, all_upper = bounds_for(spec)
    full_extents = all_upper - all_lower
    chassis_names_for_depth = {
        "belly_core", "lower_hull", "center_deck", "front_deck", "prow_mid",
        "prow_tip", "lower_glacis", "rear_hull", "rear_engine_cap",
        "left_side_rail", "right_side_rail", "left_mid_cheek", "right_mid_cheek",
    }
    chassis_lower, chassis_upper = bounds_for(spec, chassis_names_for_depth)
    chassis_extents = chassis_upper - chassis_lower
    leg_records = spec["generation"]["leg_chains"]
    root_positions = sorted(
        [tuple(round(float(value), 6) for value in record["root"]) for record in leg_records]
    )
    station_counts = {
        station: sum(record["station"] == station for record in leg_records)
        for station in ("front", "middle", "rear")
    }
    station_z_rule = {
        "front": lambda value: value > 0,
        "middle": lambda value: abs(value) <= 1e-6,
        "rear": lambda value: value < 0,
    }
    bilateral_station_roots = all(
        len(records := [record for record in leg_records if record["station"] == station])
        == 2
        and {1 if record["root"][0] > 0 else -1 for record in records} == {-1, 1}
        and all(station_z_rule[station](record["root"][2]) for record in records)
        for station in ("front", "middle", "rear")
    )
    foot_ground_heights = []
    for record in leg_records:
        lower, _ = bounds_for(spec, {record["foot"]})
        foot_ground_heights.append(round(float(lower[1]), 6))

    inventory = actual_inventory(spec)
    recorded_inventory = spec["generation"]["feature_inventory"]
    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    proportions = {
        "overall_width_to_height": round(float(full_extents[0] / full_extents[1]), 6),
        "overall_length_to_width": round(float(full_extents[2] / full_extents[0]), 6),
        "chassis_depth_to_width": round(float(chassis_extents[2] / chassis_extents[0]), 6),
        "chassis_height_to_full_height": round(float(chassis_extents[1] / full_extents[1]), 6),
        "foot_ground_heights": foot_ground_heights,
    }
    proportion_gates = {
        "chassis_local_depth_to_width_at_least_0.55": (
            proportions["chassis_depth_to_width"] >= 0.55
        ),
        "six_grounded_feet_within_0.05": (
            len(foot_ground_heights) == 6
            and max(abs(value) for value in foot_ground_heights) <= 0.05
        ),
        "six_distinct_xz_roots": len({(value[0], value[2]) for value in root_positions}) == 6,
        "front_middle_rear_bilateral_pairs": bilateral_station_roots,
        "at_least_three_segments_per_leg": all(
            len(record["segments"]) >= 3 for record in leg_records
        ),
        "at_least_three_hinges_per_leg": all(
            len(record["hinges"]) >= 3 for record in leg_records
        ),
    }
    feature_contract = (
        inventory == recorded_inventory
        and 120 <= len(spec["cubes"]) <= 180
        and inventory["mechanical_leg_chains"] == 6
        and inventory["mechanical_leg_segments"] >= 18
        and inventory["mechanical_hinges"] >= 18
        and inventory["shin_shields"] == 6
        and inventory["shin_armor_layers"] == 18
        and inventory["grounded_feet"] == 6
        and inventory["foot_armor_blocks"] == 6
        and inventory["toe_claws"] == 18
        and inventory["turret_collar_segments"] >= 12
        and inventory["radar_pod_cuboids"] >= 7
        and inventory["roof_antennae"] == 3
        and inventory["amber_status_lights"] == 12
        and inventory["front_optics"] == 3
        and inventory["panel_bolts"] >= 24
        and inventory["panel_seams"] >= 6
    )
    evaluation = {
        "schema_version": 1,
        "renderer": (
            "deterministic-orthographic-and-fixed-camera-perspective-"
            "textured-cuboid-zbuffer-v3"
        ),
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "source_projection": False,
        "reference_rights": "unknown; private ignored benchmark references only",
        "single_view_hidden_geometry": spec["generation"]["single_view_hidden_geometry"],
        "model_extents": [round(float(value), 6) for value in full_extents],
        "chassis_extents": [round(float(value), 6) for value in chassis_extents],
        "proportion_metrics": proportions,
        "proportion_gates": proportion_gates,
        "all_proportion_gates_pass": all(proportion_gates.values()),
        "orthographic_source_diagnostic": silhouette,
        "perspective_source_evidence": {
            "original": perspective_evidence,
            "alternate": alternate_perspective_evidence,
        },
        "perspective_camera_calibration": {
            "original": original_camera_record,
            "alternate": alternate_camera_record,
        },
        "perspective_source_gate": {
            "status": "pass_independent_visual_review",
            "target_iou_at_least": 0.65,
            "target_keypoint_mean_error_subject_heights_at_most": 0.06,
            "original_iou": perspective_evidence["silhouette"]["iou"],
            "original_keypoint_mean_error_subject_heights": (
                perspective_evidence["keypoints"]["mean_error_subject_heights"]
            ),
            "alternate_iou": alternate_perspective_evidence["silhouette"]["iou"],
            "alternate_keypoint_mean_error_subject_heights": (
                alternate_perspective_evidence["keypoints"][
                    "mean_error_subject_heights"
                ]
            ),
            "hard_acceptance_gate": False,
            "acceptance_basis": (
                "independent review of both fixed-camera sheets plus native depth, "
                "six-leg stance, and attachment audits"
            ),
            "reason": (
                "Two source images constrain identity and leg count, but their staged "
                "poses, colors, and viewing directions differ. Scores remain diagnostics; "
                "the rebuilt six-legged model must be independently reviewed."
            ),
        },
        "feature_inventory": inventory,
        "recorded_feature_inventory_matches": inventory == recorded_inventory,
        "feature_contract_pass": feature_contract,
        "root_positions": [list(value) for value in root_positions],
        "leg_station_counts": station_counts,
        "attachments": attachment,
        "views": [
            "source-perspective.png", "perspective-silhouette-overlap.png",
            "alternate-source-perspective.png",
            "alternate-perspective-silhouette-overlap.png",
            "reference-angle.png", "front.png", "back.png", "left.png",
            "right.png", "top.png", "isometric.png", "leg-closeup.png",
            "chassis-closeup.png", "turret-closeup.png", "silhouette-overlap.png",
            "comparison-sheet.png", "alternate-comparison-sheet.png",
        ],
        "evidence_files": [
            "perspective-camera.json",
            "alternate-perspective-camera.json",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
