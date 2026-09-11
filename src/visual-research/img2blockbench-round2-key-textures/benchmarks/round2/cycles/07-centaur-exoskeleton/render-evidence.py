#!/usr/bin/env python3
"""Render and audit multiview evidence for the piloted Centaur exoskeleton."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from img2blockbench import build_texture, read_json
from semantic_evidence import (
    STANDARD_VIEWS,
    PerspectiveCamera,
    contact_sheet,
    cube_vertices,
    fixed_camera_perspective_evidence,
    foreground_mask,
    render_view,
)
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
OUTPUT = CYCLE / "render"
BACKGROUND = (236, 238, 241, 255)
REFERENCE_PATHS = {
    "source-6": ROOT / "image-6.png",
    "source-7": ROOT / "image-7.png",
    "source-8": ROOT / "image-8.png",
}
MASK_PATHS = {name: CYCLE / "inputs" / f"{name}-mask.png" for name in REFERENCE_PATHS}
IOU_TARGETS = {"source-6": 0.50, "source-7": 0.45, "source-8": 0.50}

# Each camera is frozen in the original 1000x1023 frame. These are manual
# view/occupancy estimates, not mask-fitting outputs.
CAMERA_ORBITS: dict[str, dict[str, Any]] = {
    "source-6": {
        "yaw_degrees": -5.0,
        "pitch_degrees": 0.0,
        "roll_degrees": 0.0,
        "vertical_fov_degrees": 35.0,
        "target": (4.0, 55.0, 4.0),
        "distance": 190.0,
        "near": 0.1,
        "principal_point": (500.0, 513.0),
    },
    "source-7": {
        "yaw_degrees": 70.0,
        "pitch_degrees": 1.0,
        "roll_degrees": 0.0,
        "vertical_fov_degrees": 35.0,
        "target": (2.0, 54.0, 2.0),
        "distance": 184.0,
        "near": 0.1,
        "principal_point": (510.0, 515.0),
    },
    "source-8": {
        "yaw_degrees": 178.0,
        "pitch_degrees": 1.0,
        "roll_degrees": 0.0,
        "vertical_fov_degrees": 35.0,
        "target": (0.0, 53.0, 0.0),
        "distance": 188.0,
        "near": 0.1,
        "principal_point": (500.0, 515.0),
    },
}

REFERENCE_KEYPOINTS: dict[str, Mapping[str, tuple[float, float]]] = {
    "source-6": {
        "head": (435.0, 115.0),
        "pelvis": (470.0, 485.0),
        "left_knee": (248.0, 650.0),
        "right_knee": (640.0, 655.0),
        "left_foot": (205.0, 946.0),
        "right_foot": (660.0, 948.0),
        "shield_center": (742.0, 245.0),
        "tool_tip": (102.0, 206.0),
    },
    "source-7": {
        "head": (539.0, 111.0),
        "pelvis": (552.0, 470.0),
        "near_knee": (520.0, 670.0),
        "near_foot": (573.0, 946.0),
        "shield_center": (306.0, 247.0),
        "shield_lower": (346.0, 515.0),
        "boom_crown": (662.0, 107.0),
    },
    "source-8": {
        "head": (546.0, 155.0),
        "pelvis": (566.0, 535.0),
        "left_knee": (363.0, 690.0),
        "right_knee": (723.0, 713.0),
        "left_foot": (346.0, 940.0),
        "right_foot": (758.0, 942.0),
        "backpack_center": (603.0, 309.0),
        "shield_center": (197.0, 291.0),
    },
}


def cube_by_name(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index cuboids by semantic name."""
    return {cube["name"]: cube for cube in spec["cubes"]}


