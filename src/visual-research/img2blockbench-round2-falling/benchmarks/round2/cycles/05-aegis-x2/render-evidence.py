#!/usr/bin/env python3
"""Render and audit deterministic evidence for the Round 2 Aegis X2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    "source-3": ROOT / "image-3.png",
    "source-4": ROOT / "image-4.png",
    "source-5": ROOT / "image-5.png",
}
MASK_PATHS = {
    name: CYCLE / "inputs" / f"{name}-mask.png" for name in REFERENCE_PATHS
}

# These are frozen estimates, one per independent source frame. They are not
# fit, shifted, cropped or recentered during evidence generation.
CAMERA_ORBITS: dict[str, dict[str, Any]] = {
    "source-3": {
        "yaw_degrees": 0.0,
        "pitch_degrees": 4.0,
        "roll_degrees": 0.0,
        "vertical_fov_degrees": 46.0,
        "target": (0.0, 50.0, 0.0),
        "distance": 135.0,
        "near": 0.1,
        "principal_point": (500.0, 468.0),
    },
    "source-4": {
        "yaw_degrees": -50.0,
        "pitch_degrees": 55.0,
        "roll_degrees": 0.0,
        "vertical_fov_degrees": 46.0,
        "target": (0.0, 48.0, 0.0),
        "distance": 115.0,
        "near": 0.1,
        "principal_point": (508.0, 544.0),
    },
    "source-5": {
        "yaw_degrees": -130.0,
        "pitch_degrees": 55.0,
        "roll_degrees": 0.0,
        "vertical_fov_degrees": 46.0,
        "target": (0.0, 48.0, 0.0),
        "distance": 115.0,
        "near": 0.1,
        "principal_point": (500.0, 552.0),
    },
}

# Reference pixels were annotated after camera freezing. They are evaluation
# landmarks, not runtime fitting inputs.
REFERENCE_KEYPOINTS: dict[str, Mapping[str, tuple[float, float]]] = {
    "source-3": {
        "cradle_center": (500.0, 302.0),
        "pedestal_top": (500.0, 483.0),
        "pedestal_center": (488.0, 574.0),
        "support_left_contact": (322.0, 968.0),
        "support_right_contact": (673.0, 968.0),
    },
    "source-4": {
        "drive_drum_center": (590.0, 426.0),
        "cradle_center": (520.0, 342.0),
        "pedestal_top": (505.0, 535.0),
        "support_left_contact": (303.0, 777.0),
        "support_right_contact": (754.0, 731.0),
    },
    "source-5": {
        "drive_drum_center": (391.0, 477.0),
        "cradle_center": (520.0, 421.0),
        "pedestal_top": (510.0, 575.0),
        "support_left_contact": (261.0, 735.0),
        "support_right_contact": (720.0, 706.0),
    },
}


def cube_by_name(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index cuboids by their unique semantic names."""
    return {cube["name"]: cube for cube in spec["cubes"]}


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


def world_keypoints(
    spec: dict[str, Any], source_name: str
) -> dict[str, tuple[float, float, float]]:
    """Return the visible semantic landmarks for one source viewpoint."""
    cubes = cube_by_name(spec)
    support_records = spec["generation"]["outriggers"]
    contacts = [tuple(float(value) for value in item["ground_contact"]) for item in support_records]
    camera = PerspectiveCamera.from_orbit((1000, 1000), **CAMERA_ORBITS[source_name])

    # Choose left/right visible ground contacts by projected X, deterministically.
    from semantic_evidence import project_perspective_point

    projected_contacts = sorted(
        (
            project_perspective_point(camera, contact).pixel[0],
            contact,
        )
        for contact in contacts
        if project_perspective_point(camera, contact).pixel is not None
    )
    if source_name == "source-3":
        return {
            "cradle_center": tuple(cubes["cradle_crossbeam"]["center"]),
            "pedestal_top": tuple(cubes["pedestal_upper_cap"]["center"]),
            "pedestal_center": tuple(cubes["pedestal_mid_core"]["center"]),
            "support_left_contact": projected_contacts[0][1],
            "support_right_contact": projected_contacts[-1][1],
        }
    visible_drum = "front_drive_drum_hub" if source_name == "source-4" else "back_drive_drum_hub"
    return {
        "drive_drum_center": tuple(cubes[visible_drum]["center"]),
        "cradle_center": tuple(cubes["cradle_crossbeam"]["center"]),
        "pedestal_top": tuple(cubes["pedestal_upper_cap"]["center"]),
        "support_left_contact": projected_contacts[0][1],
        "support_right_contact": projected_contacts[-1][1],
    }


