#!/usr/bin/env python3
"""Render and measure deterministic Zombie Devil evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from img2blockbench import build_texture, read_json
from semantic_evidence import (
    PerspectiveCamera,
    STANDARD_VIEWS,
    aligned_mask_metrics,
    alpha_silhouette_metrics,
    contact_sheet,
    cube_vertices,
    foreground_mask,
    project_perspective_point,
    render_perspective_view,
    render_view,
)
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "image-11.png"
MASK = CYCLE / "inputs" / "foreground-mask.png"
INPUT_CONTRACT = CYCLE / "inputs" / "input-contract.json"
OUTPUT = CYCLE / "render"
BACKGROUND = (238, 238, 235, 255)
REFERENCE_DIRECTION = (0.0, 0.02, 1.0)
REFERENCE_RENDER_SIZE = (513, 754)


def source_camera() -> PerspectiveCamera:
    """Return the frozen, weak-perspective camera estimated from the manga panel."""
    return PerspectiveCamera.from_orbit(
        REFERENCE_RENDER_SIZE,
        yaw_degrees=0.0,
        pitch_degrees=0.0,
        vertical_fov_degrees=25.0,
        target=(0.0, 15.0, 0.0),
        distance=360.0,
        principal_point=(260.0, 377.0),
    )


def review_camera(yaw: float, pitch: float = 0.0) -> PerspectiveCamera:
    """Return a fixed review frame that clips unknown lower continuations."""
    return PerspectiveCamera.from_orbit(
        (640, 640),
        yaw_degrees=yaw,
        pitch_degrees=pitch,
        vertical_fov_degrees=25.0,
        target=(0.0, 15.0, 0.0),
        distance=325.0,
        principal_point=(320.0, 320.0),
    )


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return exact world bounds for all or selected cuboids."""
    vertices = [
        cube_vertices(spec, cube)
        for cube in spec["cubes"]
        if names is None or cube["name"] in names
    ]
    if not vertices:
        raise ValueError("part selection contains no cuboids")
    joined = np.concatenate(vertices)
    return joined.min(axis=0), joined.max(axis=0)


def part_extents(spec: dict[str, Any], names: set[str]) -> list[float]:
    """Return selected oriented-cuboid world extents."""
    lower, upper = bounds_for(spec, names)
    return [round(float(value), 6) for value in upper - lower]


def actual_inventory(spec: dict[str, Any]) -> dict[str, int]:
    """Count major identity structures independently from recorded totals."""
    names = {cube["name"] for cube in spec["cubes"]}
    return {
        "massive_arm_chains": len(spec["generation"]["arm_chains"]),
        "fists": sum(
            int(any(name.startswith(f"{side}_fist_volume_") for name in names))
            for side in ("left", "right")
        ),
        "fist_fingers": sum("_fist_knuckle_" in name for name in names),
        "exposed_brains": int(any(name.startswith("brain_volume_") for name in names)),
        "brain_grooves": sum(name.startswith("brain_groove_") for name in names),
        "carved_screaming_mouths": int(any(name.startswith("mouth_cavity_") for name in names)),
        "mouth_teeth": sum("_mouth_tooth_" in name for name in names),
        "hanging_organ_lobes": sum(
            f"organ_lobe_{part}" in names
            for part in ("left_upper", "left_lower", "right_upper", "right_lower")
        ),
        "visceral_tendrils": len(spec["generation"]["visceral_tendrils"]),
        "grounded_feet": sum(name.endswith("_foot") for name in names),
        "observed_camera_axes": spec["generation"]["independent_observed_camera_axes"],
    }


