#!/usr/bin/env python3
"""Render and measure deterministic multi-view goldfinch evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from img2blockbench import build_texture, read_json
from semantic_evidence import (
    STANDARD_VIEWS,
    bilateral_metrics,
    contact_sheet,
    cube_vertices,
    foreground_mask,
    render_view,
)
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "benchmarks" / "references" / "01-american-goldfinch.jpg"
SOURCE_MASK = CYCLE / "segmentation" / "foreground-mask.png"
OUTPUT = CYCLE / "render"


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return world bounds for all or selected cuboids."""
    vertices = np.concatenate(
        [
            cube_vertices(spec, cube)
            for cube in spec["cubes"]
            if names is None or cube["name"] in names
        ]
    )
    return vertices.min(axis=0), vertices.max(axis=0)


def normalized_mask(mask: np.ndarray, size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """Center a silhouette at common height while preserving its aspect ratio."""
    rows, columns = np.where(mask)
    if not len(rows):
        raise ValueError("cannot normalize an empty silhouette")
    crop = mask[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]
    target_height = size[1] - 16
    scale = target_height / crop.shape[0]
    target_width = max(1, round(crop.shape[1] * scale))
    if target_width > size[0] - 16:
        target_width = size[0] - 16
        scale = target_width / crop.shape[1]
        target_height = max(1, round(crop.shape[0] * scale))
    resized = Image.fromarray(crop.astype(np.uint8) * 255, mode="L").resize(
        (target_width, target_height), Image.Resampling.NEAREST
    )
    canvas = np.zeros((size[1], size[0]), dtype=bool)
    left = (size[0] - target_width) // 2
    top = (size[1] - target_height) // 2
    canvas[top : top + target_height, left : left + target_width] = (
        np.asarray(resized, dtype=np.uint8) >= 128
    )
    return canvas


def source_profile_metrics(
    source_mask_image: Image.Image, model_profile: Image.Image
) -> tuple[dict[str, Any], Image.Image]:
    """Compare the observed, leg-free side profile without claiming hidden shape."""
    source_raw = np.asarray(source_mask_image.convert("L"), dtype=np.uint8) >= 128
    model_raw = np.asarray(foreground_mask(model_profile), dtype=np.uint8) >= 128
    source_rows, source_columns = np.where(source_raw)
    model_rows, model_columns = np.where(model_raw)
    source_aspect = (source_columns.max() - source_columns.min() + 1) / (
        source_rows.max() - source_rows.min() + 1
    )
    model_aspect = (model_columns.max() - model_columns.min() + 1) / (
        model_rows.max() - model_rows.min() + 1
    )
    source = normalized_mask(source_raw)
    model = normalized_mask(model_raw)
    intersection = source & model
    union = source | model
    metrics = {
        "method": "source-segmentation-and-semantic-main-body-height-aligned-iou-v1",
        "iou": round(float(intersection.sum() / max(1, union.sum())), 6),
        "recall": round(float(intersection.sum() / max(1, source.sum())), 6),
        "precision": round(float(intersection.sum() / max(1, model.sum())), 6),
        "source_aspect": round(float(source_aspect), 6),
        "model_aspect": round(float(model_aspect), 6),
        "aspect_relative_error": round(abs(model_aspect / source_aspect - 1.0), 6),
        "included_model_anatomy": (
            "body, neck, head, cap, eyes, bill, and the proximal/middle folded wings"
        ),
        "excluded_model_anatomy": (
            "legs, toes, claws, inferred tail, and distal wing tips beyond the source crop"
        ),
        "limitation": (
            "The source tail is cropped and its foot is branch-occluded; this validates only "
            "the observed side-profile envelope, not hidden-side depth or detailed correspondence"
        ),
    }
    overlay = np.zeros((source.shape[0], source.shape[1], 4), dtype=np.uint8)
    overlay[:, :, 3] = 255
    overlay[source & ~model] = (255, 94, 94, 255)
    overlay[model & ~source] = (83, 171, 255, 255)
    overlay[intersection] = (245, 220, 64, 255)
    return metrics, Image.fromarray(overlay, mode="RGBA")


def main() -> None:
    """Write all required views, closeups, topology checks, and profile metrics."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    views: dict[str, Image.Image] = {}
    for name, direction in STANDARD_VIEWS.items():
        views[name] = render_view(
            spec, direction, atlas_image=atlas, placements=placements
        )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)

    head_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(
            (
                "head_volume_", "black_cap_", "left_eye", "right_eye",
                "upper_beak_", "lower_beak_",
            )
        )
        or cube["name"] == "neck_bridge"
    }
    main_body_names = {
        cube["name"]
        for cube in spec["cubes"]
        if not cube["name"].startswith(
            (
                "leg_", "toe_", "left_thigh_fluff", "right_thigh_fluff",
                "tail_feather_", "wing_left_3", "wing_right_3",
            )
        )
    }
    wing_joint_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(
            ("body_volume_", "wing_left_", "wing_right_", "white_bar_")
        )
    }
    feet_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(
            ("leg_", "toe_", "left_thigh_fluff", "right_thigh_fluff")
        )
    }
    details = {
        "left head closeup": render_view(
            spec,
            STANDARD_VIEWS["left"],
            atlas_image=atlas,
            placements=placements,
            selected_names=head_names,
        ),
        "right head closeup": render_view(
            spec,
            STANDARD_VIEWS["right"],
            atlas_image=atlas,
            placements=placements,
            selected_names=head_names,
        ),
        "wing joints": render_view(
            spec,
            STANDARD_VIEWS["isometric"],
            atlas_image=atlas,
            placements=placements,
            selected_names=wing_joint_names,
        ),
        "feet joints": render_view(
            spec,
            (0.8, 0.25, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=feet_names,
        ),
    }
    for name, image in details.items():
        image.save(OUTPUT / f"{name.replace(' ', '-')}.png", optimize=True)

    source_profile = render_view(
        spec,
        STANDARD_VIEWS["left"],
        atlas_image=atlas,
        placements=placements,
        selected_names=main_body_names,
    )
    source_profile.save(OUTPUT / "source-profile.png", optimize=True)
    with Image.open(SOURCE_MASK) as opened:
        profile_metrics, overlap = source_profile_metrics(opened, source_profile)
    overlap.save(OUTPUT / "source-profile-overlap.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    contact_sheet(
        reference,
        {
            "source profile": source_profile,
            "front": views["front"],
            "back": views["back"],
            "left": views["left"],
            "right": views["right"],
            "top": views["top"],
            "isometric": views["isometric"],
            **details,
            "profile overlap": overlap,
        },
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    cube_names = [cube["name"] for cube in spec["cubes"]]
    actual_inventory = {
        "body_volumes": sum(name.startswith("body_volume_") for name in cube_names),
        "head_volumes": sum(name.startswith("head_volume_") for name in cube_names),
        "cap_volumes": sum(name.startswith("black_cap_") for name in cube_names),
        "eyes": sum(name in {"left_eye", "right_eye"} for name in cube_names),
        "beak_segments": sum(name.startswith(("upper_beak_", "lower_beak_")) for name in cube_names),
        "wing_chains": 2,
        "wing_segments": sum(name.startswith(("wing_left_", "wing_right_")) for name in cube_names),
        "raised_white_wing_patches": sum(name.startswith("white_bar_") for name in cube_names),
        "wing_bar_landmarks": sum("wing_bar" in item["name"] for item in spec["landmarks"]),
        "tail_segments": sum(name.startswith("tail_feather_") for name in cube_names),
        "leg_chains": 2,
        "leg_segments": sum(name.startswith(("leg_left_", "leg_right_")) for name in cube_names),
        "toe_chains": 6,
        "toe_and_claw_segments": sum(name.startswith("toe_") for name in cube_names),
    }
    recorded_inventory = spec["generation"]["feature_inventory"]
    all_lower, all_upper = bounds_for(spec)
    body_lower, body_upper = bounds_for(
        spec, {name for name in cube_names if name.startswith("body_volume_")}
    )
    head_lower, head_upper = bounds_for(spec, head_names)
    model_extents = all_upper - all_lower
    body_extents = body_upper - body_lower
    head_extents = head_upper - head_lower
    head_left = render_view(
        spec,
        STANDARD_VIEWS["left"],
        atlas_image=atlas,
        placements=placements,
        selected_names=head_names,
    )
    head_right = render_view(
        spec,
        STANDARD_VIEWS["right"],
        atlas_image=atlas,
        placements=placements,
        selected_names=head_names,
    )
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v2",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "model_extents": [round(float(value), 6) for value in model_extents],
        "body_extents": [round(float(value), 6) for value in body_extents],
        "body_depth_to_length": round(float(body_extents[0] / body_extents[2]), 6),
        "body_height_to_length": round(float(body_extents[1] / body_extents[2]), 6),
        "head_to_body_height": round(float(head_extents[1] / body_extents[1]), 6),
        "profile": profile_metrics,
        "bilateral_head": bilateral_metrics(head_left, head_right),
        "feature_inventory": actual_inventory,
        "recorded_feature_inventory_matches": actual_inventory == recorded_inventory,
        "feature_contract_pass": (
            actual_inventory == recorded_inventory
            and actual_inventory["eyes"] == 2
            and actual_inventory["wing_chains"] == 2
            and actual_inventory["wing_segments"] == 6
            and actual_inventory["raised_white_wing_patches"] == 4
            and actual_inventory["wing_bar_landmarks"] == 4
            and actual_inventory["leg_chains"] == 2
            and actual_inventory["toe_chains"] == 6
            and actual_inventory["toe_and_claw_segments"] == 12
        ),
        "attachments": attachment,
        "views": [
            "source-profile.png", "front.png", "back.png", "left.png", "right.png",
            "top.png", "isometric.png", "left-head-closeup.png",
            "right-head-closeup.png", "wing-joints.png", "feet-joints.png",
            "source-profile-overlap.png", "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
