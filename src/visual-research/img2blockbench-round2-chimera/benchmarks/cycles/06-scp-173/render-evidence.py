#!/usr/bin/env python3
"""Render and measure deterministic multi-view SCP-173 evidence."""

from __future__ import annotations

import json
import math
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
REFERENCE = ROOT / "benchmarks" / "references" / "06-scp-173.jpg"
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


def normalized_mask(mask: np.ndarray, size: tuple[int, int] = (320, 512)) -> np.ndarray:
    """Center a silhouette at common height without hiding aspect error."""
    rows, columns = np.where(mask)
    if not len(rows):
        raise ValueError("cannot normalize an empty silhouette")
    crop = mask[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]
    target_height = size[1] - 16
    scale = target_height / crop.shape[0]
    target_width = max(1, round(crop.shape[1] * scale))
    target_width = min(size[0], target_width)
    resized = Image.fromarray(crop.astype(np.uint8) * 255, mode="L").resize(
        (target_width, target_height), Image.Resampling.NEAREST
    )
    canvas = np.zeros((size[1], size[0]), dtype=bool)
    left = (size[0] - target_width) // 2
    canvas[8 : 8 + target_height, left : left + target_width] = (
        np.asarray(resized, dtype=np.uint8) >= 128
    )
    return canvas


def silhouette_metrics(reference: Image.Image, rendered: Image.Image) -> dict[str, Any]:
    """Compare the observed front silhouette after height-only normalization."""
    source_rgb = np.asarray(reference.convert("RGB"), dtype=np.int16)
    # The supplied product image has a nearly uniform #f8f8f8 surround.
    source = np.max(np.abs(source_rgb - np.asarray((248, 248, 248))), axis=2) >= 18
    model = np.asarray(foreground_mask(rendered), dtype=np.uint8) >= 128
    first = normalized_mask(source)
    second = normalized_mask(model)
    intersection = first & second
    union = first | second
    return {
        "method": "foreground-threshold-height-normalized-centered-iou-v1",
        "source_background_rgb": [248, 248, 248],
        "threshold": 18,
        "iou": round(float(intersection.sum() / max(1, union.sum())), 6),
        "recall": round(float(intersection.sum() / max(1, first.sum())), 6),
        "precision": round(float(intersection.sum() / max(1, second.sum())), 6),
        "limitation": "front silhouette only; it does not validate hidden profile or back geometry",
    }


def main() -> None:
    """Write review images and machine-checkable semantic metrics."""
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
        (-0.7, 0.035, 1.0),
        atlas_image=atlas,
        placements=placements,
    )
    views["reference_angle"].save(OUTPUT / "reference-angle.png", optimize=True)

    head_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith("head_volume_")
        or cube["bone"] == "face"
        or cube["name"] == "neck_core"
    }
    arm_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(("viewer_left_arm", "viewer_right_arm"))
    }
    torso_context = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith("torso_volume_")
    }
    details = {
        "face closeup": render_view(
            spec,
            (-0.08, 0.015, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=head_names,
        ),
        "left head closeup": render_view(
            spec,
            (0.75, 0.025, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=head_names,
        ),
        "right head closeup": render_view(
            spec,
            (-0.75, 0.025, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=head_names,
        ),
        "arm joints": render_view(
            spec,
            (-0.12, 0.04, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=arm_names | torso_context,
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

    names = [cube["name"] for cube in spec["cubes"]]
    head_set = {name for name in names if name.startswith("head_volume_")}
    torso_set = {name for name in names if name.startswith("torso_volume_")}
    leg_set = {name for name in names if name.startswith(("left_leg_", "right_leg_"))}
    all_lower, all_upper = bounds_for(spec)
    head_lower, head_upper = bounds_for(spec, head_set)
    torso_lower, torso_upper = bounds_for(spec, torso_set)
    leg_lower, leg_upper = bounds_for(spec, leg_set)
    extents = all_upper - all_lower
    head_extents = head_upper - head_lower
    torso_extents = torso_upper - torso_lower
    leg_extents = leg_upper - leg_lower
    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    recorded = spec["generation"]["feature_inventory"]
    actual = {
        "head_volumes": len(head_set),
        "torso_volumes": len(torso_set),
        "leg_segments": sum(name.startswith(("left_leg_", "right_leg_")) for name in names),
        "arm_segments": sum(
            name.startswith(("viewer_left_arm_", "viewer_right_arm_"))
            and not name.endswith(("_fist", "_knuckles"))
            for name in names
        ),
        "fist_volumes": sum(name.endswith(("_fist", "_knuckles")) for name in names),
        "procedural_face_decal_images": int(
            "source_texture" in spec["materials"]["face_decal"]
        ),
        "decal_mapped_front_faces": sum(
            cube.get("faces", {}).get("south", {}).get("material") == "face_decal"
            for cube in spec["cubes"]
        ),
        "geometric_face_pads": sum(cube["bone"] == "face" for cube in spec["cubes"]),
        "surface_cracks": sum(name.startswith("torso_crack_") for name in names),
    }
    decal = spec["generation"]["procedural_face_decal"]
    face_groups = dict(decal["features"])
    source_mask_metrics = silhouette_metrics(reference, views["reference_angle"])
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v2",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "model_extents": [round(float(value), 6) for value in extents],
        "proportion_metrics": {
            "overall_width_to_height": round(float(extents[0] / extents[1]), 6),
            "head_width_to_height": round(float(head_extents[0] / extents[1]), 6),
            "head_height_to_height": round(float(head_extents[1] / extents[1]), 6),
            "head_depth_to_width": round(float(head_extents[2] / head_extents[0]), 6),
            "torso_width_to_height": round(float(torso_extents[0] / extents[1]), 6),
            "torso_depth_to_width": round(float(torso_extents[2] / torso_extents[0]), 6),
            "leg_height_to_height": round(float(leg_extents[1] / extents[1]), 6),
            "ground_gap": round(max(0.0, float(all_lower[1])), 6),
        },
        "source_measurements": {
            "method": (
                "manual source-pixel bounding boxes divided by observed 872-pixel "
                "subject height"
            ),
            "subject_bbox_pixels": [252, 64, 496, 935],
            "overall_width_to_height": 0.28,
            "head_width_to_height": 0.202,
            "neck_width_to_height": 0.109,
            "body_width_to_height": 0.149,
            "leg_height_to_height": 0.24,
        },
        "front_silhouette": source_mask_metrics,
        "face_feature_groups": face_groups,
        "face_contract_pass": face_groups
        == {
            "red_forehead_flame": True,
            "central_black_slit": True,
            "upper_green_discs": 2,
            "lower_black_sockets": 2,
            "triangular_nose": True,
            "jagged_mouth_teeth": 4,
            "left_edge_red_smear": True,
        },
        "feature_inventory": actual,
        "recorded_feature_inventory_matches": actual == recorded,
        "attachments": attachment,
        "no_reference_image_projection": (
            spec["generation"]["source_projection"] is False
            and decal["source_reference_pixels"] is False
        ),
        "procedural_decal": {
            "image_count": actual["procedural_face_decal_images"],
            "mapped_front_faces": actual["decal_mapped_front_faces"],
            "geometric_protrusion": decal["geometric_protrusion"],
            "painted_surface": decal["painted_surface"],
        },
        "hidden_geometry_disclosure": spec["generation"]["single_view_hidden_geometry"],
        "views": [
            "reference-angle.png",
            "front.png",
            "back.png",
            "left.png",
            "right.png",
            "top.png",
            "isometric.png",
            "face-closeup.png",
            "left-head-closeup.png",
            "right-head-closeup.png",
            "arm-joints.png",
            "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
