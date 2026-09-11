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
        self.assertEqual("duplicate-aware-fused-zombie-anatomy-v2", generation["algorithm"])
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

    def test_primary_view_texture_transfer_does_not_double_count_duplicate(self) -> None:
        """Gate direct source pixels while preserving the one-camera-axis claim."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        transfer = spec["generation"]["texture_transfer"]
        evidence = json.loads(
            (CYCLE / "texture-evidence.json").read_text(encoding="utf-8")
        )

        self.assertEqual(evidence, transfer)
        self.assertEqual(
            "calibrated-perspective-visible-face-texture-bake-v1",
            transfer["algorithm"],
        )
        self.assertFalse(transfer["palette_quantization"])
        self.assertFalse(spec["texture"]["quantize_source"])
        self.assertEqual(4, transfer["texture"]["density"])
        self.assertEqual(2048, transfer["texture"]["resolved_atlas_size"])
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
        self.assertGreaterEqual(transfer["coverage"]["source_fraction"], 0.08)
        self.assertGreaterEqual(transfer["coverage"]["faces_with_source"], 240)
        self.assertEqual(1128, transfer["coverage"]["total_faces"])
        self.assertIn("solid effective material base", transfer["unobserved_policy"])
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