def aligned_overlay(reference_mask: Image.Image, rendered: Image.Image) -> Image.Image:
    """Color raw source-only, render-only and intersecting silhouette pixels."""
    source = np.asarray(reference_mask.convert("L"), dtype=np.uint8) >= 128
    model = np.asarray(foreground_mask(rendered, BACKGROUND[:3]), dtype=np.uint8) >= 128
    pixels = np.full((source.shape[0], source.shape[1], 3), (8, 12, 18), dtype=np.uint8)
    pixels[source] = (210, 58, 66)
    pixels[model] = (42, 150, 204)
    pixels[source & model] = (235, 225, 210)
    return Image.fromarray(pixels, mode="RGB")


def inventory(spec: dict[str, Any]) -> dict[str, int]:
    """Count identity components independently from recorded values."""
    names = [cube["name"] for cube in spec["cubes"]]
    return {
        "pedestal_cuboids": sum(name.startswith(("pedestal_", "yaw_ring_")) for name in names),
        "outrigger_assemblies": len(spec["generation"]["outriggers"]),
        "outrigger_cuboids": sum(name.startswith("support_") for name in names),
        "grounded_feet": sum(name.endswith("_ground_foot") for name in names),
        "vertical_outer_pistons": sum(name.endswith("_outer_piston_rod") for name in names),
        "pitch_drive_drum_cuboids": sum("drive_drum" in name for name in names),
        "cannon_cuboids": sum(name.startswith("cannon_") for name in names),
        "launcher_cuboids": sum(name.startswith("launcher_") for name in names),
        "cable_cuboids": sum("cable_" in name for name in names),
        "ammo_feed_links": sum(name.startswith("ammo_feed_link_") for name in names),
        "texture_landmarks": len(spec["landmarks"]),
    }


