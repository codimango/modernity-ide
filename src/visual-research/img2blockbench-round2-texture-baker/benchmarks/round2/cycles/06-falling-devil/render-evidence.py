#!/usr/bin/env python3
"""Render and measure fixed-camera evidence for the Falling Devil."""

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
REFERENCE = ROOT / "image-12.png"
OUTPUT = CYCLE / "render"
LIGHT_BACKGROUND = (236, 238, 241, 255)
REFERENCE_DIRECTION = (0.0, 0.02, 1.0)


def source_foreground_mask(reference: Image.Image) -> Image.Image:
    """Remove the known lime field and white side bars without erasing white clothes."""
    pixels = np.asarray(reference.convert("RGB"), dtype=np.int16)
    height, width = pixels.shape[:2]
    yy, xx = np.indices((height, width))
    red, green, blue = (pixels[:, :, index] for index in range(3))
    lime = (green > 155) & (green - blue > 80) & (green - red > 25) & (blue < 140)
    white_border = (xx <= 43) | (xx >= 356)
    foreground = ~(lime | white_border)
    return Image.fromarray(foreground.astype(np.uint8) * 255, mode="L")


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
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


def perspective_overlay(reference_mask: Image.Image, rendered_mask: Image.Image) -> Image.Image:
    """Show source-only red, model-only blue, and shared dark pixels in one frame."""
    source = np.asarray(reference_mask.convert("L"), dtype=np.uint8) >= 128
    rendered = np.asarray(rendered_mask.convert("L"), dtype=np.uint8) >= 128
    pixels = np.full((*source.shape, 3), 245, dtype=np.uint8)
    pixels[source] = (205, 58, 65)
    pixels[rendered] = (45, 142, 183)
    pixels[source & rendered] = (37, 41, 47)
    return Image.fromarray(pixels, mode="RGB")


def actual_inventory(spec: dict[str, Any]) -> dict[str, int]:
    """Count semantic assemblies independently of the recorded inventory."""
    arm_records = spec["generation"]["arm_chains"]
    names = {cube["name"] for cube in spec["cubes"]}
    return {
        "arm_pairs": len({record["pair"] for record in arm_records}),
        "individual_arms": len(arm_records),
        "arm_segments": sum(len(record["segments"]) for record in arm_records),
        "head_support_arm_pairs": len(
            {record["pair"] for record in arm_records if record["head_contact"]}
        ),
        "head_support_hands": sum(record["head_contact"] for record in arm_records),
        "head_support_contacts": len(spec["generation"]["head_support_contacts"]),
        "black_sleeved_arm_pairs": len(
            {record["pair"] for record in arm_records if "black_sleeved" in record["pair"]}
        ),
        "bare_arm_pairs": len(
            {record["pair"] for record in arm_records if "black_sleeved" not in record["pair"]}
        ),
        "distinct_arm_depth_bands": len({record["depth_layer"] for record in arm_records}),
        "waist_tendrils": int(spec["generation"]["tendril"]["classification"] ==
                              "independent_non_arm_appendage"),
        "tendril_segments": len(spec["generation"]["tendril"]["segments"]),
        "chef_hat_cuboids": sum(name.startswith("hat_") for name in names),
        "detached_heads": int("head_face" in names),
        "grounded_feet": sum(name.endswith("_foot") for name in names),
    }