def world_keypoints(spec: dict[str, Any], source_name: str) -> dict[str, tuple[float, float, float]]:
    """Return semantic model landmarks corresponding to the source annotations."""
    cubes = cube_by_name(spec)
    common = {
        "head": tuple(cubes["pilot_head_core"]["center"]),
        "pelvis": tuple(cubes["pelvis_frame_core"]["center"]),
        "shield_center": tuple(cubes["shield_core"]["center"]),
    }
    if source_name == "source-6":
        return {
            **common,
            "left_knee": tuple(cubes["left_exo_knee_core"]["center"]),
            "right_knee": tuple(cubes["right_exo_knee_core"]["center"]),
            "left_foot": tuple(cubes["left_exo_ground_foot"]["center"]),
            "right_foot": tuple(cubes["right_exo_ground_foot"]["center"]),
            "tool_tip": tuple(cubes["tool_receiver"]["center"]),
        }
    if source_name == "source-7":
        return {
            **common,
            "near_knee": tuple(cubes["right_exo_knee_core"]["center"]),
            "near_foot": tuple(cubes["right_exo_ground_foot"]["center"]),
            "shield_lower": tuple(cubes["shield_bottom_edge_rail"]["center"]),
            "boom_crown": tuple(cubes["shield_boom_hinge_2"]["center"]),
        }
    return {
        **common,
        "left_knee": tuple(cubes["right_exo_knee_core"]["center"]),
        "right_knee": tuple(cubes["left_exo_knee_core"]["center"]),
        "left_foot": tuple(cubes["right_exo_ground_foot"]["center"]),
        "right_foot": tuple(cubes["left_exo_ground_foot"]["center"]),
        "backpack_center": tuple(cubes["backpack_main"]["center"]),
    }


