"""Regression gates for the Round 2 Zombie Devil benchmark."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "08-zombie-devil"


def _rgb(color: str) -> tuple[int, int, int]:
    """Decode one model-spec color."""
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))


def _channel_spread(color: str) -> int:
    """Return the largest RGB-channel difference in one color."""
    channels = _rgb(color)
    return max(channels) - min(channels)


class RoundTwoZombieDevilTests(unittest.TestCase):
    """Require a duplicate-aware grotesque torso rather than a generic biped."""

    def test_duplicate_sources_count_as_one_observed_axis(self) -> None:
        """Gate exact provenance and prevent duplicate crops from claiming depth."""
        contract = json.loads(
            (CYCLE / "inputs" / "input-contract.json").read_text(encoding="utf-8")
        )
        self.assertEqual(2, len(contract["sources"]))
        self.assertEqual(1, contract["observed_camera_axes"])
        self.assertFalse(contract["hidden_geometry_established_from_observed_views"])
        similarity = contract["view_content_similarity"]
        self.assertTrue(similarity["near_duplicate"])
        self.assertGreaterEqual(similarity["rgb_correlation"], 0.995)
        self.assertLessEqual(similarity["normalized_mean_absolute_error"], 0.04)
        for source in contract["sources"]:
            local = ROOT / Path(source["image"]).name
            if local.is_file():
                self.assertEqual(
                    source["sha256"], hashlib.sha256(local.read_bytes()).hexdigest()
                )

    def test_zombie_devil_is_deep_native_and_not_a_biped(self) -> None:
        """Gate identity anatomy, true mouth carving, and the exact contact tree."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        generation = spec["generation"]
        inventory = generation["feature_inventory"]
        names = {cube["name"] for cube in spec["cubes"]}

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("zombie_devil_exposed_brain", spec["id"])
        self.assertEqual("agent-authored-semantic-volume", generation["lane"])
        self.assertEqual(188, len(spec["cubes"]))
        self.assertEqual(0, generation["source_skin_cuboids"])
        self.assertFalse(generation["source_projection"])
        self.assertEqual(2, inventory["massive_arm_chains"])
        self.assertEqual(1, inventory["exposed_brains"])
        self.assertEqual(10, inventory["brain_grooves"])
        self.assertEqual(1, inventory["carved_screaming_mouths"])
        self.assertEqual(6, inventory["mouth_teeth"])
        self.assertEqual(4, inventory["hanging_organ_lobes"])
        self.assertEqual(3, inventory["visceral_tendrils"])
        self.assertEqual(0, inventory["grounded_feet"])
        self.assertFalse(any(name.endswith("_foot") for name in names))
        self.assertGreater(generation["head_cutout"]["removed_voxels"], 0)
        self.assertTrue(generation["head_cutout"]["carved_faces"])
        self.assertEqual("duplicate-aware-fused-zombie-anatomy-v3", generation["algorithm"])
        self.assertEqual(
            "front-surface-preserving-rear-extrusion-v1",
            generation["rear_depth_policy"]["method"],
        )
        self.assertTrue(
            generation["rear_depth_policy"]["observed_positive_z_surfaces_preserved"]
        )
        self.assertTrue(generation["rear_depth_policy"]["rear_depth_is_inferred"])
        self.assertEqual(-65.0, generation["source_frame_crop_world_y"])
        self.assertTrue(any(name.startswith("organ_bulge_") for name in names))

        links = [
            (entry["first"], entry["second"], entry["joint"])
            for entry in generation["declared_attachments"]
        ]
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertEqual(len(spec["cubes"]) - 1, len(links))
        self.assertTrue(report["all_connected"])
        self.assertGreaterEqual(report["minimum_margin"], 0)

    def test_primary_view_texture_transfer_is_stylized_without_duplicate(self) -> None:
        """Gate source-guided pixel art while preserving the one-camera-axis claim."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        transfer = spec["generation"]["texture_transfer"]
        evidence = json.loads(
            (CYCLE / "texture-evidence.json").read_text(encoding="utf-8")
        )

        self.assertEqual(evidence, transfer)
        self.assertEqual(
            "calibrated-perspective-visible-face-texture-bake-v2",
            transfer["algorithm"],
        )
        self.assertTrue(transfer["palette_quantization"])
        self.assertEqual("minecraft", transfer["style"]["name"])
        self.assertEqual(2, transfer["style"]["colors_per_material"])
        self.assertFalse(transfer["style"]["dithering"])
        self.assertLessEqual(len(transfer["style"]["actual_palette"]), 16)
        self.assertFalse(spec["texture"]["quantize_source"])
        self.assertEqual(1, transfer["texture"]["density"])
        self.assertEqual(1024, transfer["texture"]["resolved_atlas_size"])
        self.assertEqual(["primary-front"], [view["id"] for view in transfer["views"]])
        self.assertEqual(
            "e3c594bc2fc60a63fa7f510fd6557e761219b731be2654a599fc751d024c96df",
            transfer["views"][0]["image_sha256"],
        )
        manifest = json.loads(
            (CYCLE / "texture-views.json").read_text(encoding="utf-8")
        )
        evaluation = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertEqual(evaluation["source_camera"], manifest["views"][0]["camera"])
        self.assertGreaterEqual(transfer["coverage"]["source_fraction"], 0.06)
        self.assertGreaterEqual(transfer["coverage"]["source_texels"], 8000)
        self.assertGreaterEqual(transfer["coverage"]["faces_with_source"], 230)
        self.assertEqual(1128, transfer["coverage"]["total_faces"])
        self.assertIn("solid authored material base", transfer["unobserved_policy"])
        palette_contract = spec["generation"]["palette_contract"]
        self.assertEqual("user-selected-stylized-color", palette_contract["name"])
        self.assertTrue(palette_contract["source_is_grayscale"])
        self.assertTrue(palette_contract["source_projection_remains_grayscale"])
        self.assertTrue(palette_contract["colorization_is_authored_fallback"])
        self.assertTrue(palette_contract["warm_flesh_brain_and_viscera_palette"])
        self.assertEqual(
            {
                "flesh": "#d2cec3",
                "wound": "#762a34",
                "brain": "#b97f86",
                "organ_dark": "#8d6567",
                "intestine": "#a87b77",
            },
            {
                name: spec["materials"][name]["base"]
                for name in ("flesh", "wound", "brain", "organ_dark", "intestine")
            },
        )
        self.assertTrue(
            all(
                _channel_spread(color) <= 1
                for color in transfer["style"]["actual_palette"]
            )
        )
        atlas, _ = img2blockbench.build_texture(spec)
        atlas_colors = atlas.getcolors(maxcolors=atlas.width * atlas.height)
        self.assertIsNotNone(atlas_colors)
        opaque_counts = [entry for entry in atlas_colors or [] if entry[1][3] > 0]
        self.assertTrue(opaque_counts)
        opaque_texels = sum(count for count, _ in opaque_counts)
        chromatic_texels = sum(
            count
            for count, color in opaque_counts
            if max(color[:3]) - min(color[:3]) > 8
        )
        self.assertGreaterEqual(chromatic_texels / opaque_texels, 0.40)
        luminance_bins = {
            round(sum(color[:3]) / 3) // 16 for _, color in opaque_counts
        }
        self.assertGreaterEqual(len(luminance_bins), 8)
        for cube in spec["cubes"]:
            self.assertEqual(set(img2blockbench.FACES), set(cube["faces"]))
            self.assertTrue(
                all(
                    "source_texture" in cube["faces"][face]
                    for face in img2blockbench.FACES
                )
            )

    def test_zombie_devil_evidence_and_build_are_reproducible(self) -> None:
        """Gate source match, local depth, views, and deterministic compilation."""
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["source_iou_gate_at_least_0.55"])
        self.assertGreaterEqual(report["alpha_silhouette"]["iou"], 0.55)
        self.assertTrue(report["keypoint_mean_gate_at_most_0.08_subject_heights"])
        self.assertLessEqual(
            report["alpha_silhouette"]["keypoints"]["mean_error_subject_heights"],
            0.08,
        )
        self.assertEqual(1, report["observed_camera_axes"])
        self.assertFalse(report["hidden_geometry_established_from_observed_views"])
        self.assertTrue(report["reference_frame_clipping"]["measured_bottom"])
        self.assertTrue(
            report["reference_frame_clipping"][
                "off_frame_continuation_is_not_reconstructed_as_feet"
            ]
        )
        self.assertTrue(
            report["reference_frame_clipping"][
                "both_trailing_continuations_clipped_by_fixed_camera"
            ]
        )
        self.assertTrue(report["source_camera_has_no_auto_fit_or_recentering"])
        self.assertGreaterEqual(report["raw_fixed_camera_silhouette"]["iou"], 0.55)
        self.assertTrue(report["all_depth_gates_pass"])
        self.assertGreaterEqual(report["proportions"]["torso_depth_to_width"], 0.70)
        self.assertGreaterEqual(report["proportions"]["head_depth_to_width"], 0.80)
        self.assertGreaterEqual(report["proportions"]["brain_depth_to_width"], 1.10)
        self.assertGreaterEqual(report["proportions"]["arms_depth_to_width"], 0.33)
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertTrue(report["declared_link_tree_covers_every_cube"])
        for relative in report["views"]:
            self.assertTrue((CYCLE / "render" / relative).is_file(), relative)

        audit = json.loads(
            (CYCLE / "build" / "zombie_devil_exposed_brain.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        if (ROOT / "image-11.png").is_file():
            with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
                first = img2blockbench.build_model(CYCLE / "model-spec.json", Path(first_temp))
                second = img2blockbench.build_model(CYCLE / "model-spec.json", Path(second_temp))
                self.assertTrue(first["audit"]["ok"])
                self.assertEqual(
                    (Path(first_temp) / "zombie_devil_exposed_brain.bbmodel").read_bytes(),
                    (Path(second_temp) / "zombie_devil_exposed_brain.bbmodel").read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
