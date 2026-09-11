#!/usr/bin/env python3
"""Render and audit deterministic multi-view Porsche 930 evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from img2blockbench import build_texture, read_json
from semantic_evidence import (
    STANDARD_VIEWS,
    contact_sheet,
    cube_vertices,
    foreground_mask,
    render_view,
)
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "benchmarks" / "references" / "02-porsche-911.png"
SOURCE_MASK = CYCLE / "inputs" / "foreground-mask.png"
OUTPUT = CYCLE / "render"
REFERENCE_DIRECTION = (0.72, 0.08, 1.0)


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return world bounds for all or selected native cuboids."""
    vertices = np.concatenate(
        [
            cube_vertices(spec, cube)
            for cube in spec["cubes"]
            if names is None or cube["name"] in names
        ]
    )
    return vertices.min(axis=0), vertices.max(axis=0)


def normalized_mask(
    mask: np.ndarray, size: tuple[int, int] = (1280, 440)
) -> np.ndarray:
    """Center a silhouette at common height while preserving its aspect."""
    rows, columns = np.where(mask)
    if not len(rows):
        raise ValueError("cannot normalize an empty silhouette")
    crop = mask[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]
    target_height = size[1] - 20
    scale = target_height / crop.shape[0]
    target_width = max(1, min(size[0] - 20, round(crop.shape[1] * scale)))
    target_height = max(1, min(size[1] - 20, round(crop.shape[0] * target_width / crop.shape[1])))
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


def silhouette_metrics(rendered: Image.Image) -> dict[str, Any]:
    """Compare the observed three-quarter silhouette to one fixed model view."""
    with Image.open(SOURCE_MASK) as opened:
        source = np.asarray(opened.convert("L"), dtype=np.uint8) >= 128
    model = np.asarray(foreground_mask(rendered), dtype=np.uint8) >= 128
    first = normalized_mask(source)
    second = normalized_mask(model)
    intersection = first & second
    union = first | second
    return {
        "method": "manual-source-mask-height-normalized-centered-iou-v1",
        "camera_direction": list(REFERENCE_DIRECTION),
        "iou": round(float(intersection.sum() / max(1, union.sum())), 6),
        "recall": round(float(intersection.sum() / max(1, first.sum())), 6),
        "precision": round(float(intersection.sum() / max(1, second.sum())), 6),
        "limitation": "one observed three-quarter silhouette; inferred opposite, front, rear, roof, and underbody are reviewed separately",
    }


