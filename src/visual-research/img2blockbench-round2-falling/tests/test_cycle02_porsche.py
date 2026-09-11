import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "cycles" / "02-porsche"


class CycleTwoPorscheTests(unittest.TestCase):
    def test_porsche_is_complete_native_vehicle_volume(self):
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = [cube["name"] for cube in spec["cubes"]]
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("porsche_911_turbo_930", spec["id"])
        self.assertEqual(97, len(spec["cubes"]))
        self.assertEqual(
            "complete-hard-surface-semantic-cuboids-v2",
            spec["generation"]["algorithm"],
        )
        self.assertEqual(18, spec["generation"]["feature_inventory"]["body_volumes"])
        self.assertEqual(
            12, spec["generation"]["feature_inventory"]["fender_haunch_volumes"]
        )
        self.assertEqual(4, spec["generation"]["feature_inventory"]["wheel_assemblies"])
        self.assertEqual(28, sum("_wheel_" in name for name in names))
        self.assertEqual(6, sum("headlamp" in name for name in names))
        self.assertEqual(6, spec["generation"]["feature_inventory"]["greenhouse_glass"])
        self.assertEqual(3, spec["generation"]["feature_inventory"]["spoiler_cuboids"])
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertNotIn("reference_photo", spec["materials"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )
        self.assertEqual(
            ["side_livery"], spec["generation"]["authored_texture_sources"]
        )
        self.assertIn("source_texture", spec["materials"]["side_livery"])

        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        self.assertEqual(16, len(links))
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertTrue(report["all_connected"])
        self.assertGreaterEqual(report["minimum_margin"], 0)

    def test_porsche_evidence_proves_four_sided_geometry(self):
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["vehicle_contract_pass"])
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertTrue(report["no_source_projection"])
        self.assertTrue(report["authored_livery_only"])
        self.assertGreaterEqual(report["source_angle_silhouette"]["iou"], 0.70)
        self.assertGreaterEqual(
            report["proportion_metrics"]["body_length_to_width"], 1.9
        )
        self.assertGreaterEqual(
            report["proportion_metrics"]["cabin_length_to_body_length"], 0.38
        )
        self.assertLessEqual(
            report["proportion_metrics"]["overall_height_to_length"], 0.42
        )
        self.assertLessEqual(
            report["proportion_metrics"]["wheelbase_to_body_length"], 0.58
        )
        self.assertLessEqual(
            max(report["proportion_metrics"]["wheel_ground_heights"]), 0.5
        )
        self.assertEqual(
            {
                "front.png",
                "back.png",
                "left.png",
                "right.png",
                "top.png",
                "isometric.png",
            },
            set(report["views"])
            & {
                "front.png",
                "back.png",
                "left.png",
                "right.png",
                "top.png",
                "isometric.png",
            },
        )


if __name__ == "__main__":
    unittest.main()
