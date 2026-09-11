"""Regression gates for the native volumetric Cycle 3 Excalibur correction."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "cycles" / "03-excalibur"


class CycleThreeExcaliburTests(unittest.TestCase):
    """Require a connected two-sided sword rather than a thin image relief."""

    def test_excalibur_is_native_semantic_volume(self) -> None:
        """Gate native geometry, identity parts, and exact connections."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = [cube["name"] for cube in spec["cubes"]]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("excalibur", spec["id"])
        self.assertEqual("agent-authored-semantic-volume", spec["generation"]["lane"])
        self.assertEqual(30, len(spec["cubes"]))
        self.assertEqual(4, sum(name.startswith("blade_") and "tip_" not in name for name in names))
        self.assertEqual(3, sum(name.startswith("blade_tip_") for name in names))
        self.assertEqual(6, sum("quillon_inlay" in name for name in names))
        self.assertEqual(6, sum(name.startswith(("left_quillon_", "right_quillon_")) and "inlay" not in name for name in names))
        self.assertIn("raised_front_crest", names)
        self.assertIn("raised_back_crest", names)
        self.assertIn("grip_core", names)
        self.assertIn("pommel_core", names)
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertFalse(spec["generation"]["source_projection"])
        self.assertFalse(spec["generation"]["procedural_textures"]["source_reference_pixels"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )

        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertEqual(31, len(links))
        self.assertTrue(report["all_connected"])
        self.assertGreater(report["minimum_margin"], 0)
        covered = {name for first, second, _ in links for name in (first, second)}
        self.assertEqual(set(names), covered)

    def test_excalibur_evidence_proves_shape_depth_and_reverse_finish(self) -> None:
        """Gate reference silhouette, profile depth, and two-sided details."""
        evidence = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        audit = json.loads(
            (CYCLE / "build" / "excalibur.audit.json").read_text(encoding="utf-8")
        )

        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        self.assertEqual([], audit["warnings"])
        self.assertTrue(evidence["attachments"]["all_connected"])
        self.assertTrue(evidence["attachment_graph"]["all_cuboids_covered"])
        self.assertTrue(evidence["recorded_feature_inventory_matches"])
        self.assertTrue(evidence["no_reference_image_projection"])
        self.assertGreaterEqual(evidence["source_silhouette"]["iou"], 0.50)
        self.assertLessEqual(evidence["source_silhouette"]["major_axis_delta_degrees"], 2.0)
        self.assertGreaterEqual(
            evidence["proportion_metrics"]["blade_profile_depth_to_length"], 0.025
        )
        self.assertLessEqual(
            evidence["proportion_metrics"]["blade_profile_depth_to_length"], 0.04
        )
        self.assertGreaterEqual(
            evidence["proportion_metrics"]["guard_span_to_length"], 0.22
        )
        self.assertEqual(5, evidence["texture_contract"]["front_rune_glyphs"])
        self.assertEqual(5, evidence["texture_contract"]["reverse_rune_glyphs"])
        self.assertTrue(evidence["texture_contract"]["front_crest"])
        self.assertTrue(evidence["texture_contract"]["reverse_crest"])
        self.assertTrue(evidence["texture_contract"]["two_sided_grip_wrap"])
        for filename in (
            "front.png",
            "back.png",
            "profile.png",
            "top.png",
            "isometric.png",
            "reference-angle.png",
            "hilt-junction.png",
            "emblem-and-runes.png",
            "reverse-emblem.png",
            "comparison-sheet.png",
        ):
            self.assertTrue((CYCLE / "render" / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()