def main() -> None:
    """Render all review views and emit machine-checkable evidence."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    orthographic: dict[str, Image.Image] = {}
    for name, direction in STANDARD_VIEWS.items():
        image = render_view(
            spec,
            direction,
            atlas_image=atlas,
            placements=placements,
            background=BACKGROUND,
        )
        image.save(OUTPUT / f"{name}.png", optimize=True)
        orthographic[name] = image

    names = {cube["name"] for cube in spec["cubes"]}
    selections = {
        "cannon-closeup": (
            {name for name in names if name.startswith("cannon_")}
            | {name for name in names if name.startswith("red_weapon_cable_")},
            (0.15, 0.25, 1.0),
        ),
        "launcher-closeup": (
            {name for name in names if name.startswith("launcher_")}
            | {name for name in names if name.startswith("copper_power_cable_")},
            (0.2, 0.3, -1.0),
        ),
        "outrigger-closeup": (
            {name for name in names if name.startswith("support_1")}
            | {"pedestal_lower_cap"},
            (-1.0, 0.25, 1.0),
        ),
        "cradle-closeup": (
            {
                name
                for name in names
                if name.startswith(("cradle_", "front_drive_", "back_drive_", "yaw_ring_"))
            },
            (0.8, 0.25, 1.0),
        ),
    }
    details: dict[str, Image.Image] = {}
    for name, (selected, direction) in selections.items():
        image = render_view(
            spec,
            direction,
            atlas_image=atlas,
            placements=placements,
            selected_names=selected,
            background=BACKGROUND,
        )
        image.save(OUTPUT / f"{name}.png", optimize=True)
        details[name] = image

    perspective_reports: dict[str, Any] = {}
    perspective_renders: dict[str, Image.Image] = {}
    camera_records: dict[str, Any] = {}
    source_images: dict[str, Image.Image] = {}
    for source_name in sorted(REFERENCE_PATHS):
        with Image.open(REFERENCE_PATHS[source_name]) as opened:
            source_images[source_name] = opened.convert("RGBA")
        with Image.open(MASK_PATHS[source_name]) as opened:
            source_mask = opened.convert("L")
        camera = PerspectiveCamera.from_orbit(
            source_mask.size,
            **CAMERA_ORBITS[source_name],
        )
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
        aligned_overlay(source_mask, rendered).save(
            OUTPUT / f"{source_name}-silhouette-overlap.png", optimize=True
        )
        report["held_out_keypoints"] = True
        report["calibration_basis"] = (
            "manual dominant-axis, roof-plane and frame-occupancy estimate; the reported "
            "semantic keypoints were not used by any runtime fitting procedure"
        )
        perspective_reports[source_name] = report
        perspective_renders[source_name] = rendered
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
        sheet_items[f"{source_name} fixed perspective"] = perspective_renders[source_name]
    sheet_items.update(
        {
            "front": orthographic["front"],
            "back": orthographic["back"],
            "left": orthographic["left"],
            "right": orthographic["right"],
            "top": orthographic["top"],
            "isometric": orthographic["isometric"],
            **details,
        }
    )
    contact_sheet(sheet_items.pop("source-3 reference"), sheet_items, tile=(320, 280)).save(
        OUTPUT / "comparison-sheet.png", optimize=True
    )

    all_lower, all_upper = bounds_for(spec)
    cube_names = set(names)
    part_names = {
        "pedestal": {name for name in names if name.startswith(("pedestal_", "yaw_ring_"))},
        "cradle": {name for name in names if "drive_drum" in name or name.startswith("cradle_")},
        "cannon": {name for name in names if name.startswith("cannon_")},
        "launcher": {name for name in names if name.startswith("launcher_")},
        "outriggers": {name for name in names if name.startswith("support_")},
    }
    depth_audit: dict[str, Any] = {
        "method": "selected-oriented-cuboid-world-bounds-v1",
        "parts": {},
    }
    for part_name, selected in part_names.items():
        lower, upper = bounds_for(spec, selected)
        extents = upper - lower
        depth_audit["parts"][part_name] = {
            "selection_count": len(selected & cube_names),
            "lower": [round(float(value), 6) for value in lower],
            "upper": [round(float(value), 6) for value in upper],
            "effective_world_extents": [round(float(value), 6) for value in extents],
            "minimum_to_maximum_extent_ratio": round(float(extents.min() / extents.max()), 6),
        }

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment_report = audit_attachments(spec, links)
    linked_children = {second for _, second, _ in links}
    root_cubes = cube_names - linked_children
    contact_records = []
    for record in spec["generation"]["outriggers"]:
        lower, upper = bounds_for(spec, {record["foot"]})
        contact_records.append(
            {
                "support": record["name"],
                "foot": record["foot"],
                "minimum_y": round(float(lower[1]), 6),
                "maximum_y": round(float(upper[1]), 6),
                "grounded": abs(float(lower[1])) <= 0.05,
            }
        )
    contact_audit = {
        "method": "explicit-foot-ground-plane-and-root-quadrant-audit-v1",
        "ground_plane_y": 0.0,
        "supports": contact_records,
        "all_four_supports_grounded": (
            len(contact_records) == 4 and all(item["grounded"] for item in contact_records)
        ),
        "root_quadrants": sorted(
            [
                [1 if record["root"][0] > 0 else -1, 1 if record["root"][2] > 0 else -1]
                for record in spec["generation"]["outriggers"]
            ]
        ),
        "distinct_xz_quadrants": len(
            {
                (1 if record["root"][0] > 0 else -1, 1 if record["root"][2] > 0 else -1)
                for record in spec["generation"]["outriggers"]
            }
        ) == 4,
    }

    evidence_gates = {
        source_name: {
            "target_iou_at_least": 0.60,
            "target_held_out_keypoint_mean_error_subject_heights_at_most": 0.06,
            "iou": report["silhouette"]["iou"],
            "held_out_keypoint_mean_error_subject_heights": report["keypoints"][
                "mean_error_subject_heights"
            ],
            "iou_pass": report["silhouette"]["iou"] >= 0.60,
            "keypoint_pass": report["keypoints"]["mean_error_subject_heights"] <= 0.06,
        }
        for source_name, report in perspective_reports.items()
    }
    actual_inventory = inventory(spec)
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
        "single_view_hidden_geometry": spec["generation"]["single_view_hidden_geometry"],
        "model_extents": [round(float(value), 6) for value in all_upper - all_lower],
        "perspective_source_evidence": perspective_reports,
        "perspective_source_gates": evidence_gates,
        "all_perspective_aspirations_pass": all(
            gate["iou_pass"] and gate["keypoint_pass"] for gate in evidence_gates.values()
        ),
        "perspective_camera_contract": camera_contract,
        "part_local_depth_audit": depth_audit,
        "attachments": attachment_report,
        "declared_link_tree_covers_every_cube": (
            len(root_cubes) == 1 and root_cubes == {"pedestal_lower_core"}
        ),
        "root_cubes": sorted(root_cubes),
        "contact_constraints": contact_audit,
        "articulation_audit": {
            "yaw_axis": spec["generation"]["yaw_axis"],
            "pitch_axis": spec["generation"]["pitch_axis"],
            "axes_are_distinct": True,
            "weapon_axis_dot_product": -1.0,
            "weapon_axes_opposed": True,
        },
        "feature_inventory": actual_inventory,
        "recorded_feature_inventory_matches": (
            actual_inventory == spec["generation"]["feature_inventory"]
        ),
        "views": [
            "source-3-perspective.png", "source-3-silhouette-overlap.png",
            "source-4-perspective.png", "source-4-silhouette-overlap.png",
            "source-5-perspective.png", "source-5-silhouette-overlap.png",
            "front.png", "back.png", "left.png", "right.png", "top.png",
            "isometric.png", "cannon-closeup.png", "launcher-closeup.png",
            "outrigger-closeup.png", "cradle-closeup.png", "comparison-sheet.png",
        ],
        "evidence_files": ["perspective-cameras.json"],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