def bounds_for(spec: dict[str, Any], names: set[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return exact world-space bounds for selected oriented cuboids."""
    vertices = [
        cube_vertices(spec, cube)
        for cube in spec["cubes"]
        if names is None or cube["name"] in names
    ]
    if not vertices:
        raise ValueError("part selection contains no cuboids")
    joined = np.concatenate(vertices)
    return joined.min(axis=0), joined.max(axis=0)


def overlay(reference_mask: Image.Image, rendered: Image.Image) -> Image.Image:
    """Show source-only red, model-only blue, and overlap pale pixels."""
    source = np.asarray(reference_mask.convert("L"), dtype=np.uint8) >= 128
    model = np.asarray(foreground_mask(rendered, BACKGROUND[:3]), dtype=np.uint8) >= 128
    pixels = np.full((*source.shape, 3), (9, 14, 17), dtype=np.uint8)
    pixels[source] = (208, 58, 63)
    pixels[model] = (43, 148, 195)
    pixels[source & model] = (232, 224, 205)
    return Image.fromarray(pixels, mode="RGB")


def actual_inventory(spec: dict[str, Any]) -> dict[str, int]:
    """Count identity assemblies independently of recorded totals."""
    names = {cube["name"] for cube in spec["cubes"]}
    return {
        "human_pilots": int("pilot_head_core" in names),
        "powered_exo_legs": len(spec["generation"]["exo_leg_chains"]),
        "exo_primary_leg_segments": sum(
            len(record["primary_segments"])
            for record in spec["generation"]["exo_leg_chains"]
        ),
        "grounded_exo_feet": sum(name.endswith("_exo_ground_foot") for name in names),
        "articulated_toes": sum("_toe_" in name for name in names),
        "human_leg_chains": sum(name.startswith("pilot_") and name.endswith("_thigh") for name in names),
        "human_arm_chains": sum(name.startswith("pilot_") and name.endswith("_upper_arm") for name in names),
        "boot_restraints": sum(name.endswith("_boot_restraint") for name in names),
        "segmented_ankle_cuboids": sum(
            "_exo_ankle_core" in name or "_ankle_upper_segment" in name
            or "_ankle_lower_segment" in name for name in names
        ),
        "shield_support_boom_segments": sum(
            name.startswith("shield_boom_") and "hinge" not in name for name in names
        ),
        "shield_physical_contacts": len(spec["generation"]["shield_contacts"]),
        "shield_grille_bays": sum(name.startswith("shield_grille_bay_") for name in names),
        "shield_grille_ribs": sum("shield_bay_" in name and "_rib_" in name for name in names),
        "knee_tread_guard_cuboids": sum("_knee_tread_guard_" in name for name in names),
        "shin_rear_braces": sum(name.endswith("_shin_rear_brace") for name in names),
        "backpack_canisters": sum(name.startswith("backpack_") and name.endswith("_canister") for name in names),
        "backpack_canister_collars": sum(
            name.startswith("backpack_") and ("_cap_" in name or name.endswith("_mid_collar"))
            for name in names
        ),
        "backpack_hoses": sum(name.startswith("backpack_hose_") for name in names),
        "auxiliary_boom_segments": sum(
            name.startswith("tool_boom_") and "hinge" not in name for name in names
        ),
        "thermal_weapon_grille_bays": sum(name.startswith("thermal_grille_bay_") for name in names),
        "thermal_weapon_heat_tubes": sum(name.startswith("thermal_heat_tube_") for name in names),
        "hydraulic_hose_segments": sum("hydraulic_hose_" in name for name in names),
    }


def main() -> None:
    """Write review renders, fixed-frame evidence, and topology measurements."""
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
            background=BACKGROUND,
        )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)

    names = {cube["name"] for cube in spec["cubes"]}
    selections = {
        "pilot-closeup": {
            name for name in names
            if name.startswith("pilot_") or name in {"saddle_core", "torso_frame_spine"}
        },
        "leg-closeup": {
            name for name in names
            if name.startswith(("left_exo_", "left_thigh_", "left_knee_", "left_shin_",
                                "left_ankle_", "left_foot_", "left_toe_",
                                "left_hydraulic_", "pilot_left_thigh", "pilot_left_calf",
                                "pilot_left_boot"))
        },
        "shield-contact-closeup": {
            name for name in names
            if name.startswith(("shield_", "right_waist_brace"))
        },
        "backpack-closeup": {
            name for name in names
            if name.startswith(("backpack_", "tool_boom_", "tool_receiver", "tool_gripper_"))
        },
        "thermal-weapon-closeup": {
            name for name in names
            if name.startswith(("thermal_", "tool_receiver", "tool_gripper_"))
        },
    }
    detail_directions = {
        "pilot-closeup": (0.2, 0.15, 1.0),
        "leg-closeup": (0.8, 0.15, 1.0),
        "shield-contact-closeup": (0.5, 0.25, -1.0),
        "backpack-closeup": (0.6, 0.25, -1.0),
        "thermal-weapon-closeup": (0.15, 0.2, 1.0),
    }
    details: dict[str, Image.Image] = {}
    for name, selected in selections.items():
        details[name] = render_view(
            spec,
            detail_directions[name],
            atlas_image=atlas,
            placements=placements,
            selected_names=selected,
            background=BACKGROUND,
        )
        details[name].save(OUTPUT / f"{name}.png", optimize=True)

    reports: dict[str, Any] = {}
    source_images: dict[str, Image.Image] = {}
    perspective_images: dict[str, Image.Image] = {}
    camera_records: dict[str, Any] = {}
    for source_name in sorted(REFERENCE_PATHS):
        with Image.open(REFERENCE_PATHS[source_name]) as opened:
            source_images[source_name] = opened.convert("RGBA")
        with Image.open(MASK_PATHS[source_name]) as opened:
            source_mask = opened.convert("L")
        camera = PerspectiveCamera.from_orbit(source_mask.size, **CAMERA_ORBITS[source_name])
        rendered, report = fixed_camera_perspective_evidence(
            spec,
            camera,
            source_mask,
            reference_keypoints=REFERENCE_KEYPOINTS[source_name],
            world_keypoints=world_keypoints(spec, source_name),
            atlas_image=atlas,
            placements=placements,
            background=BACKGROUND,
        )
        rendered.save(OUTPUT / f"{source_name}-perspective.png", optimize=True)
        overlay(source_mask, rendered).save(
            OUTPUT / f"{source_name}-silhouette-overlap.png", optimize=True
        )
        report["held_out_keypoints"] = True
        report["calibration_basis"] = (
            "manual view direction, vertical occupancy, and subject-center estimate; no runtime "
            "mask fitting, cropping, scaling, translation, or recentering"
        )
        reports[source_name] = report
        perspective_images[source_name] = rendered
        camera_records[source_name] = {
            "orbit_parameters": {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in CAMERA_ORBITS[source_name].items()
            },
            "resolved_camera": camera.as_dict(),
        }

    camera_contract = {
        "schema_version": 1,
        "method": "three-independent-manually-frozen-perspective-cameras-v1",
        "camera_parameters_are_estimated": True,
        "runtime_camera_fitting": False,
        "automatic_fit_or_recentering": False,
        "geometry_modified_during_evidence": False,
        "visual_hull_used": False,
        "hidden_geometry_established": False,
        "cameras": camera_records,
    }
    (OUTPUT / "perspective-cameras.json").write_text(
        json.dumps(camera_contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    sheet_items: dict[str, Image.Image] = {}
    for source_name in sorted(source_images):
        sheet_items[f"{source_name} reference"] = source_images[source_name]
        sheet_items[f"{source_name} fixed camera"] = perspective_images[source_name]
    sheet_items.update({
        "front": views["front"], "back": views["back"], "left": views["left"],
        "right": views["right"], "top": views["top"], "isometric": views["isometric"],
        **details,
    })
    contact_sheet(sheet_items.pop("source-6 reference"), sheet_items, tile=(320, 290)).save(
        OUTPUT / "comparison-sheet.png", optimize=True
    )

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    structural = audit_attachments(spec, links)
    shield_links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["shield_contacts"]
    ]
    shield_contacts = audit_attachments(spec, shield_links)
    pilot_links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["pilot_exoframe_contacts"]
    ]
    pilot_contacts = audit_attachments(spec, pilot_links)
    linked_children = {second for _, second, _ in links}
    root_cubes = names - linked_children

    ground_contacts = []
    for record in spec["generation"]["exo_leg_chains"]:
        lower, upper = bounds_for(spec, {record["ground_foot"]})
        ground_contacts.append({
            "side": record["side"],
            "foot": record["ground_foot"],
            "minimum_y": round(float(lower[1]), 6),
            "maximum_y": round(float(upper[1]), 6),
            "grounded": abs(float(lower[1])) <= 0.05,
        })

    pilot_names = {name for name in names if name.startswith("pilot_")}
    frame_names = names - pilot_names - {name for name in names if name.startswith("shield_")}
    shield_names = {name for name in names if name.startswith("shield_")}
    part_depth = {}
    for part_name, selected in (
        ("pilot", pilot_names), ("exoframe", frame_names), ("shield", shield_names)
    ):
        lower, upper = bounds_for(spec, selected)
        extents = upper - lower
        part_depth[part_name] = {
            "selection_count": len(selected),
            "effective_world_extents": [round(float(value), 6) for value in extents],
            "depth_to_width": round(float(extents[2] / extents[0]), 6),
        }

    pilot_records = {record["side"]: record for record in spec["generation"]["pilot_leg_chains"]}
    exo_records = {record["side"]: record for record in spec["generation"]["exo_leg_chains"]}
    leg_nesting = {}
    for side in ("left", "right"):
        pilot_joints = pilot_records[side]["joints"]
        exo_joints = exo_records[side]["joints"]
        knee_gap = abs(float(exo_joints[1][0]) - float(pilot_joints[1][0]))
        ankle_gap = abs(float(exo_joints[2][0]) - float(pilot_joints[2][0]))
        leg_nesting[side] = {
            "pilot_knee": pilot_joints[1],
            "exo_knee": exo_joints[1],
            "pilot_ankle": pilot_joints[2],
            "exo_ankle": exo_joints[2],
            "knee_centerline_x_separation": round(knee_gap, 6),
            "ankle_centerline_x_separation": round(ankle_gap, 6),
            "boot_restraint": pilot_records[side]["boot"].replace("_boot", "_boot_restraint"),
            "pilot_material": "trouser_blue",
            "exo_material": "frame_dark/frame_blue/edge_steel",
        }

    gates = {
        source_name: {
            "target_iou_at_least": IOU_TARGETS[source_name],
            "target_keypoint_mean_error_subject_heights_at_most": 0.09,
            "iou": report["silhouette"]["iou"],
            "keypoint_mean_error_subject_heights": report["keypoints"]["mean_error_subject_heights"],
            "iou_pass": report["silhouette"]["iou"] >= IOU_TARGETS[source_name],
            "keypoint_pass": report["keypoints"]["mean_error_subject_heights"] <= 0.09,
        }
        for source_name, report in reports.items()
    }
    inventory = actual_inventory(spec)
    evaluation = {
        "schema_version": 1,
        "model_id": spec["id"],
        "renderer": "deterministic-orthographic-and-three-fixed-perspective-cuboid-zbuffer-v1",
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "source_projection": False,
        "reference_rights": "unknown; private ignored benchmark references only",
        "camera_parameters_are_estimated": True,
        "visual_hull_used": False,
        "hidden_geometry_established": False,
        "perspective_source_evidence": reports,
        "perspective_source_gates": gates,
        "all_perspective_aspirations_pass": all(
            gate["iou_pass"] and gate["keypoint_pass"] for gate in gates.values()
        ),
        "perspective_camera_contract": camera_contract,
        "attachments": structural,
        "declared_link_tree_covers_every_cube": (
            len(root_cubes) == 1 and root_cubes == {"pelvis_frame_core"}
        ),
        "root_cubes": sorted(root_cubes),
        "shield_contact_constraints": shield_contacts,
        "all_two_shield_contacts_touch": (
            len(shield_links) == 2 and shield_contacts["all_connected"]
        ),
        "pilot_exoframe_contact_constraints": pilot_contacts,
        "both_pilot_boots_retained_in_exoframe": (
            len(pilot_links) == 2 and pilot_contacts["all_connected"]
        ),
        "ground_contacts": ground_contacts,
        "both_exo_feet_grounded": (
            len(ground_contacts) == 2 and all(record["grounded"] for record in ground_contacts)
        ),
        "part_local_depth_audit": part_depth,
        "leg_nesting_audit": {
            "method": "authored-joint-centerline-and-explicit-restraint-v1",
            "sides": leg_nesting,
            "minimum_knee_centerline_x_separation": min(
                record["knee_centerline_x_separation"] for record in leg_nesting.values()
            ),
            "minimum_ankle_centerline_x_separation": min(
                record["ankle_centerline_x_separation"] for record in leg_nesting.values()
            ),
            "materials_are_distinct": True,
        },
        "feature_inventory": inventory,
        "recorded_feature_inventory_matches": (
            inventory == spec["generation"]["feature_inventory"]
        ),
        "views": [
            "source-6-perspective.png", "source-6-silhouette-overlap.png",
            "source-7-perspective.png", "source-7-silhouette-overlap.png",
            "source-8-perspective.png", "source-8-silhouette-overlap.png",
            "front.png", "back.png", "left.png", "right.png", "top.png",
            "isometric.png", "pilot-closeup.png", "leg-closeup.png",
            "shield-contact-closeup.png", "backpack-closeup.png",
            "thermal-weapon-closeup.png", "comparison-sheet.png",
        ],
        "evidence_files": ["perspective-cameras.json"],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "cuboids": evaluation["cuboids"],
        "bones": evaluation["bones"],
        "perspective_source_gates": gates,
        "all_links_connected": structural["all_connected"],
        "shield_contacts": shield_contacts["all_connected"],
        "both_feet_grounded": evaluation["both_exo_feet_grounded"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
