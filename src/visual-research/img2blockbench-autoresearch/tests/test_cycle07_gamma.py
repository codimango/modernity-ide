import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "cycles" / "07-gamma"


class CycleSevenGammaTests(unittest.TestCase):
    def test_gamma_is_native_volumetric_and_semantically_complete(self):
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = [cube["name"] for cube in spec["cubes"]]
        inventory = spec["generation"]["feature_inventory"]
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("gamma_abnormality", spec["id"])
        self.assertEqual(111, len(spec["cubes"]))
        self.assertEqual(8, inventory["upper_mandible_chains"])
        self.assertEqual(40, sum(name.startswith("mandible_") for name in names))
        self.assertEqual(4, inventory["mechanical_leg_chains"])
        self.assertEqual(12, inventory["mechanical_leg_segments"])
        self.assertEqual(8, inventory["mechanical_hinges"])
        self.assertEqual(2, inventory["silver_ring_assemblies"])
        self.assertEqual(16, sum("_ring_segment_" in name for name in names))
        self.assertEqual(1, sum(name == "chest_maw" for name in names))
        self.assertEqual(5, sum(name.startswith("maw_tooth_") for name in names))
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertFalse(spec["generation"]["source_projection"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )

        graphs = spec["generation"]["branch_graphs"]
        self.assertEqual(13, len(graphs))
        self.assertTrue(all(graph["parent_cube"] for graph in graphs))
        self.assertTrue(
            all(
                graph["nodes"] == sorted(graph["nodes"], key=lambda node: node["name"])
                for graph in graphs
            )
        )
        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertEqual(120, len(links))
        self.assertTrue(report["all_connected"])
        self.assertGreaterEqual(report["minimum_margin"], 0)

    def test_gamma_evidence_passes_quantitative_contract(self):
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["all_proportion_gates_pass"])
        self.assertTrue(report["source_iou_gate_at_least_0.58"])
        self.assertTrue(report["source_iou_aspiration_at_least_0.64"])
        self.assertGreaterEqual(report["alpha_silhouette"]["iou"], 0.64)
        self.assertTrue(report["alpha_silhouette"]["source_touches_frame"])
        self.assertIn("clipped appendages", report["alpha_silhouette"]["limitation"])
        self.assertLessEqual(
            report["alpha_silhouette"]["keypoints"]["mean_error_subject_heights"],
            0.06,
        )
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertTrue(report["feature_contract_pass"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertGreaterEqual(
            report["proportion_metrics"]["real_depth_to_full_width"], 0.22
        )

    def test_gamma_required_visual_evidence_and_clean_build_exist(self):
        evaluation = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        for relative in evaluation["views"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 1000, relative)
        audit = json.loads(
            (CYCLE / "build" / "gamma_abnormality.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        self.assertTrue((CYCLE / "build" / "gamma_abnormality.bbmodel").is_file())
        self.assertTrue((CYCLE / "build" / "gamma_abnormality.geo.json").is_file())
        self.assertTrue((CYCLE / "build" / "gamma_abnormality.png").is_file())
        self.assertTrue((CYCLE / "build" / "gamma_abnormality.zip").is_file())


if __name__ == "__main__":
    unittest.main()
