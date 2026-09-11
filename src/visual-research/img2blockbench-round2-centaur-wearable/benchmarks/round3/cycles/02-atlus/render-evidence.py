#!/usr/bin/env python3
"""Render and measure holistic multi-axis Atlus evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from img2blockbench import build_texture, read_json
from semantic_evidence import (
    STANDARD_VIEWS,
    contact_sheet,
    cube_vertices,
    foreground_mask,
    render_view,
)
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "round3-inputs" / "atlus.png"
MULTIVIEW = ROOT / "round3-inputs" / "atlus-multiview"
LOCAL_REVIEW = ROOT / "round3-inputs" / "local-review" / "02-atlus"
OUTPUT = CYCLE / "render"
BACKGROUND = (238, 241, 243, 255)
REFERENCE_DIRECTION = (1.0, 0.32, 1.0)


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


def silhouette_occupancy(image: Image.Image) -> float:
    """Return the fraction of a view occupied by model silhouette pixels."""
    mask = np.asarray(foreground_mask(image, BACKGROUND[:3]), dtype=np.uint8)
    return round(float(np.count_nonzero(mask) / mask.size), 6)


def silhouette_aspect(image: Image.Image) -> float:
    """Return foreground bounding-box width divided by height."""
    bbox = foreground_mask(image, BACKGROUND[:3]).getbbox()
    if bbox is None or bbox[3] <= bbox[1]:
        raise ValueError("render silhouette is empty")
    return round(float((bbox[2] - bbox[0]) / (bbox[3] - bbox[1])), 6)


def image_difference(first: Image.Image, second: Image.Image) -> float:
    """Return normalized RGB mean absolute difference for equal-sized renders."""
    left = np.asarray(first.convert("RGB"), dtype=np.float32)
    right = np.asarray(second.convert("RGB"), dtype=np.float32)
    return round(float(np.abs(left - right).mean() / 255.0), 6)


def source_tile(path: Path, size: tuple[int, int] = (360, 260)) -> Image.Image:
    """Fit one reference image into a review tile without stretching it."""
    with Image.open(path) as opened:
        return ImageOps.contain(opened.convert("RGBA"), size, Image.Resampling.LANCZOS)


def main() -> None:
    """Write canonical views, closeups, comparison sheets, and volume gates."""
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
            size=(720, 560),
            background=BACKGROUND,
        )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)
    views["reference-angle"] = render_view(
        spec,
        REFERENCE_DIRECTION,
        atlas_image=atlas,
        placements=placements,
        size=(760, 560),
        background=BACKGROUND,
    )
    views["reference-angle"].save(OUTPUT / "reference-angle.png", optimize=True)
    views["underside"] = render_view(
        spec,
        (-1.0, -0.58, 1.0),
        atlas_image=atlas,
        placements=placements,
        size=(720, 560),
        background=BACKGROUND,
    )
    views["underside"].save(OUTPUT / "underside.png", optimize=True)

    names = {cube["name"] for cube in spec["cubes"]}
    side_names = {
        name
        for name in names
        if name.startswith(("left_", "right_")) or name in {"mid_fuselage", "lower_fuselage"}
    }
    rear_names = {
        name
        for name in names
        if "rear" in name or "thruster" in name or name in {"rear_cabin", "rear_bumper"}
    }
    underside_names = {
        name
        for name in names
        if (
            "gear" in name
            or "belly" in name
            or "lower" in name
            or "bottom_fin" in name
            or "hover" in name
            or name.startswith("ventral_")
        )
    }
    detail_images = {
        "side-pod-closeup": render_view(
            spec,
            (1.0, 0.14, 0.15),
            atlas_image=atlas,
            placements=placements,
            selected_names=side_names,
            size=(720, 560),
            background=BACKGROUND,
        ),
        "rear-closeup": render_view(
            spec,
            (0.1, 0.12, -1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=rear_names,
            size=(720, 560),
            background=BACKGROUND,
        ),
        "underside-closeup": render_view(
            spec,
            (-0.65, -1.0, 0.4),
            atlas_image=atlas,
            placements=placements,
            selected_names=underside_names,
            size=(720, 560),
            background=BACKGROUND,
        ),
    }
    for name, image in detail_images.items():
        image.save(OUTPUT / f"{name}.png", optimize=True)

    # This committed sheet contains generated model renders only. Private source
    # pixels are written exclusively below the ignored round3-inputs tree.
    all_angle_sheet = contact_sheet(
        views["reference-angle"],
        {
            "front": views["front"],
            "back": views["back"],
            "left": views["left"],
            "right": views["right"],
            "top": views["top"],
            "isometric": views["isometric"],
            "underside": views["underside"],
            **detail_images,
        },
        columns=4,
        tile=(360, 280),
    )
    all_angle_draw = ImageDraw.Draw(all_angle_sheet)
    all_angle_draw.rectangle((0, 0, 359, 37), fill="#09111a")
    all_angle_draw.text((12, 10), "MODEL REFERENCE ANGLE", fill="#f0bd31")
    all_angle_sheet.save(OUTPUT / "all-angle-sheet.png", optimize=True)

    LOCAL_REVIEW.mkdir(parents=True, exist_ok=True)
    with Image.open(REFERENCE) as opened:
        original_reference = opened.convert("RGBA")
    contact_sheet(
        original_reference,
        {
            "reference angle": views["reference-angle"],
            "front": views["front"],
            "back": views["back"],
            "left": views["left"],
            "right": views["right"],
            "top": views["top"],
            "isometric": views["isometric"],
            "underside": views["underside"],
            **detail_images,
        },
        columns=4,
        tile=(360, 280),
    ).save(LOCAL_REVIEW / "user-source-comparison.png", optimize=True)

    # Pair each independently observed direction with the corresponding native
    # view. These are review evidence, not claims of calibrated camera matching.
    source_views = {
        "source front quarter": source_tile(MULTIVIEW / "front-quarter.webp"),
        "model isometric": views["isometric"],
        "source front": source_tile(MULTIVIEW / "front.webp"),
        "model front": views["front"],
        "source side": source_tile(MULTIVIEW / "side.webp"),
        "model side": views["left"],
        "source rear": source_tile(MULTIVIEW / "rear.webp"),
        "model rear": views["back"],
        "source top": source_tile(MULTIVIEW / "top.webp"),
        "model top": views["top"],
    }
    # ``contact_sheet`` takes its first image separately; retaining the other
    # nine tiles keeps source/model pair order explicit.
    first = source_views.pop("source front quarter")
    contact_sheet(first, source_views, columns=2, tile=(420, 300)).save(
        LOCAL_REVIEW / "multiview-source-comparison.png", optimize=True
    )

    all_lower, all_upper = bounds_for(spec)
    extents = all_upper - all_lower
    center_names = {
        "belly_keel", "lower_fuselage", "mid_fuselage", "upper_cabin",
        "nose_deck", "nose_mid", "nose_tip", "nose_lower", "rear_cabin",
        "rear_upper_taper", "rear_bumper",
    }
    center_lower, center_upper = bounds_for(spec, center_names)
    center_extents = center_upper - center_lower
    left_names = set(spec["generation"]["side_pod_feature_names"]["left"])
    right_names = set(spec["generation"]["side_pod_feature_names"]["right"])
    left_lower, left_upper = bounds_for(spec, left_names)
    right_lower, right_upper = bounds_for(spec, right_names)
    left_extents = left_upper - left_lower
    right_extents = right_upper - right_lower

    shoe_names = {record["shoe"] for record in spec["generation"]["landing_gear"]}
    shoe_ground_heights = [round(float(bounds_for(spec, {name})[0][1]), 6) for name in sorted(shoe_names)]
    attachment_links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, attachment_links)

    occupancy = {
        name: silhouette_occupancy(views[name])
        for name in ("front", "back", "left", "right", "top", "isometric", "underside")
    }
    metrics = {
        "overall_extents_xyz": [round(float(value), 6) for value in extents],
        "central_hull_extents_xyz": [round(float(value), 6) for value in center_extents],
        "left_pod_extents_xyz": [round(float(value), 6) for value in left_extents],
        "right_pod_extents_xyz": [round(float(value), 6) for value in right_extents],
        "overall_length_to_width": round(float(extents[2] / extents[0]), 6),
        "overall_width_to_height": round(float(extents[0] / extents[1]), 6),
        "central_hull_length_to_width": round(float(center_extents[2] / center_extents[0]), 6),
        "left_pod_length_fraction": round(float(left_extents[2] / extents[2]), 6),
        "right_pod_length_fraction": round(float(right_extents[2] / extents[2]), 6),
        "minimum_axis_to_maximum_axis": round(float(extents.min() / extents.max()), 6),
        "shoe_ground_heights": shoe_ground_heights,
        "orthographic_silhouette_occupancy": occupancy,
        "front_back_pixel_difference": image_difference(views["front"], views["back"]),
        "top_underside_pixel_difference": image_difference(views["top"], views["underside"]),
    }
    gates = {
        "overall_length_to_width_at_least_1.15": metrics["overall_length_to_width"] >= 1.15,
        "overall_width_to_height_at_least_1.35": metrics["overall_width_to_height"] >= 1.35,
        "central_hull_length_to_width_at_least_1.75": metrics["central_hull_length_to_width"] >= 1.75,
        "both_side_pods_cover_at_least_65_percent_length": (
            metrics["left_pod_length_fraction"] >= 0.65
            and metrics["right_pod_length_fraction"] >= 0.65
        ),
        "three_axis_nonflatness_at_least_0.25": metrics["minimum_axis_to_maximum_axis"] >= 0.25,
        "all_primary_views_have_at_least_12_percent_occupancy": all(
            occupancy[name] >= 0.12
            for name in ("front", "back", "left", "right", "top", "isometric")
        ),
        "four_grounded_shoes": (
            len(shoe_ground_heights) == 4
            and max(abs(value) for value in shoe_ground_heights) <= 0.01
        ),
        "front_and_back_are_visibly_distinct": metrics["front_back_pixel_difference"] >= 0.02,
        "top_and_underside_are_visibly_distinct": metrics["top_underside_pixel_difference"] >= 0.02,
        "all_declared_attachments_connected": attachment["all_connected"],
    }

    reference_hashes = {
        record["view"]: record["sha256"]
        for record in spec["generation"]["geometry_references"]
    }
    directional_evidence = {
        "front-quarter": {
            "reference_sha256": reference_hashes["front-quarter"],
            "observed_anchors": ["tapered nose", "outer rib stacks", "broad rescue door"],
            "metric": "isometric_silhouette_occupancy",
            "value": occupancy["isometric"],
            "gate": occupancy["isometric"] >= 0.25,
        },
        "front": {
            "reference_sha256": reference_hashes["front"],
            "observed_anchors": ["central louver bank", "two four-barrel clusters", "paired outer pods"],
            "metric": "front_width_to_height",
            "value": silhouette_aspect(views["front"]),
            "gate": 1.1 <= silhouette_aspect(views["front"]) <= 2.2,
        },
        "side": {
            "reference_sha256": reference_hashes["side"],
            "observed_anchors": ["long rescue door", "front and rear hover pods", "low roofline"],
            "metric": "side_length_to_height",
            "value": silhouette_aspect(views["left"]),
            "gate": silhouette_aspect(views["left"]) >= 1.8,
        },
        "rear": {
            "reference_sha256": reference_hashes["rear"],
            "observed_anchors": ["large service panel", "vertical red rails", "layered pod exhausts"],
            "metric": "rear_width_to_height",
            "value": silhouette_aspect(views["back"]),
            "gate": 1.1 <= silhouette_aspect(views["back"]) <= 2.2,
        },
        "top": {
            "reference_sha256": reference_hashes["top"],
            "observed_anchors": ["long central spine", "paired roof ports", "four-corner pod plan"],
            "metric": "top_length_to_width",
            "value": round(1.0 / silhouette_aspect(views["top"]), 6),
            "gate": 1.0 / silhouette_aspect(views["top"]) >= 1.45,
        },
    }

    inventory = spec["generation"]["feature_inventory"]
    feature_gates = {
        "cuboid_budget_140_to_170": 140 <= len(spec["cubes"]) <= 170,
        "paired_side_pods_have_at_least_20_cuboids_each": (
            inventory["left_side_pod_cuboids"] >= 20
            and inventory["right_side_pod_cuboids"] >= 20
        ),
        "at_least_40_side_detail_cuboids": inventory["side_detail_cuboids"] >= 40,
        "four_landing_modules": inventory["landing_gear_modules"] == 4,
        "at_least_six_rear_thruster_cuboids": inventory["rear_thruster_cuboids"] >= 6,
        "two_four_barrel_weapon_clusters": inventory["under_nose_weapon_barrels"] == 8,
        "eight_weapon_muzzle_collars": inventory["under_nose_weapon_muzzles"] == 8,
        "eight_layered_rear_pod_louvers": inventory["rear_pod_louvers"] == 8,
        "chunky_ventral_machinery": inventory["ventral_machinery_cuboids"] >= 6,
        "three_roof_aerials": inventory["roof_aerials"] == 3,
        "bilateral_medical_crosses": inventory["medical_marking_strokes"] >= 8,
        "all_materials_are_noise_free_solid_panels": all(
            record["pattern"] == "solid" for record in spec["materials"].values()
        ),
    }
    model_only_views = [
        "front.png", "back.png", "left.png", "right.png", "top.png",
        "isometric.png", "reference-angle.png", "underside.png",
        "side-pod-closeup.png", "rear-closeup.png", "underside-closeup.png",
        "all-angle-sheet.png",
    ]
    render_sha256 = {
        relative: hashlib.sha256((OUTPUT / relative).read_bytes()).hexdigest()
        for relative in model_only_views
    }
    evaluation = {
        "schema_version": 1,
        "model_id": spec["id"],
        "renderer": "deterministic-textured-cuboid-zbuffer-v3",
        "evidence_basis": "five observed exterior directions plus one user screenshot",
        "camera_calibration_claimed": False,
        "hidden_geometry_established_by_source": False,
        "underside_inference_disclosed": True,
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "landmarks": len(spec["landmarks"]),
        "metrics": metrics,
        "anti_pancake_gates": gates,
        "all_anti_pancake_gates_pass": all(gates.values()),
        "feature_inventory": inventory,
        "feature_gates": feature_gates,
        "all_feature_gates_pass": all(feature_gates.values()),
        "multiview_directional_evidence": directional_evidence,
        "all_five_reference_direction_gates_pass": all(
            record["gate"] for record in directional_evidence.values()
        ),
        "attachments": attachment,
        "render_sha256": render_sha256,
        "views": model_only_views,
        "ignored_local_source_review": [
            "round3-inputs/local-review/02-atlus/user-source-comparison.png",
            "round3-inputs/local-review/02-atlus/multiview-source-comparison.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
