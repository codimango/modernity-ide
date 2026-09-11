import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "cycles" / "06-scp-173"


class CycleSixScpTests(unittest.TestCase):
    def test_scp_is_native_volumetric_and_semantically_complete(self):
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = [cube["name"] for cube in spec["cubes"]]
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("scp_173", spec["id"])
        self.assertEqual(79, len(spec["cubes"]))
        self.assertEqual(43, sum(name.startswith("head_volume_") for name in names))
        self.assertEqual(19, sum(name.startswith("torso_volume_") for name in names))
        self.assertEqual(0, sum(cube["bone"] == "face" for cube in spec["cubes"]))
        self.assertEqual(
            43,
            sum(
                cube.get("faces", {}).get("south", {}).get("material")
                == "face_decal"
                for cube in spec["cubes"]
            ),
        )
        decal = spec["generation"]["procedural_face_decal"]
        self.assertEqual(0, decal["geometric_protrusion"])
        self.assertFalse(decal["source_reference_pixels"])
        self.assertEqual(2, decal["features"]["upper_green_discs"])
        self.assertEqual(2, decal["features"]["lower_black_sockets"])
        self.assertEqual(4, decal["features"]["jagged_mouth_teeth"])
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertFalse(spec["generation"]["source_projection"])
        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertEqual(14, len(links))
        self.assertTrue(report["all_connected"])
        self.assertGreaterEqual(report["minimum_margin"], 0)

    def test_scp_evidence_matches_measured_proportions(self):
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        proportions = report["proportion_metrics"]
        self.assertLessEqual(abs(proportions["head_width_to_height"] - 0.202), 0.02)
        self.assertLessEqual(abs(proportions["torso_width_to_height"] - 0.149), 0.02)
        self.assertLessEqual(abs(proportions["leg_height_to_height"] - 0.24), 0.04)
        self.assertLessEqual(abs(proportions["overall_width_to_height"] - 0.28), 0.03)
        self.assertGreaterEqual(proportions["head_depth_to_width"], 0.9)
        self.assertGreaterEqual(proportions["torso_depth_to_width"], 0.85)
        self.assertLessEqual(proportions["ground_gap"], 0.1)
        self.assertTrue(report["face_contract_pass"])
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertTrue(report["no_reference_image_projection"])
        self.assertEqual(0, report["procedural_decal"]["geometric_protrusion"])

    def test_scp_view_proof_discloses_proxy_limit(self):
        proof = json.loads(
            (CYCLE / "view-proof" / "model-spec.json").read_text(encoding="utf-8")
        )
        evidence = json.loads(
            (CYCLE / "view-proof" / "evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], img2blockbench.validate_spec(proof, strict=True))
        self.assertEqual(
            ["observed", "synthetic_proxy"],
            sorted(view["evidence_kind"] for view in evidence["views"]),
        )
        constraints = evidence["axis_constraints"]
        self.assertEqual(2, constraints["horizontal_constraint_rank_all"])
        self.assertEqual(1, constraints["horizontal_constraint_rank_observed"])
        self.assertFalse(evidence["hidden_geometry_established_from_observed_views"])
        self.assertGreaterEqual(
            evidence["per_view_silhouette"]["front_observed"]["fitted_cuboids"]["iou"],
            0.85,
        )
        self.assertGreaterEqual(
            evidence["per_view_silhouette"]["side_synthetic_proxy"]["fitted_cuboids"]["iou"],
            0.85,
        )


if __name__ == "__main__":
    unittest.main()