def main() -> None:
    """Write review renders and source-aware quantitative evidence."""
    spec = read_json(SPEC_PATH)
    input_contract = read_json(INPUT_CONTRACT)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    views: dict[str, Image.Image] = {}
    fixed_review_cameras = {
        "front": review_camera(0.0),
        "back": review_camera(180.0),
        "left": review_camera(90.0),
        "right": review_camera(-90.0),
        "isometric": review_camera(42.0, 18.0),
    }
    for name in STANDARD_VIEWS:
        if name == "top":
            views[name] = render_view(
                spec,
                STANDARD_VIEWS[name],
                atlas_image=atlas,
                placements=placements,
                background=BACKGROUND,
            )
        else:
            views[name] = render_perspective_view(
                spec,
                fixed_review_cameras[name],
                atlas_image=atlas,
                placements=placements,
                background=BACKGROUND,
            )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)
    camera = source_camera()
    reference_render = render_perspective_view(
        spec,
        camera,
        atlas_image=atlas,
        placements=placements,
        background=BACKGROUND,
    )
    reference_render.save(OUTPUT / "reference-angle.png", optimize=True)

    names = {cube["name"] for cube in spec["cubes"]}
    detail_selections = {
        "face closeup": {
            name for name in names
            if name.startswith(
                (
                    "face_volume_", "jaw_mass_", "mouth_cavity_", "upper_mouth_",
                    "lower_mouth_", "hair_", "left_bulging_eye_", "right_bulging_eye_",
                    "left_brow_", "right_brow_", "left_inner_", "right_inner_",
                    "left_cheek_", "right_cheek_", "left_nasolabial_",
                    "right_nasolabial_", "chin_",
                )
            )
            or name in {"broken_nose", "left_pupil", "right_pupil"}
        },
        "brain closeup": {
            name for name in names
            if name.startswith(("brain_neck_mass_", "brain_volume_", "brain_groove_"))
        },
        "viscera closeup": {
            name for name in names
            if name.startswith(
                (
                    "visceral_bridge_", "organ_lobe_", "organ_bulge_", "left_visceral_",
                    "central_intertwined_", "right_visceral_",
                )
            )
        },
    }
    details = {
        label: render_view(
            spec,
            REFERENCE_DIRECTION,
            atlas_image=atlas,
            placements=placements,
            selected_names=selection,
            background=BACKGROUND,
        )
        for label, selection in detail_selections.items()
    }
    for label, rendered in details.items():
        rendered.save(OUTPUT / f"{label.replace(' ', '-')}.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        source = opened.convert("RGBA")
    contact_sheet(
        source,
        {
            "reference angle": reference_render,
            "front": views["front"],
            "back": views["back"],
            "left": views["left"],
            "right": views["right"],
            "top": views["top"],
            "isometric": views["isometric"],
            **details,
        },
        tile=(340, 340),
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)

    with Image.open(MASK) as opened:
        mask = opened.convert("L")
    reference_silhouette = Image.new("RGBA", mask.size, (255, 255, 255, 0))
    reference_silhouette.putalpha(mask)
    reference_keypoints: Mapping[str, tuple[float, float]] = {
        "brain_top": (349.0, 39.0),
        "left_fist": (31.0, 169.0),
        "right_fist": (496.0, 322.0),
        "left_eye": (166.0, 250.0),
        "mouth_center": (183.0, 309.0),
        "organ_split": (211.0, 474.0),
        "left_crop": (48.0, 753.0),
        "right_crop": (302.0, 753.0),
    }
    world_keypoints = {
        "brain_top": (17.0, 87.0, 0.5),
        "left_fist": (-40.0, 59.5, 10.5),
        "right_fist": (43.0, 25.5, 12.0),
        "left_eye": (-23.0, 43.0, 18.3),
        "mouth_center": (-16.0, 32.0, 12.0),
        "organ_split": (-1.0, 28.0, 12.0),
        "left_crop": (-24.0, -65.0, 6.0),
        "right_crop": (14.0, -65.0, 10.0),
    }
    rendered_keypoints = {}
    for name, point in world_keypoints.items():
        projected = project_perspective_point(camera, point)
        if not projected.in_front or projected.pixel is None:
            raise ValueError(f"keypoint is behind source camera: {name}")
        rendered_keypoints[name] = projected.pixel
    continuation_endpoint_projection = {}
    for record in spec["generation"]["visceral_tendrils"]:
        if not record["endpoint_is_frame_cropped"]:
            continue
        endpoint = record["joints"][-1]
        projected = project_perspective_point(camera, endpoint)
        continuation_endpoint_projection[record["name"]] = {
            "world": endpoint,
            "pixel": list(projected.pixel) if projected.pixel is not None else None,
            "in_front": projected.in_front,
            "in_frame": projected.in_frame,
        }
    silhouette = alpha_silhouette_metrics(
        reference_silhouette,
        reference_render,
        reference_keypoints=reference_keypoints,
        rendered_keypoints=rendered_keypoints,
        rendered_background=BACKGROUND[:3],
    )
    silhouette["limitation"] = (
        "The reviewed mask isolates the visible Devil from speech balloons and nearby "
        "figures. It is bottom-clipped, and the second supplied image is the same view."
    )
    raw_fixed_silhouette = aligned_mask_metrics(
        reference_silhouette,
        foreground_mask(reference_render, BACKGROUND[:3]),
    )

    links = [
        (entry["first"], entry["second"], entry["joint"])
        for entry in spec["generation"]["declared_attachments"]
    ]
    attachment_report = audit_attachments(spec, links)
    actual = actual_inventory(spec)
    recorded = spec["generation"]["feature_inventory"]
    torso_names = {name for name in names if name.startswith("torso_core_")}
    head_names = {name for name in names if name.startswith("face_volume_")}
    brain_names = {name for name in names if name.startswith("brain_volume_")}
    arm_names = {
        name for name in names
        if name.startswith(("left_arm_mass_", "left_fist_", "right_arm_upper_", "right_forearm_", "right_fist_"))
    }
    proportions = {
        "torso_xyz_extents": part_extents(spec, torso_names),
        "head_xyz_extents": part_extents(spec, head_names),
        "brain_xyz_extents": part_extents(spec, brain_names),
        "arms_xyz_extents": part_extents(spec, arm_names),
    }
    proportions.update(
        {
            "torso_depth_to_width": round(proportions["torso_xyz_extents"][2] / proportions["torso_xyz_extents"][0], 6),
            "head_depth_to_width": round(proportions["head_xyz_extents"][2] / proportions["head_xyz_extents"][0], 6),
            "brain_depth_to_width": round(proportions["brain_xyz_extents"][2] / proportions["brain_xyz_extents"][0], 6),
        }
    )
    report = {
        "schema_version": 1,
        "asset": spec["id"],
        "source_iou_gate_at_least_0.55": silhouette["iou"] >= 0.55,
        "keypoint_mean_gate_at_most_0.08_subject_heights": silhouette["keypoints"]["mean_error_subject_heights"] <= 0.08,
        "alpha_silhouette": silhouette,
        "raw_fixed_camera_silhouette": raw_fixed_silhouette,
        "source_camera": camera.as_dict(),
        "source_camera_has_no_auto_fit_or_recentering": True,
        "review_cameras": {
            name: review.as_dict() for name, review in fixed_review_cameras.items()
        },
        "duplicate_view_evidence": input_contract["view_content_similarity"],
        "observed_camera_axes": input_contract["observed_camera_axes"],
        "hidden_geometry_established_from_observed_views": False,
        "reference_frame_clipping": {
            "declared_edges": ["bottom", "right"],
            "measured_bottom": bool(np.asarray(mask)[-1, :].max()),
            "measured_right": bool(np.asarray(mask)[:, -1].max()),
            "off_frame_continuation_is_not_reconstructed_as_feet": True,
            "rendered_continuation_endpoints": continuation_endpoint_projection,
            "both_trailing_continuations_clipped_by_fixed_camera": (
                len(continuation_endpoint_projection) == 2
                and all(
                    item["in_front"] and not item["in_frame"]
                    for item in continuation_endpoint_projection.values()
                )
            ),
        },
        "proportions": proportions,
        "depth_gates": {
            "torso_depth_to_width_at_least_0.48": proportions["torso_depth_to_width"] >= 0.48,
            "head_depth_to_width_at_least_0.60": proportions["head_depth_to_width"] >= 0.60,
            "brain_depth_to_width_at_least_0.70": proportions["brain_depth_to_width"] >= 0.70,
        },
        "actual_feature_inventory": actual,
        "recorded_feature_inventory": recorded,
        "recorded_feature_inventory_matches": actual == recorded,
        "attachments": attachment_report,
        "declared_link_tree_covers_every_cube": len(links) == len(spec["cubes"]) - 1,
        "part_local_depth_audit": {
            "method": "explicit selected-oriented-cuboid world bounds",
            "rear_depth_is_inferred": True,
        },
        "views": [
            "reference-angle.png", "front.png", "back.png", "left.png", "right.png",
            "top.png", "isometric.png", "face-closeup.png", "brain-closeup.png",
            "viscera-closeup.png", "comparison-sheet.png",
        ],
    }
    report["all_depth_gates_pass"] = all(report["depth_gates"].values())
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