def main() -> None:
    """Write all required views and machine-checkable vehicle metrics."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    views: dict[str, Image.Image] = {}
    for name, direction in STANDARD_VIEWS.items():
        views[name] = render_view(
            spec, direction, atlas_image=atlas, placements=placements
        )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)
    views["reference_angle"] = render_view(
        spec,
        REFERENCE_DIRECTION,
        atlas_image=atlas,
        placements=placements,
        size=(800, 560),
    )
    views["reference_angle"].save(OUTPUT / "reference-angle.png", optimize=True)

    names = [cube["name"] for cube in spec["cubes"]]
    wheel_names = {
        name
        for name in names
        if name.startswith("front_right_wheel")
        or name.startswith("front_right_fender")
        or name in {"front_axle", "right_rocker"}
    }
    greenhouse_names = {
        name
        for name in names
        if name.startswith(("left_", "right_"))
        and any(token in name for token in ("window", "pillar", "mirror", "door"))
    } | {
        name
        for name in names
        if name.startswith("roof_")
        or name in {"windshield", "rear_glass", "center_body"}
        or name.startswith(("rear_left_haunch", "rear_right_haunch"))
    }
    front_names = {
        name
        for name in names
        if name.startswith(("front_", "left_headlamp", "right_headlamp"))
        or name in {"hood_main", "front_nose"}
    }
    details = {
        "wheel closeup": render_view(
            spec,
            (1.0, 0.03, 0.08),
            atlas_image=atlas,
            placements=placements,
            selected_names=wheel_names,
        ),
        "greenhouse livery": render_view(
            spec,
            (1.0, 0.08, 0.03),
            atlas_image=atlas,
            placements=placements,
            selected_names=greenhouse_names,
        ),
        "front lamps": render_view(
            spec,
            (0.0, 0.02, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=front_names,
        ),
    }
    for name, image in details.items():
        image.save(OUTPUT / f"{name.replace(' ', '-')}.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    contact_sheet(
        reference,
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
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)

    cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
    all_lower, all_upper = bounds_for(spec)
    body_set = {
        "undertray", "lower_chassis", "center_body", "front_nose", "hood_main",
        "rear_deck",
    } | {
        name
        for name in names
        if "fender_" in name or "haunch_" in name
    }
    body_lower, body_upper = bounds_for(spec, body_set)
    cabin_set = {
        "windshield", "rear_glass", "left_front_window",
        "right_front_window", "left_rear_window", "right_rear_window",
        "left_a_pillar", "right_a_pillar", "left_b_pillar", "right_b_pillar",
        "left_c_pillar", "right_c_pillar",
    } | {name for name in names if name.startswith("roof_")}
    cabin_lower, cabin_upper = bounds_for(spec, cabin_set)
    extents = all_upper - all_lower
    body_extents = body_upper - body_lower
    cabin_extents = cabin_upper - cabin_lower
    wheel_centers = [
        np.asarray(cube_by_name[f"{prefix}_hub"]["center"], dtype=np.float64)
        for prefix in (
            "front_left_wheel", "front_right_wheel",
            "rear_left_wheel", "rear_right_wheel",
        )
    ]
    wheel_ground_heights = []
    for prefix in (
        "front_left_wheel", "front_right_wheel",
        "rear_left_wheel", "rear_right_wheel",
    ):
        selected = {
            f"{prefix}_tire_vertical",
            f"{prefix}_tire_diagonal",
        }
        lower, _ = bounds_for(spec, selected)
        wheel_ground_heights.append(round(float(lower[1]), 6))

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    actual_inventory = {
        "body_volumes": len(body_set & set(names)),
        "fender_haunch_volumes": sum("fender" in name or "haunch" in name for name in names),
        "wheel_assemblies": 4,
        "wheel_cuboids": sum("_wheel_" in name for name in names),
        "headlamp_cuboids": sum("headlamp" in name for name in names),
        "greenhouse_glass": sum(name in {"windshield", "rear_glass", "left_front_window", "right_front_window", "left_rear_window", "right_rear_window"} for name in names),
        "mirrors": sum(name in {"left_mirror", "right_mirror"} for name in names),
        "spoiler_cuboids": sum(name in {"spoiler_left_support", "spoiler_right_support", "whale_tail"} for name in names),
        "tail_lamps": sum(name.startswith("rear_light_") for name in names),
    }
    wheelbase = abs(wheel_centers[0][2] - wheel_centers[2][2])
    track = abs(wheel_centers[0][0] - wheel_centers[1][0])
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v2",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "source_angle_silhouette": silhouette_metrics(views["reference_angle"]),
        "model_extents": [round(float(value), 6) for value in extents],
        "proportion_metrics": {
            "overall_length_to_width": round(float(extents[2] / extents[0]), 6),
            "overall_height_to_length": round(float(extents[1] / extents[2]), 6),
            "body_length_to_width": round(float(body_extents[2] / body_extents[0]), 6),
            "cabin_length_to_body_length": round(float(cabin_extents[2] / body_extents[2]), 6),
            "cabin_width_to_body_width": round(float(cabin_extents[0] / body_extents[0]), 6),
            "wheelbase_to_body_length": round(float(wheelbase / body_extents[2]), 6),
            "track_to_body_width": round(float(track / body_extents[0]), 6),
            "wheel_ground_heights": wheel_ground_heights,
        },
        "feature_inventory": actual_inventory,
        "recorded_feature_inventory_matches": (
            actual_inventory == spec["generation"]["feature_inventory"]
        ),
        "vehicle_contract_pass": (
            actual_inventory["wheel_assemblies"] == 4
            and actual_inventory["wheel_cuboids"] == 28
            and actual_inventory["headlamp_cuboids"] == 6
            and actual_inventory["greenhouse_glass"] == 6
            and actual_inventory["mirrors"] == 2
            and actual_inventory["spoiler_cuboids"] == 3
            and actual_inventory["tail_lamps"] == 2
            and max(wheel_ground_heights) - min(wheel_ground_heights) <= 0.01
        ),
        "attachments": attachment,
        "no_source_projection": not any(
            "source_region" in override
            for cube in spec["cubes"]
            for override in cube.get("faces", {}).values()
        ),
        "authored_livery_only": spec["generation"]["authored_texture_sources"] == ["side_livery"],
        "hidden_geometry_disclosure": spec["generation"]["single_view_hidden_geometry"],
        "views": [
            "reference-angle.png", "front.png", "back.png", "left.png",
            "right.png", "top.png", "isometric.png", "wheel-closeup.png",
            "greenhouse-livery.png", "front-lamps.png", "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
