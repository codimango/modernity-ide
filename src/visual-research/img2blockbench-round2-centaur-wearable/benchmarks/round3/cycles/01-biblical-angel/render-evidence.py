#!/usr/bin/env python3
"""Render and measure holistic multi-angle evidence for the Round 3 angel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

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
REFERENCE = ROOT / "round3-inputs" / "biblically-accurate-angel.png"
SPEC_PATH = CYCLE / "model-spec.json"
OUTPUT = CYCLE / "render"
LOCAL_REVIEW_OUTPUT = (
    ROOT / "round3-inputs" / "local-review" / "01-biblical-angel"
)
BACKGROUND = (232, 235, 238, 255)
HOLISTIC_VIEWS = {
    **STANDARD_VIEWS,
    "bottom": (0.001, -1.0, 0.0),
}


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


def mask_stats(image: Image.Image) -> dict[str, Any]:
    """Measure non-background area and bounding box in one fixed render."""
    mask = np.asarray(foreground_mask(image, BACKGROUND[:3]), dtype=np.uint8) >= 128
    rows, columns = np.where(mask)
    if not len(rows):
        raise ValueError("render contains no foreground")
    width = int(columns.max() - columns.min() + 1)
    height = int(rows.max() - rows.min() + 1)
    return {
        "foreground_pixels": int(mask.sum()),
        "bbox": [
            int(columns.min()), int(rows.min()),
            int(columns.max()) + 1, int(rows.max()) + 1,
        ],
        "bbox_width": width,
        "bbox_height": height,
        "bbox_aspect": round(width / height, 6),
        "mask_sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
    }


def model_only_sheet(
    renders: dict[str, Image.Image],
    *,
    columns: int = 4,
    tile: tuple[int, int] = (330, 300),
) -> Image.Image:
    """Compose a commit-safe review sheet containing model renders only."""
    header = 36
    rows = (len(renders) + columns - 1) // columns
    sheet = Image.new("RGB", (tile[0] * columns, (tile[1] + header) * rows), "#09111a")
    draw = ImageDraw.Draw(sheet)
    for index, (name, source) in enumerate(renders.items()):
        x = index % columns * tile[0]
        y = index // columns * (tile[1] + header)
        fitted = source.copy()
        fitted.thumbnail(tile, Image.Resampling.LANCZOS)
        panel = Image.new("RGBA", tile, "#0d141c")
        panel.alpha_composite(
            fitted,
            ((tile[0] - fitted.width) // 2, (tile[1] - fitted.height) // 2),
        )
        sheet.paste(panel.convert("RGB"), (x, y + header))
        draw.text((x + 10, y + 10), name.upper().replace("_", " "), fill="#f0bd31")
    return sheet


def main() -> None:
    """Write fixed views, close-ups, and anti-pancake regression metrics."""
    spec = read_json(SPEC_PATH)
    atlas, placements = build_texture(spec)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    views: dict[str, Image.Image] = {}
    for name, direction in HOLISTIC_VIEWS.items():
        view = render_view(
            spec,
            direction,
            atlas_image=atlas,
            placements=placements,
            background=BACKGROUND,
            size=(720, 720),
        )
        view.save(OUTPUT / f"{name}.png", optimize=True)
        views[name] = view

    cube_names = {cube["name"] for cube in spec["cubes"]}
    front_eye_names = {
        name for name in cube_names
        if name.startswith("front_eye_")
        or name in {
            "front_eye_band", "front_left_crown_wrap", "front_right_crown_wrap",
            "left_side_temple", "right_side_temple", "body_core", "body_upper_crown",
        }
    }
    rear_eye_names = {
        name for name in cube_names
        if name.startswith("back_eye_")
        or name in {
            "back_eye_band", "rear_left_crown_wrap", "rear_right_crown_wrap",
            "left_side_temple", "right_side_temple", "body_core", "body_upper_crown",
        }
    }
    left_wing_names = {
        name for name in cube_names
        if name.startswith("left_") and any(
            token in name for token in ("spar", "feather", "wing_eye", "overlap_vane")
        )
    } | {"body_core", "front_eye_band", "back_eye_band"}
    wing_tip_names = {
        name for name in cube_names
        if name.startswith((
            "left_rear_upper_spar_1", "left_rear_upper_spar_2",
            "left_rear_upper_feather_1_", "left_rear_upper_overlap_vane_1_",
        ))
    }
    crown_wrap_names = set(spec["generation"]["eye_crown"]["segments"])
    crown_wrap_names.update(
        cube_name
        for eye in spec["generation"]["eyes"]
        for cube_name in eye["cubes"]
        if not eye["name"].startswith(("left_", "right_")) or "temple" in eye["name"]
    )
    detail_views = {
        "eye-crown-closeup": render_view(
            spec,
            (0.25, 0.12, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=front_eye_names,
            background=BACKGROUND,
            size=(720, 560),
        ),
        "rear-eyes-closeup": render_view(
            spec,
            (-0.22, 0.10, -1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=rear_eye_names,
            background=BACKGROUND,
            size=(720, 560),
        ),
        "wing-layers-closeup": render_view(
            spec,
            (0.85, 0.35, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=left_wing_names,
            background=BACKGROUND,
            size=(720, 620),
        ),
        "side-depth-closeup": render_view(
            spec,
            (1.0, 0.12, 0.12),
            atlas_image=atlas,
            placements=placements,
            background=BACKGROUND,
            size=(720, 720),
        ),
        "wing-tip-closeup": render_view(
            spec,
            (0.45, 0.20, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=wing_tip_names,
            background=BACKGROUND,
            size=(720, 620),
        ),
        "crown-wrap-closeup": render_view(
            spec,
            (1.0, 0.24, 1.0),
            atlas_image=atlas,
            placements=placements,
            selected_names=crown_wrap_names,
            background=BACKGROUND,
            size=(720, 620),
        ),
    }
    for name, image in detail_views.items():
        image.save(OUTPUT / f"{name}.png", optimize=True)

    model_render_images = {
        "front": views["front"],
        "back": views["back"],
        "left": views["left"],
        "right": views["right"],
        "top": views["top"],
        "bottom": views["bottom"],
        "isometric": views["isometric"],
        **detail_views,
    }
    model_only_sheet(model_render_images).save(
        OUTPUT / "all-angle-sheet.png", optimize=True
    )

    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGBA")
    flattened = Image.new("RGBA", reference.size, BACKGROUND)
    flattened.alpha_composite(reference)
    LOCAL_REVIEW_OUTPUT.mkdir(parents=True, exist_ok=True)
    contact_sheet(
        flattened,
        {
            "front": views["front"],
            "back": views["back"],
            "left": views["left"],
            "right": views["right"],
            "top": views["top"],
            "bottom": views["bottom"],
            "isometric": views["isometric"],
            **detail_views,
        },
        columns=4,
        tile=(330, 300),
    ).save(LOCAL_REVIEW_OUTPUT / "angel.source-comparison.png", optimize=True)

    required_render_files = [
        *[f"{name}.png" for name in HOLISTIC_VIEWS],
        *[f"{name}.png" for name in detail_views],
        "all-angle-sheet.png",
    ]

    all_lower, all_upper = bounds_for(spec)
    all_extents = all_upper - all_lower
    body_names = {
        "body_core", "body_upper_crown", "body_lower_shroud", "front_eye_band",
        "back_eye_band", "left_side_temple", "right_side_temple", "top_eye_plinth",
        "front_body_shell", "back_body_shell", "left_body_shell", "right_body_shell",
        "front_left_crown_wrap", "front_right_crown_wrap",
        "rear_left_crown_wrap", "rear_right_crown_wrap",
    }
    body_lower, body_upper = bounds_for(spec, body_names)
    body_extents = body_upper - body_lower
    wing_records = spec["generation"]["wing_records"]
    wing_depths = sorted({float(record["depth_center"]) for record in wing_records})
    view_metrics = {name: mask_stats(view) for name, view in views.items()}
    front_pixels = view_metrics["front"]["foreground_pixels"]
    side_ratios = {
        side: round(view_metrics[side]["foreground_pixels"] / front_pixels, 6)
        for side in ("left", "right")
    }
    side_width_ratios = {
        side: round(view_metrics[side]["bbox_width"] / view_metrics["front"]["bbox_width"], 6)
        for side in ("left", "right")
    }
    axis_area_ratios = {
        name: round(view_metrics[name]["foreground_pixels"] / front_pixels, 6)
        for name in ("back", "left", "right", "top", "bottom", "isometric")
    }
    image_hashes = {
        filename: hashlib.sha256((OUTPUT / filename).read_bytes()).hexdigest()
        for filename in required_render_files
    }
    (OUTPUT / "render-hashes.json").write_text(
        json.dumps(
            {
                "algorithm": "sha256",
                "model_only": True,
                "required_renders": image_hashes,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    cube_centers_z = [float(cube["center"][2]) for cube in spec["cubes"]]
    depth_occupancy = {
        "front_band_cuboids_z_at_least_5": sum(value >= 5.0 for value in cube_centers_z),
        "middle_band_cuboids_abs_z_below_5": sum(abs(value) < 5.0 for value in cube_centers_z),
        "rear_band_cuboids_z_at_most_minus_5": sum(value <= -5.0 for value in cube_centers_z),
    }
    eye_orientations: dict[str, int] = {}
    for record in spec["generation"]["eyes"]:
        orientation = str(record["orientation"])
        eye_orientations[orientation] = eye_orientations.get(orientation, 0) + 1

    wing_shape_cubes = [
        cube for cube in spec["cubes"]
        if any(token in cube["name"] for token in ("spar", "feather", "overlap_vane"))
    ]
    yawed_wing_cubes = [
        cube for cube in wing_shape_cubes if abs(float(cube["rotation"][1])) >= 1.0
    ]
    feather_profiles = [
        profile for record in wing_records for profile in record["feather_profiles"]
    ]
    vane_profiles = [
        profile for record in wing_records for profile in record["overlap_vane_profiles"]
    ]
    taper_profiles = feather_profiles + vane_profiles
    taper_metrics = {
        "primary_profile_count": len(feather_profiles),
        "overlap_vane_profile_count": len(vane_profiles),
        "all_profiles_have_three_segments": all(
            len(profile["segments"]) == 3 for profile in taper_profiles
        ),
        "all_widths_strictly_decrease": all(
            profile["widths"][0] > profile["widths"][1] > profile["widths"][2]
            for profile in taper_profiles
        ),
        "all_depths_strictly_decrease": all(
            profile["depths"][0] > profile["depths"][1] > profile["depths"][2]
            for profile in taper_profiles
        ),
        "maximum_terminal_width": max(profile["widths"][-1] for profile in taper_profiles),
        "maximum_terminal_depth": max(profile["depths"][-1] for profile in taper_profiles),
        "distinct_terminal_lengths": len(
            {round(float(profile["terminal_length"]), 3) for profile in taper_profiles}
        ),
        "minimum_terminal_length": min(
            float(profile["terminal_length"]) for profile in taper_profiles
        ),
        "maximum_terminal_length": max(
            float(profile["terminal_length"]) for profile in taper_profiles
        ),
    }
    sector_sweeps = {
        layer: sorted(
            {
                float(record["sector_sweep_degrees"])
                for record in wing_records if record["layer"] == layer
            }
        )
        for layer in ("rear_upper", "middle", "front_lower")
    }
    crown_names = set(spec["generation"]["eye_crown"]["segments"])
    cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
    crown_metrics = {
        "segment_count": len(crown_names),
        "all_segments_exist": crown_names <= set(cube_by_name),
        "angled_corner_segments": sum(
            abs(float(cube_by_name[name]["rotation"][1])) >= 35.0
            for name in crown_names if "crown_wrap" in name
        ),
        "includes_both_side_temples": {
            "left_side_temple", "right_side_temple"
        } <= crown_names,
    }

    links = [
        (record["first"], record["second"], record["joint"])
        for record in spec["generation"]["declared_attachments"]
    ]
    attachment_audit = audit_attachments(spec, links)
    proportions = {
        "full_extents_xyz": [round(float(value), 6) for value in all_extents],
        "depth_to_width": round(float(all_extents[2] / all_extents[0]), 6),
        "body_extents_xyz": [round(float(value), 6) for value in body_extents],
        "body_depth_to_width": round(float(body_extents[2] / body_extents[0]), 6),
        "wing_depth_centers": wing_depths,
        "wing_depth_span": round(max(wing_depths) - min(wing_depths), 6),
        "side_to_front_silhouette_area": side_ratios,
        "side_to_front_bbox_width": side_width_ratios,
        "axis_to_front_silhouette_area": axis_area_ratios,
        "front_bbox_aspect": view_metrics["front"]["bbox_aspect"],
        "side_bbox_aspects": {
            side: view_metrics[side]["bbox_aspect"] for side in ("left", "right")
        },
    }
    contract = spec["generation"]["holistic_3d_contract"]
    gates = {
        "full_depth_to_width_at_least_contract": (
            proportions["depth_to_width"] >= contract["minimum_required_depth_to_width"]
        ),
        "body_depth_to_width_at_least_contract": (
            proportions["body_depth_to_width"]
            >= contract["minimum_required_body_depth_to_width"]
        ),
        "three_wing_depth_bands_span_at_least_30": (
            len(wing_depths) == 3 and proportions["wing_depth_span"] >= 30.0
        ),
        "both_side_silhouettes_have_minimum_area": all(
            ratio >= contract["minimum_required_side_to_front_silhouette_area"]
            for ratio in side_ratios.values()
        ),
        "both_side_bbox_widths_meet_contract": all(
            ratio >= contract["minimum_required_side_to_front_bbox_width"]
            for ratio in side_width_ratios.values()
        ),
        "front_middle_rear_depth_bands_are_populated": all(
            count >= 20 for count in depth_occupancy.values()
        ),
        "front_back_side_top_eye_surfaces_exist": all(
            eye_orientations.get(face, 0) >= minimum
            for face, minimum in {
                "south": 7, "north": 5, "west": 1, "east": 1, "up": 1,
            }.items()
        ),
        "back_top_and_bottom_silhouettes_are_substantive": (
            axis_area_ratios["back"]
            >= contract["minimum_required_back_to_front_silhouette_area"]
            and axis_area_ratios["top"]
            >= contract["minimum_required_top_to_front_silhouette_area"]
            and axis_area_ratios["bottom"]
            >= contract["minimum_required_bottom_to_front_silhouette_area"]
        ),
        "all_wing_shape_cubes_have_nonzero_yaw": (
            len(wing_shape_cubes) > 0 and len(yawed_wing_cubes) == len(wing_shape_cubes)
        ),
        "wing_sector_angles_match_rear_middle_front_contract": (
            all(35.0 <= value <= 55.0 for value in sector_sweeps["rear_upper"])
            and all(15.0 <= value <= 30.0 for value in sector_sweeps["middle"])
            and all(35.0 <= value <= 55.0 for value in sector_sweeps["front_lower"])
        ),
        "every_primary_and_vane_has_three_step_taper": (
            taper_metrics["primary_profile_count"] == 18
            and taper_metrics["overlap_vane_profile_count"] == 12
            and taper_metrics["all_profiles_have_three_segments"]
            and taper_metrics["all_widths_strictly_decrease"]
            and taper_metrics["all_depths_strictly_decrease"]
            and taper_metrics["maximum_terminal_width"] <= 1.4
            and taper_metrics["maximum_terminal_depth"] <= 1.0
            and taper_metrics["distinct_terminal_lengths"] >= 6
        ),
        "eye_crown_wraps_through_four_angled_corners_and_both_sides": (
            crown_metrics["segment_count"] == 8
            and crown_metrics["all_segments_exist"]
            and crown_metrics["angled_corner_segments"] == 4
            and crown_metrics["includes_both_side_temples"]
        ),
        "all_required_model_only_renders_are_pixel_distinct": (
            len(set(image_hashes.values())) == len(required_render_files)
        ),
        "side_aspect_differs_materially_from_front": all(
            abs(view_metrics["front"]["bbox_aspect"] - view_metrics[side]["bbox_aspect"])
            >= 0.35
            for side in ("left", "right")
        ),
        "attachment_tree_is_connected": (
            len(links) == len(spec["cubes"]) - 1 and attachment_audit["all_connected"]
        ),
        "all_materials_are_noise_free": all(
            material["pattern"] == "solid" for material in spec["materials"].values()
        ),
    }
    evaluation = {
        "schema_version": 1,
        "renderer": "deterministic-orthographic-textured-cuboid-zbuffer-v2",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "bones": len(spec["bones"]),
        "semantic_cuboids": len(spec["cubes"]),
        "source_skin_cuboids": 0,
        "source_projection": False,
        "reference_rights": "unknown; private ignored benchmark reference only",
        "single_view_hidden_geometry": spec["generation"]["single_view_hidden_geometry"],
        "source_scoring": {
            "silhouette_iou_omitted": True,
            "reason": (
                "The source merges white anatomy into cloud and bloom; any automated foreground "
                "mask would score background effects as body geometry. Multi-angle structure is "
                "therefore gated directly instead of reporting a misleading fitted IoU."
            ),
        },
        "feature_inventory": spec["generation"]["feature_inventory"],
        "eye_orientations": eye_orientations,
        "depth_occupancy": depth_occupancy,
        "wing_yaw": {
            "wing_shape_cuboids": len(wing_shape_cubes),
            "nonzero_yaw_cuboids": len(yawed_wing_cubes),
            "nonzero_yaw_fraction": round(
                len(yawed_wing_cubes) / max(1, len(wing_shape_cubes)), 6
            ),
            "sector_sweeps_degrees": sector_sweeps,
        },
        "distal_taper": taper_metrics,
        "eye_crown": crown_metrics,
        "proportions": proportions,
        "view_metrics": view_metrics,
        "render_sha256": image_hashes,
        "view_diversity_gates": gates,
        "all_view_diversity_gates_pass": all(gates.values()),
        "attachments": attachment_audit,
        "declared_link_tree_covers_every_cube": (
            len(links) == len(spec["cubes"]) - 1
            and {name for first, second, _ in links for name in (first, second)}
            == {cube["name"] for cube in spec["cubes"]}
        ),
        "views": required_render_files,
        "render_hash_manifest": "render-hashes.json",
        "local_source_comparison": (
            "round3-inputs/local-review/01-biblical-angel/"
            "angel.source-comparison.png"
        ),
        "local_source_comparison_is_ignored": True,
        "limitations": [
            "The supplied reference contains only one frontal view and no mesh; rear and side "
            "topology is agent-authored inference, not source-observed geometry.",
            "Painterly bloom, clouds, and micro-veins are reduced to a crisp bounded Minecraft "
            "palette rather than copied as noisy photographic texture.",
            "The rigid feather rig prioritizes a strong all-angle static silhouette; animation "
            "quality requires a separate playback review.",
        ],
    }
    (OUTPUT / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (CYCLE / "results.json").write_text(
        json.dumps(
            {
                "cycle": "round3-01",
                "asset": "biblical_angel_many_eyed_six_wing",
                "status": (
                    "ready_for_independent_review"
                    if evaluation["all_view_diversity_gates_pass"]
                    else "failed_author_gates"
                ),
                "metrics": {
                    "cuboids": len(spec["cubes"]),
                    "geometric_eyes": spec["generation"]["feature_inventory"][
                        "total_geometric_eyes"
                    ],
                    "bilateral_wings": spec["generation"]["feature_inventory"][
                        "bilateral_wings"
                    ],
                    "primary_feathers": spec["generation"]["feature_inventory"][
                        "primary_feathers"
                    ],
                    "broad_overlap_vanes": spec["generation"]["feature_inventory"][
                        "broad_overlap_vanes"
                    ],
                    "depth_to_width": proportions["depth_to_width"],
                    "body_depth_to_width": proportions["body_depth_to_width"],
                    "wing_depth_span": proportions["wing_depth_span"],
                    "minimum_side_to_front_area": min(side_ratios.values()),
                    "top_to_front_area": axis_area_ratios["top"],
                    "bottom_to_front_area": axis_area_ratios["bottom"],
                    "back_to_front_area": axis_area_ratios["back"],
                    "wing_nonzero_yaw_fraction": round(
                        len(yawed_wing_cubes) / max(1, len(wing_shape_cubes)), 6
                    ),
                    "three_stage_taper_profiles": len(taper_profiles),
                    "wrapped_eye_crown_segments": crown_metrics["segment_count"],
                },
                "all_view_diversity_gates_pass": evaluation[
                    "all_view_diversity_gates_pass"
                ],
                "visual_review_required": True,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
