#!/usr/bin/env python3
"""Render and audit deterministic multi-view Tomato Devil evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from img2blockbench import build_texture, exported_cube_bounds, read_json
from photo_reconstruction import _rotate_point
from semantic_evidence import STANDARD_VIEWS, contact_sheet, cube_vertices, render_view
from semantic_geometry import audit_attachments


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
REFERENCE = ROOT / "benchmarks" / "references" / "05-tomato-devil.png"
OUTPUT = CYCLE / "render"


# Source measurements normalized inside the visible tomato globe. These are
# intentionally not symmetrized; the chaotic eye constellation is canonical.
SOURCE_BODY_BBOX = (18, 68, 463, 519)
SOURCE_EYE_PIXELS = (
    (111, 122),
    (89, 190),
    (236, 172),
    (325, 221),
    (410, 122),
    (450, 230),
    (378, 325),
    (147, 284),
    (31, 312),
    (107, 397),
)


def declared_attachments(spec: dict[str, Any]) -> list[tuple[str, str, tuple[float, ...]]]:
    """Read the generator's single authoritative semantic attachment manifest."""
    records = spec.get("generation", {}).get("declared_attachments")
    if not isinstance(records, list) or not records:
        raise ValueError("model has no declared attachment manifest")
    return [
        (record["first"], record["second"], tuple(float(value) for value in record["joint"]))
        for record in records
    ]