def main() -> None:
    """Write multiview renders, fixed-frame scores, and topology evidence."""
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

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    reference_mask = source_foreground_mask(reference)
    reference_mask.save(OUTPUT / "reference-mask.png", optimize=True)

    # This single estimated camera is declared before scoring and never altered
    # by any mask-fitting code. It retains the source's full 399x501 frame.
    camera = PerspectiveCamera.from_orbit(
        (399, 501),
        yaw_degrees=0.0,
        pitch_degrees=0.0,
        vertical_fov_degrees=35.0,
        target=(0.0, 50.0, 0.0),
        distance=175.0,
        principal_point=(199.5, 259.0),
    )
    reference_keypoints: Mapping[str, tuple[float, float]] = {
        "hat_top": (199.0, 19.0),
        "head_center": (199.0, 117.0),
        "chin_tip": (199.0, 157.0),
        "outer_left_head_elbow": (117.0, 91.0),
        "inner_left_head_elbow": (131.0, 144.0),
        "rear_mid_left_elbow": (104.0, 184.0),
        "rear_low_left_elbow": (75.0, 275.0),
        "waist_knot": (199.0, 253.0),
        "tendril_left_turn": (70.0, 347.0),
        "tendril_right_tip": (300.0, 350.0),
        "cropped_foot_center": (199.0, 500.0),
    }
    world_keypoints = {
        "hat_top": (0.0, 101.8, 1.0),
        "head_center": (0.0, 82.0, 6.0),
        "chin_tip": (0.0, 75.05, 2.0),
        "outer_left_head_elbow": (-19.0, 86.0, -5.5),
        "inner_left_head_elbow": (-16.0, 75.0, 1.0),
        "rear_mid_left_elbow": (-21.0, 66.0, -9.0),
        "rear_low_left_elbow": (-26.0, 44.0, -12.0),
        "waist_knot": (0.0, 48.5, 8.0),
        "tendril_left_turn": (-26.0, 31.5, 11.5),
        "tendril_right_tip": (21.0, 30.0, 12.0),
        "cropped_foot_center": (0.0, 0.0, 2.0),
    }
    perspective, fixed = fixed_camera_perspective_evidence(
        spec,
        camera,
        reference_mask,
        reference_keypoints=reference_keypoints,
        world_keypoints=world_keypoints,
        atlas_image=atlas,
        placements=placements,
        background=LIGHT_BACKGROUND,
    )
    perspective.save(OUTPUT / "source-perspective.png", optimize=True)
    rendered_mask = foreground_mask(perspective, LIGHT_BACKGROUND[:3])
    perspective_overlay(reference_mask, rendered_mask).save(
        OUTPUT / "perspective-silhouette-overlap.png", optimize=True
    )
    (OUTPUT / "perspective-camera.json").write_text(
        json.dumps(fixed["camera"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    names = {cube["name"] for cube in spec["cubes"]}
    head_names = {
        name
        for name in names
        if name.startswith(("head_", "hat_", "chin", "nose", "left_ear", "right_ear",
                            "hair_cap", "outer_head_support", "inner_head_support"))
    }
    arm_names = {name for name in names if "_arm_" in name}
    tendril_names = {name for name in names if name.startswith("waist_tendril_")}
    body_names = {
        name
        for name in names
        if name.startswith(("chest_", "abdomen_", "shoulder_", "neck_", "left_collar",
                            "right_collar", "waist_", "skirt_", "apron_", "sash_"))
    }
    detail_selections = {
        "head support closeup": head_names,
        "arm layer closeup": arm_names | {"shoulder_bar", "abdomen_jacket", "pelvis_core"},
        "tendril closeup": tendril_names | {"pelvis_core", "apron_front"},
        "body depth closeup": body_names,
    }
    details = {
        label: render_view(
            spec,
            (0.75, 0.25, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=selection,
            background=LIGHT_BACKGROUND,
        )
        for label, selection in detail_selections.items()
    }
    for label, image in details.items():
        image.save(OUTPUT / f"{label.replace(' ', '-')}.png", optimize=True)

    contact_sheet(
        reference,
        {
            "fixed source camera": perspective,
            "front": views["front"],
            "isometric": views["isometric"],
            "left": views["left"],
            "right": views["right"],
            "back": views["back"],
            "top": views["top"],
            **details,
        },
        tile=(320, 320),
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)

    arm_records = spec["generation"]["arm_chains"]
    pair_depth_centers: dict[str, float] = {}
    for pair in sorted({record["pair"] for record in arm_records}):
        selected = {
            segment
            for record in arm_records
            if record["pair"] == pair
            for segment in record["segments"]
        }
        lower, upper = bounds_for(spec, selected)
        pair_depth_centers[pair] = round(float((lower[2] + upper[2]) / 2), 6)
    sorted_centers = sorted(pair_depth_centers.values())
    minimum_pair_depth_separation = min(
        second - first for first, second in zip(sorted_centers, sorted_centers[1:])
    )

    torso_names = {
        "pelvis_core", "abdomen_jacket", "chest_jacket", "shoulder_bar", "skirt_core"
    }
    torso_lower, torso_upper = bounds_for(spec, torso_names)
    torso_extents = torso_upper - torso_lower
    head_lower, _ = bounds_for(spec, {"head_face", "chin"})
    _, stump_upper = bounds_for(spec, {"neck_stump", "left_collar", "right_collar"})
    foot_ground_heights = {}
    for name in ("left_foot", "right_foot"):
        lower, _ = bounds_for(spec, {name})
        foot_ground_heights[name] = round(float(lower[1]), 6)

    structural_links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    support_links = [
        (record["hand_cube"], record["head_cube"], record["joint"])
        for record in spec["generation"]["head_support_contacts"]
    ]
    structural_audit = audit_attachments(spec, structural_links)
    support_audit = audit_attachments(spec, support_links)
    inventory = actual_inventory(spec)
    recorded_inventory = spec["generation"]["feature_inventory"]
    proportions = {
        "torso_depth_to_width": round(float(torso_extents[2] / torso_extents[0]), 6),
        "arm_depth_span": round(max(pair_depth_centers.values()) -
                                min(pair_depth_centers.values()), 6),
        "minimum_pair_depth_center_separation": round(minimum_pair_depth_separation, 6),
        "head_to_collar_negative_space": round(float(head_lower[1] - stump_upper[1]), 6),
        "foot_ground_heights": foot_ground_heights,
    }
    proportion_gates = {
        "torso_depth_to_width_at_least_0.45": proportions["torso_depth_to_width"] >= 0.45,
        "arm_depth_span_at_least_15": proportions["arm_depth_span"] >= 15.0,
        "head_is_visibly_detached": proportions["head_to_collar_negative_space"] > 0.25,
        "both_feet_grounded": all(abs(value) <= 0.05 for value in foot_ground_heights.values()),
    }
    feature_gate = (
        inventory == recorded_inventory
        and inventory["arm_pairs"] == 6
        and inventory["individual_arms"] == 12
        and inventory["head_support_contacts"] == 4
        and inventory["head_support_hands"] == 4
        and inventory["waist_tendrils"] == 1
    )
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-fixed-perspective-textured-cuboid-zbuffer-v1",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "source_projection": False,
        "reference_rights": "unknown; private ignored benchmark reference only",
        "single_view_hidden_geometry": spec["generation"]["single_view_hidden_geometry"],
        "fixed_camera_perspective": fixed,
        "source_iou_gate_at_least_0.62": fixed["silhouette"]["iou"] >= 0.62,
        "keypoint_mean_gate_at_most_0.06_subject_heights": (
            fixed["keypoints"]["mean_error_subject_heights"] <= 0.06
        ),
        "reference_frame_clipping": {
            "declared_edges": spec["generation"]["frame_clipping"],
            "measured_edges": fixed["silhouette"]["reference_touches_frame_edges"],
            "iou_cannot_establish_off_frame_footwear": True,
        },
        "feature_inventory": inventory,
        "recorded_feature_inventory_matches": inventory == recorded_inventory,
        "six_arm_pair_feature_gate": feature_gate,
        "arm_pair_depth_centers_z": pair_depth_centers,
        "proportions": proportions,
        "proportion_gates": proportion_gates,
        "all_proportion_gates_pass": all(proportion_gates.values()),
        "attachments": structural_audit,
        "declared_link_tree_covers_every_cube": (
            len(structural_links) == len(spec["cubes"]) - 1
            and {name for link in structural_links for name in link[:2]} == names
        ),
        "head_support_contact_audit": support_audit,
        "all_four_head_support_contacts_touch": (
            len(support_links) == 4 and support_audit["all_connected"]
        ),
        "tendril_classification": spec["generation"]["tendril"]["classification"],
        "views": [
            "source-perspective.png", "perspective-silhouette-overlap.png",
            "reference-mask.png", "front.png", "back.png", "left.png", "right.png",
            "top.png", "isometric.png", "head-support-closeup.png",
            "arm-layer-closeup.png", "tendril-closeup.png", "body-depth-closeup.png",
            "comparison-sheet.png", "perspective-camera.json",
        ],
        "limitations": [
            "Only one frontal illustration is available; fixed-camera evidence cannot establish "
            "the unseen back surfaces or exact hidden arm-root ordering.",
            "The source clips the feet, so footwear geometry is conservative and excluded from "
            "any claim of source-observed detail.",
            "Several arms overlap in the source; side and isometric renders verify chosen depth "
            "layers but do not convert those inferred layers into observed facts.",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (CYCLE / "results.json").write_text(
        json.dumps(
            {
                "cycle": 6,
                "asset": "falling_devil",
                "status": "ready_for_independent_review",
                "metrics": {
                    "fixed_camera_iou": fixed["silhouette"]["iou"],
                    "keypoint_mean_subject_heights": fixed["keypoints"][
                        "mean_error_subject_heights"
                    ],
                    "cuboids": len(spec["cubes"]),
                    "arm_pairs": inventory["arm_pairs"],
                    "head_support_contacts": inventory["head_support_contacts"],
                },
                "visual_review_required": True,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
