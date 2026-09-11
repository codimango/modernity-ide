"""Regression gates for the Round 2 Falling Devil benchmark."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "06-falling-devil"


class RoundTwoFallingDevilTests(unittest.TestCase):
    """Require the source's full arm inventory, held head, and volumetric body."""

    def test_model_has_exactly_six_arm_pairs_and_separate_tendril(self) -> None:
        """Gate twelve articulated arms without misclassifying the waist tendril."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        generation = spec["generation"]
        inventory = generation["feature_inventory"]
        arm_records = generation["arm_chains"]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("falling_devil_twelve_armed_chef", spec["id"])
        self.assertEqual("agent-authored-semantic-volume", generation["lane"])
        self.assertEqual(0, generation["source_skin_cuboids"])
        self.assertFalse(generation["source_projection"])
        self.assertEqual(78, len(spec["cubes"]))
        self.assertEqual(6, inventory["arm_pairs"])
        self.assertEqual(12, inventory["individual_arms"])
        self.assertEqual(36, inventory["arm_segments"])
        self.assertEqual(2, inventory["head_support_arm_pairs"])
        self.assertEqual(4, inventory["head_support_hands"])
        self.assertEqual(4, inventory["head_support_contacts"])
        self.assertEqual(2, inventory["black_sleeved_arm_pairs"])
        self.assertEqual(4, inventory["bare_arm_pairs"])
        self.assertEqual(12, len(arm_records))
        self.assertEqual(
            6,
            len({record["pair"] for record in arm_records}),
        )
        self.assertTrue(all(len(record["segments"]) == 3 for record in arm_records))
        self.assertEqual(
            "independent_non_arm_appendage",
            generation["tendril"]["classification"],
        )
        self.assertEqual(6, len(generation["tendril"]["segments"]))
        self.assertTrue(
            all("tendril" not in record["pair"] for record in arm_records)
        )

    def test_detached_head_has_four_real_hand_contacts(self) -> None:
        """Gate both support pairs, bilateral hands, and physical head contact."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        generation = spec["generation"]
        contacts = generation["head_support_contacts"]
        contact_links = [
            (record["hand_cube"], record["head_cube"], record["joint"])
            for record in contacts
        ]
        audit = semantic_geometry.audit_attachments(spec, contact_links)

        self.assertEqual(4, len(contacts))
        self.assertEqual({"left", "right"}, {record["side"] for record in contacts})
        self.assertEqual(
            {"outer_head_support", "inner_head_support"},
            {record["pair"] for record in contacts},
        )
        self.assertEqual(4, len({record["hand_cube"] for record in contacts}))
        self.assertTrue(audit["all_connected"])
        self.assertGreaterEqual(audit["minimum_margin"], 0)

        structural_links = [
            (record["first"], record["second"], record["joint"])
            for record in generation["declared_attachments"]
        ]
        structural = semantic_geometry.audit_attachments(spec, structural_links)
        names = {cube["name"] for cube in spec["cubes"]}
        self.assertEqual(len(spec["cubes"]) - 1, len(structural_links))
        self.assertEqual(names, {name for link in structural_links for name in link[:2]})
        self.assertTrue(structural["all_connected"])

    def test_fixed_camera_evidence_and_depth_gates_pass(self) -> None:
        """Gate raw-frame resemblance, limb layering, volume, and honest limits."""
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        fixed = report["fixed_camera_perspective"]
        self.assertEqual("fixed-camera-perspective-evidence-v1", fixed["method"])
        self.assertEqual(
            "raw source pixels; no automatic fitting or recentering",
            fixed["alignment"],
        )
        self.assertTrue(fixed["camera_parameters_are_estimated"])
        self.assertFalse(fixed["visual_hull_used"])
        self.assertFalse(fixed["hidden_geometry_established"])
        self.assertTrue(report["source_iou_gate_at_least_0.62"])
        self.assertGreaterEqual(fixed["silhouette"]["iou"], 0.62)
        self.assertTrue(report["keypoint_mean_gate_at_most_0.06_subject_heights"])
        self.assertLessEqual(
            fixed["keypoints"]["mean_error_subject_heights"],
            0.06,
        )
        self.assertEqual(["bottom"], report["reference_frame_clipping"]["declared_edges"])
        self.assertTrue(
            report["reference_frame_clipping"]["measured_edges"]["bottom"]
        )
        self.assertTrue(report["six_arm_pair_feature_gate"])
        self.assertEqual(6, len(report["arm_pair_depth_centers_z"]))
        self.assertGreaterEqual(report["proportions"]["arm_depth_span"], 15.0)
        self.assertGreaterEqual(
            report["proportions"]["minimum_pair_depth_center_separation"], 1.5
        )
        self.assertGreaterEqual(report["proportions"]["torso_depth_to_width"], 0.45)
        self.assertGreater(report["proportions"]["head_to_collar_negative_space"], 0.25)
        self.assertTrue(report["all_proportion_gates_pass"])
        self.assertTrue(report["all_four_head_support_contacts_touch"])
        self.assertTrue(report["declared_link_tree_covers_every_cube"])

    def test_stylized_reference_texture_is_bounded_and_auditable(self) -> None:
        """Gate calibrated v2 transfer without photographic pixels or noise."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        evidence = json.loads(
            (CYCLE / "texture-evidence.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (CYCLE / "texture-views.json").read_text(encoding="utf-8")
        )
        camera = json.loads(
            (CYCLE / "render" / "perspective-camera.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            "calibrated-perspective-visible-face-texture-bake-v2",
            evidence["algorithm"],
        )
        self.assertEqual(evidence, spec["generation"]["texture_transfer"])
        self.assertEqual(1, spec["texture"]["density"])
        self.assertEqual(1024, spec["texture"]["atlas_size"])
        self.assertEqual("minecraft", spec["texture"]["source_style"])
        self.assertFalse(spec["texture"]["quantize_source"])

        style = evidence["style"]
        self.assertEqual("minecraft", style["name"])
        self.assertEqual(24, style["requested_palette_size"])
        self.assertLessEqual(len(style["actual_palette"]), 24)
        self.assertEqual(4, style["colors_per_material"])
        self.assertTrue(
            all(len(palette) <= 4 for palette in style["material_palettes"].values())
        )
        self.assertFalse(style["dithering"])
        self.assertFalse(style["source_pixels_embedded_verbatim"])
        self.assertTrue(
            all(
                material["pattern"] not in {"dither", "spots"}
                for material in spec["materials"].values()
            )
        )

        coverage = evidence["coverage"]
        self.assertEqual(3286, coverage["source_texels"])
        self.assertEqual(24840, coverage["fallback_texels"])
        self.assertEqual(132, coverage["faces_with_source"])
        self.assertEqual(336, coverage["fallback_only_faces"])
        self.assertAlmostEqual(0.116831, coverage["source_fraction"], places=6)
        self.assertEqual(camera, manifest["views"][0]["camera"])
        self.assertEqual(
            spec["reference"]["sha256"], manifest["views"][0]["image_sha256"]
        )
        self.assertEqual(
            hashlib.sha256((CYCLE / "render" / "reference-mask.png").read_bytes())
            .hexdigest(),
            manifest["views"][0]["mask_sha256"],
        )

    def test_reference_contract_and_required_artifacts_exist(self) -> None:
        """Require exact input metadata, review views, and native build products."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        reference_entry = next(
            asset
            for asset in json.loads(
                (ROOT / "benchmarks" / "round2" / "references.json").read_text(
                    encoding="utf-8"
                )
            )["assets"]
            if asset["id"] == "falling_devil"
        )
        self.assertEqual(reference_entry["sha256"], spec["reference"]["sha256"])
        self.assertEqual([399, 501], [spec["reference"]["width"], spec["reference"]["height"]])
        local_reference = ROOT / "image-12.png"
        if local_reference.is_file():
            self.assertEqual(
                reference_entry["sha256"],
                hashlib.sha256(local_reference.read_bytes()).hexdigest(),
            )

        evaluation = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        for relative in evaluation["views"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            minimum_size = 200 if path.suffix == ".json" else 1000
            self.assertGreater(path.stat().st_size, minimum_size, relative)

        audit = json.loads(
            (CYCLE / "build" / "falling_devil_twelve_armed_chef.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        for relative in (
            "falling_devil_twelve_armed_chef.bbmodel",
            "falling_devil_twelve_armed_chef.geo.json",
            "falling_devil_twelve_armed_chef.manifest.json",
            "falling_devil_twelve_armed_chef.model-spec.json",
            "falling_devil_twelve_armed_chef.png",
        ):
            self.assertTrue((CYCLE / "build" / relative).is_file(), relative)
        if local_reference.is_file():
            self.assertTrue(
                (CYCLE / "build" / "falling_devil_twelve_armed_chef.zip").is_file()
            )


if __name__ == "__main__":
    unittest.main()