def bounds_for(spec: dict[str, Any], names: set[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return world bounds for all or selected cuboids."""
    vertices = np.concatenate(
        [
            cube_vertices(spec, cube)
            for cube in spec["cubes"]
            if names is None or cube["name"] in names
        ]
    )
    return vertices.min(axis=0), vertices.max(axis=0)


def eye_layout_metrics(spec: dict[str, Any]) -> dict[str, Any]:
    """Compare modeled eye centers to measured source positions on the globe."""
    cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
    body_names = {cube["name"] for cube in spec["cubes"] if cube["name"].startswith("body_")}
    lower, upper = bounds_for(spec, body_names)
    width = float(upper[0] - lower[0])
    height = float(upper[1] - lower[1])
    modeled = []
    errors = []
    source_left, source_top, source_right, source_bottom = SOURCE_BODY_BBOX
    targets = tuple(
        (
            (x - source_left) / (source_right - source_left),
            (y - source_top) / (source_bottom - source_top),
        )
        for x, y in SOURCE_EYE_PIXELS
    )
    for index, target in enumerate(targets, start=1):
        center = cube_by_name[f"eye_bulb_{index}"]["center"]
        normalized = (
            (float(center[0]) - lower[0]) / width,
            (upper[1] - float(center[1])) / height,
        )
        modeled.append([round(value, 6) for value in normalized])
        errors.append(math.dist(normalized, target))
    return {
        "annotation_method": "manual source-pixel centers normalized by annotated globe bbox; not an independent fidelity score",
        "source_body_bbox_pixels": list(SOURCE_BODY_BBOX),
        "source_eye_centers_pixels": [list(value) for value in SOURCE_EYE_PIXELS],
        "source_targets_normalized": [[round(item, 6) for item in value] for value in targets],
        "modeled_centers_normalized": modeled,
        "rms_error_body_widths": round(
            math.sqrt(sum(value * value for value in errors) / len(errors)), 6
        ),
        "maximum_error_body_widths": round(max(errors), 6),
        "asymmetry_preserved": len(set(tuple(value) for value in modeled)) == 10,
    }


def segment_endpoint(cube: dict[str, Any]) -> tuple[float, float, float]:
    """Recover the authored end joint from a semantic chain cuboid."""
    origin = tuple(float(value) for value in cube["origin"])
    center = tuple(float(value) for value in cube["center"])
    authored_length = 2 * (center[1] - origin[1])
    return _rotate_point(
        (origin[0], origin[1] + authored_length, origin[2]),
        origin,
        tuple(float(value) for value in cube["rotation"]),
    )


def main() -> None:
    """Write all review images plus machine-checkable semantic metrics."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    views: dict[str, Image.Image] = {}
    for name, direction in STANDARD_VIEWS.items():
        views[name] = render_view(
            spec, direction, atlas_image=atlas, placements=placements
        )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)

    eye_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(("eye_stalk_", "eye_bulb_", "eye_band_", "iris_"))
    }
    mouth_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(("mouth_", "tooth_"))
    }
    arm_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(("arm_3_", "arm_4_"))
    }
    detail_views = {
        "ten eyes": render_view(
            spec,
            (0.0, 0.02, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=eye_names,
        ),
        "zipper mouth": render_view(
            spec,
            (0.0, 0.02, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=mouth_names,
        ),
        "arm joints": render_view(
            spec,
            (0.35, 0.12, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=arm_names,
        ),
    }
    for name, image in detail_views.items():
        image.save(OUTPUT / f"{name.replace(' ', '-')}.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    sheet_views = {
        "front": views["front"],
        "back": views["back"],
        "left": views["left"],
        "right": views["right"],
        "top": views["top"],
        "isometric": views["isometric"],
        **detail_views,
    }
    contact_sheet(reference, sheet_views).save(
        OUTPUT / "comparison-sheet.png", optimize=True
    )

    attachment = audit_attachments(spec, declared_attachments(spec))
    all_lower, all_upper = bounds_for(spec)
    body_names = {cube["name"] for cube in spec["cubes"] if cube["name"].startswith("body_")}
    body_lower, body_upper = bounds_for(spec, body_names)
    body_extents = body_upper - body_lower
    all_arm_names = {
        cube["name"] for cube in spec["cubes"] if cube["name"].startswith("arm_")
    }
    arm_lower, arm_upper = bounds_for(spec, all_arm_names)
    arm_extents = arm_upper - arm_lower
    full_extents = all_upper - all_lower
    recorded_inventory = spec["generation"]["feature_inventory"]
    cube_names = [cube["name"] for cube in spec["cubes"]]
    actual_inventory = {
        "body_volumes": sum(name.startswith("body_") for name in cube_names),
        "eye_assemblies": sum(name.startswith("eye_bulb_") for name in cube_names),
        "eye_stalk_segments": sum(name.startswith("eye_stalk_") for name in cube_names),
        "red_irises": sum(name.startswith("iris_") for name in cube_names),
        "rounded_eye_bands": sum(name.startswith("eye_band_") for name in cube_names),
        "pupil_landmarks": sum(
            landmark["name"].startswith("pupil_") for landmark in spec["landmarks"]
        ),
        "arm_chains": sum(
            bone["name"].startswith("arm_") and bone["name"].endswith("_1")
            for bone in spec["bones"]
        ),
        "arm_segments": sum(
            name.startswith("arm_")
            and "_finger_" not in name
            and name.rsplit("_", 1)[-1] in {"1", "2", "3"}
            for name in cube_names
        ),
        "arm_palms": sum(name.endswith("_palm") for name in cube_names),
        "grounded_fingers": sum("_finger_" in name for name in cube_names),
        "stem_leaves": sum(
            bone["name"].startswith("stem_leaf_")
            and bone["name"].endswith("_1")
            for bone in spec["bones"]
        ),
        "stem_leaf_segments": sum(name.startswith("stem_leaf_") for name in cube_names),
        "mouth_teeth": sum(name.startswith("tooth_") for name in cube_names),
    }
    cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
    ground_heights = [
        round(segment_endpoint(cube_by_name[f"arm_{index}_3"])[1], 6)
        for index in range(1, 9)
    ]
    mouth_minimum, mouth_maximum = exported_cube_bounds(spec, cube_by_name["mouth_cavity"])
    mouth_size = [mouth_maximum[index] - mouth_minimum[index] for index in range(3)]
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v2",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "model_extents": [round(float(value), 6) for value in full_extents],
        "body_extents": [round(float(value), 6) for value in body_extents],
        "body_width_to_height": round(float(body_extents[0] / body_extents[1]), 6),
        "body_depth_to_width": round(float(body_extents[2] / body_extents[0]), 6),
        "body_to_full_height": round(float(body_extents[1] / full_extents[1]), 6),
        "arm_extents": [round(float(value), 6) for value in arm_extents],
        "arm_span_to_body_width": round(float(arm_extents[0] / body_extents[0]), 6),
        "arm_depth_to_body_depth": round(float(arm_extents[2] / body_extents[2]), 6),
        "feature_inventory": actual_inventory,
        "recorded_feature_inventory_matches": actual_inventory == recorded_inventory,
        "feature_contract_pass": (
            actual_inventory == recorded_inventory
            and actual_inventory["eye_assemblies"] == 10
            and actual_inventory["red_irises"] == 10
            and actual_inventory["pupil_landmarks"] == 10
            and actual_inventory["arm_chains"] == 8
            and actual_inventory["arm_segments"] == 24
            and actual_inventory["arm_palms"] == 8
            and actual_inventory["grounded_fingers"] == 32
            and actual_inventory["stem_leaves"] >= 6
            and actual_inventory["stem_leaf_segments"] == 12
            and actual_inventory["mouth_teeth"] >= 5
        ),
        "eye_layout": eye_layout_metrics(spec),
        "mouth": {
            "measured_size": [round(float(value), 6) for value in mouth_size],
            "orientation": "vertical" if mouth_size[1] > mouth_size[0] * 3 else "not-vertical",
            "length_to_body_height": round(mouth_size[1] / float(body_extents[1]), 6),
            "width_to_body_width": round(mouth_size[0] / float(body_extents[0]), 6),
        },
        "attachments": attachment,
        "ground_endpoint_band": [0.3, 0.5],
        "all_arm_wrists_grounded": all(0.3 <= value <= 0.5 for value in ground_heights),
        "arm_wrist_heights": ground_heights,
        "views": [
            "front.png", "back.png", "left.png", "right.png", "top.png",
            "isometric.png", "ten-eyes.png", "zipper-mouth.png",
            "arm-joints.png", "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
