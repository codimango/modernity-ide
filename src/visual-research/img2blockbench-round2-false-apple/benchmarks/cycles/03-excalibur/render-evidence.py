#!/usr/bin/env python3
"""Render and measure deterministic semantic Excalibur evidence."""

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
REFERENCE = ROOT / "benchmarks" / "references" / "03-excalibur.png"
SOURCE_MASK = CYCLE / "inputs" / "foreground-mask.png"
OUTPUT = CYCLE / "render"
BACKGROUND = (13, 20, 28)


def bounds_for(
    spec: dict[str, Any], names: set[str] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return exact rendered world bounds for all or selected cuboids."""
    vertices = np.concatenate(
        [
            cube_vertices(spec, cube)
            for cube in spec["cubes"]
            if names is None or cube["name"] in names
        ]
    )
    return vertices.min(axis=0), vertices.max(axis=0)


def rotate_reference_angle(image: Image.Image, degrees: float) -> Image.Image:
    """Roll the native +Y sword into the supplied presentation angle."""
    mask = foreground_mask(image)
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError("front render has no foreground")
    cropped = image.crop(bounds)
    padded = Image.new(
        "RGBA", (cropped.width + 64, cropped.height + 64), (*BACKGROUND, 255)
    )
    padded.alpha_composite(cropped, (32, 32))
    return padded.rotate(
        degrees,
        resample=Image.Resampling.NEAREST,
        expand=True,
        fillcolor=(*BACKGROUND, 255),
    )


def normalized_mask(mask: np.ndarray, size: int = 768) -> np.ndarray:
    """Fit one silhouette into a common centered canvas without distortion."""
    rows, columns = np.where(mask)
    if not len(rows):
        raise ValueError("cannot normalize an empty silhouette")
    crop = mask[rows.min() : rows.max() + 1, columns.min() : columns.max() + 1]
    target = size - 32
    scale = min(target / crop.shape[0], target / crop.shape[1])
    width = max(1, round(crop.shape[1] * scale))
    height = max(1, round(crop.shape[0] * scale))
    resized = Image.fromarray(crop.astype(np.uint8) * 255, mode="L").resize(
        (width, height), Image.Resampling.NEAREST
    )
    canvas = np.zeros((size, size), dtype=bool)
    left = (size - width) // 2
    top = (size - height) // 2
    canvas[top : top + height, left : left + width] = np.asarray(resized) >= 128
    return canvas


def principal_axis(mask: np.ndarray) -> float:
    """Return the undirected major-axis angle in degrees modulo 180."""
    rows, columns = np.where(mask)
    points = np.column_stack((columns, rows)).astype(np.float64)
    centered = points - points.mean(axis=0)
    values, vectors = np.linalg.eigh(np.cov(centered.T))
    vector = vectors[:, int(np.argmax(values))]
    return float(math.degrees(math.atan2(vector[1], vector[0])) % 180.0)


def silhouette_metrics(source: Image.Image, model: Image.Image) -> dict[str, Any]:
    """Compare the observed and reference-angle silhouettes at common scale."""
    source_array = np.asarray(source.convert("L"), dtype=np.uint8) >= 128
    model_array = np.asarray(foreground_mask(model), dtype=np.uint8) >= 128
    first = normalized_mask(source_array)
    second = normalized_mask(model_array)
    intersection = first & second
    union = first | second
    source_angle = principal_axis(source_array)
    model_angle = principal_axis(model_array)
    raw_delta = abs(source_angle - model_angle)
    angle_delta = min(raw_delta, 180.0 - raw_delta)
    return {
        "method": "reviewed-source-mask-reference-roll-centered-uniform-scale-iou-v1",
        "iou": round(float(intersection.sum() / max(1, union.sum())), 6),
        "recall": round(float(intersection.sum() / max(1, first.sum())), 6),
        "precision": round(float(intersection.sum() / max(1, second.sum())), 6),
        "source_major_axis_degrees_mod_180": round(source_angle, 6),
        "model_major_axis_degrees_mod_180": round(model_angle, 6),
        "major_axis_delta_degrees": round(angle_delta, 6),
        "limitation": (
            "The reviewed source silhouette is single-view evidence; centered normalization "
            "does not validate unseen profile decoration."
        ),
    }


def main() -> None:
    """Write complete multi-view evidence and semantic metrics."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    views: dict[str, Image.Image] = {}
    for name, direction in STANDARD_VIEWS.items():
        views[name] = render_view(
            spec, direction, atlas_image=atlas, placements=placements
        )
        views[name].save(OUTPUT / f"{name}.png", optimize=True)
    views["profile"] = render_view(
        spec, (1.0, 0.025, 0.0), atlas_image=atlas, placements=placements
    )
    views["profile"].save(OUTPUT / "profile.png", optimize=True)
    reference_angle = rotate_reference_angle(
        views["front"], float(spec["generation"]["reference_roll_degrees"])
    )
    reference_angle.save(OUTPUT / "reference-angle.png", optimize=True)

    hilt_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(("left_quillon", "right_quillon", "guard_", "grip_top"))
        or cube["name"] in {"blade_ricasso", "raised_front_crest", "front_crest_gem", "grip_core"}
    }
    emblem_names = {
        "blade_ricasso",
        "blade_rune_field",
        "raised_front_crest",
        "front_crest_gem",
        "guard_hub",
    }
    reverse_emblem_names = {
        "blade_ricasso",
        "blade_rune_field",
        "raised_back_crest",
        "guard_hub",
    }
    details = {
        "hilt junction": render_view(
            spec,
            (0.0, 0.03, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=hilt_names,
        ),
        "emblem and runes": render_view(
            spec,
            (0.0, 0.02, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=emblem_names,
        ),
        "reverse emblem": render_view(
            spec,
            (0.0, 0.02, -1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=reverse_emblem_names,
        ),
    }
    for name, image in details.items():
        image.save(OUTPUT / f"{name.replace(' ', '-')}.png", optimize=True)

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    with Image.open(SOURCE_MASK) as opened:
        source_mask = opened.convert("L")
    contact_sheet(
        reference,
        {
            "reference angle": reference_angle,
            "front": views["front"],
            "back": views["back"],
            "profile": views["profile"],
            "top": views["top"],
            "isometric": views["isometric"],
            **details,
        },
    ).save(OUTPUT / "comparison-sheet.png", optimize=True)

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment = audit_attachments(spec, links)
    all_lower, all_upper = bounds_for(spec)
    main_blade_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith("blade_")
    }
    blade_lower, blade_upper = bounds_for(spec, main_blade_names)
    guard_names = {
        cube["name"]
        for cube in spec["cubes"]
        if cube["name"].startswith(("left_quillon_", "right_quillon_", "guard_hub"))
        and "inlay" not in cube["name"]
        and cube["name"] != "guard_hub_gem"
    }
    guard_lower, guard_upper = bounds_for(spec, guard_names)
    all_extents = all_upper - all_lower
    blade_extents = blade_upper - blade_lower
    guard_extents = guard_upper - guard_lower

    names = [cube["name"] for cube in spec["cubes"]]
    actual_inventory = {
        "blade_main_volumes": sum(name.startswith("blade_") and "tip_" not in name for name in names),
        "tip_volumes": sum(name.startswith("blade_tip_") for name in names),
        "crest_surfaces": sum("crest" in name and name != "front_crest_gem" for name in names),
        "physical_crest_gems": sum(name in {"front_crest_gem", "guard_hub_gem", "pommel_gem"} for name in names),
        "main_quillon_segments": sum(name.startswith(("left_quillon_", "right_quillon_")) and "inlay" not in name for name in names),
        "quillon_inlay_segments": sum("quillon_inlay" in name for name in names),
        "grip_volumes": sum(name.startswith("grip_") for name in names),
        "pommel_volumes": sum(name.startswith("pommel_") for name in names),
        "authored_texture_images": sum("source_texture" in material for material in spec["materials"].values()),
        "source_projected_faces": sum(
            "source_region" in override
            for cube in spec["cubes"]
            for override in cube.get("faces", {}).values()
        ),
    }
    attached_names = {name for first, second, _ in links for name in (first, second)}
    silhouette = silhouette_metrics(source_mask, reference_angle)
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v2",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "model_extents": [round(float(value), 6) for value in all_extents],
        "blade_extents": [round(float(value), 6) for value in blade_extents],
        "guard_extents": [round(float(value), 6) for value in guard_extents],
        "proportion_metrics": {
            "overall_span_to_length": round(float(all_extents[0] / all_extents[1]), 6),
            "guard_span_to_length": round(float(guard_extents[0] / all_extents[1]), 6),
            "blade_base_width_to_length": round(4.8 / float(all_extents[1]), 6),
            "blade_profile_depth_to_length": round(float(blade_extents[2] / all_extents[1]), 6),
            "grip_length_to_full_length": round(11.8 / float(all_extents[1]), 6),
        },
        "source_silhouette": silhouette,
        "attachments": attachment,
        "attachment_graph": {
            "declared_links": len(links),
            "covered_cuboids": len(attached_names),
            "all_cuboids_covered": attached_names == set(names),
        },
        "feature_inventory": actual_inventory,
        "recorded_feature_inventory_matches": actual_inventory
        == spec["generation"]["feature_inventory"],
        "texture_contract": {
            "front_rune_glyphs": spec["generation"]["procedural_textures"]["front_rune_glyphs"],
            "reverse_rune_glyphs": spec["generation"]["procedural_textures"]["reverse_rune_glyphs"],
            "front_crest": spec["generation"]["procedural_textures"]["front_crest"],
            "reverse_crest": spec["generation"]["procedural_textures"]["reverse_crest"],
            "two_sided_grip_wrap": spec["generation"]["procedural_textures"]["two_sided_grip_wrap"],
            "source_reference_pixels": spec["generation"]["procedural_textures"]["source_reference_pixels"],
        },
        "no_reference_image_projection": (
            spec["generation"]["source_projection"] is False
            and actual_inventory["source_projected_faces"] == 0
            and spec["generation"]["source_skin_cuboids"] == 0
        ),
        "hidden_geometry_disclosure": spec["generation"]["single_view_hidden_geometry"],
        "views": [
            "reference-angle.png",
            "front.png",
            "back.png",
            "profile.png",
            "top.png",
            "isometric.png",
            "hilt-junction.png",
            "emblem-and-runes.png",
            "reverse-emblem.png",
            "comparison-sheet.png",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
