"""Regression gates for the Round 2 Greta shark-chef benchmark."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "03-greta"
MODEL_ID = "greta_shark_chef"


class RoundTwoGretaTests(unittest.TestCase):
    """Require a true-volume rig with Greta's exact asymmetric identity."""

    def test_greta_has_exact_identity_topology_and_connected_parts(self) -> None:
        """Gate four mouths, semantic graphs, joints, and held-prop contact."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = {cube["name"] for cube in spec["cubes"]}
        generation = spec["generation"]
        inventory = generation["feature_inventory"]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual(MODEL_ID, spec["id"])
        self.assertEqual("agent-authored-semantic-volume", generation["lane"])
        self.assertEqual(72, len(spec["cubes"]))
        self.assertEqual(0, generation["source_skin_cuboids"])
        self.assertFalse(generation["source_projection"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )

        mouths = {name for name in names if name.startswith("mouth_")}
        self.assertEqual(
            {"mouth_head", "mouth_hand", "mouth_tail_base", "mouth_tail_mid"},
            mouths,
        )
        tooth_rows = [
            landmark
            for landmark in spec["landmarks"]
            if landmark["name"].endswith("_teeth")
        ]
        self.assertEqual(8, len(tooth_rows))
        self.assertEqual(mouths, {landmark["cube"] for landmark in tooth_rows})
        self.assertTrue(
            all(
                sum(row["cube"] == mouth for row in tooth_rows) == 2
                for mouth in mouths
            )
        )
        self.assertEqual(4, inventory["toothed_mouth_assemblies"])
        self.assertEqual(1, inventory["head_mouths"])
        self.assertEqual(1, inventory["hand_mouths"])
        self.assertEqual(2, inventory["tail_mouths"])
        self.assertEqual(1, inventory["red_eye_landmarks"])
        self.assertEqual(12, inventory["blue_tattoo_landmarks"])
        self.assertEqual(5, inventory["chef_hat_cuboids"])
        self.assertEqual(2, inventory["dorsal_fin_segments"])
        self.assertEqual(2, inventory["humanoid_arm_chains"])
        self.assertEqual(2, inventory["biped_leg_chains"])
        self.assertEqual(2, inventory["grounded_feet"])

        tail_edges = generation["tail_graph"]["edges"]
        self.assertEqual(5, len(tail_edges))
        self.assertEqual(
            {"upper_fin", "lower_fin"},
            {edge["name"] for edge in tail_edges if edge["name"].endswith("_fin")},
        )
        self.assertIn("tail_fork_hub", names)
        self.assertTrue(
            {"axe_handle", "axe_head", "axe_cheek", "axe_hook"}.issubset(names)
        )
        self.assertEqual(
            [{
                "prop": "axe",
                "hand_cube": "left_hand",
                "prop_cube": "axe_handle",
                "joint": [-12.5, 30.0, 1.8],
            }],
            generation["held_prop_contacts"],
        )

        links = [
            (record["first"], record["second"], record["joint"])
            for record in generation["declared_attachments"]
        ]
        self.assertEqual(71, len(links))
        self.assertIn(("left_hand", "axe_handle", [-12.5, 30.0, 1.8]), links)
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertTrue(report["all_connected"])
        self.assertGreaterEqual(report["minimum_margin"], 0)

    def test_greta_evidence_passes_source_depth_and_grounding_contract(self) -> None:
        """Gate the measured source match without hiding single-view uncertainty."""
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )

        self.assertTrue(report["all_proportion_gates_pass"])
        self.assertGreaterEqual(report["alpha_silhouette"]["iou"], 0.68)
        self.assertTrue(report["source_iou_gate_at_least_0.68"])
        self.assertLessEqual(
            report["alpha_silhouette"]["keypoints"]["mean_error_subject_heights"],
            0.05,
        )
        self.assertTrue(report["keypoint_mean_error_gate_at_most_0.05"])
        self.assertGreaterEqual(
            report["proportion_metrics"]["torso_depth_to_body_width"], 0.35
        )
        self.assertGreaterEqual(
            report["proportion_metrics"]["head_depth_to_body_width"], 0.35
        )
        self.assertEqual([0.0, 0.0], report["proportion_metrics"]["foot_ground_heights"])
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertTrue(report["feature_contract_pass"])
        self.assertTrue(report["axe_contact_present"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertFalse(report["alpha_silhouette"]["source_touches_frame"])
        self.assertEqual(
            "inferred_conservatively_not_observed",
            report["single_view_hidden_geometry"],
        )

    def test_greta_build_is_native_audited_and_deterministic(self) -> None:
        """Require native artifacts and byte-identical repeated compilation."""
        evaluation = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        for relative in evaluation["views"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 1000, relative)

        build = CYCLE / "build"
        audit = json.loads(
            (build / f"{MODEL_ID}.audit.json").read_text(encoding="utf-8")
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        for suffix in ("bbmodel", "geo.json", "png", "manifest.json", "model-spec.json"):
            self.assertTrue((build / f"{MODEL_ID}.{suffix}").is_file(), suffix)

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first = folder / "first"
            second = folder / "second"
            first_result = img2blockbench.build_model(CYCLE / "model-spec.json", first)
            img2blockbench.build_model(CYCLE / "model-spec.json", second)
            self.assertTrue(first_result["audit"]["ok"])
            for suffix in ("bbmodel", "geo.json", "png", "manifest.json", "model-spec.json", "zip"):
                self.assertEqual(
                    (first / f"{MODEL_ID}.{suffix}").read_bytes(),
                    (second / f"{MODEL_ID}.{suffix}").read_bytes(),
                    suffix,
                )


if __name__ == "__main__":
    unittest.main()
