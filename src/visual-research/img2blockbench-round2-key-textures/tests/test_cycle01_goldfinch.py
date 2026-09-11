"""Regression gates for the volumetric Cycle 1 goldfinch correction."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "cycles" / "01-goldfinch"


class CycleOneGoldfinchTests(unittest.TestCase):
    """Require native bilateral anatomy rather than a source-photo relief."""

    def test_goldfinch_is_connected_semantic_volume(self) -> None:
        """Gate the identity inventory, depth, and audited articulations."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        evidence = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        audit = json.loads(
            (CYCLE / "build" / "american_goldfinch.audit.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(spec["generation"]["lane"], "agent-authored-semantic-volume")
        self.assertEqual(spec["generation"]["source_skin_cuboids"], 0)
        self.assertEqual(evidence["source_skin_cuboids"], 0)
        self.assertTrue(audit["ok"])
        self.assertTrue(evidence["attachments"]["all_connected"])
        self.assertGreater(evidence["attachments"]["minimum_margin"], 0)
        self.assertTrue(evidence["feature_contract_pass"])
        self.assertEqual(evidence["bilateral_head"]["silhouette_iou"], 1.0)
        self.assertGreaterEqual(evidence["profile"]["iou"], 0.78)
        self.assertLessEqual(evidence["profile"]["aspect_relative_error"], 0.05)

        names = {cube["name"] for cube in spec["cubes"]}
        expected = {
            "left_eye",
            "right_eye",
            "wing_left_1",
            "wing_left_2",
            "wing_left_3",
            "wing_right_1",
            "wing_right_2",
            "wing_right_3",
            "tail_feather_1",
            "tail_feather_2",
            "tail_feather_3",
            "leg_left_1",
            "leg_left_2",
            "leg_right_1",
            "leg_right_2",
        }
        self.assertTrue(expected.issubset(names))
        self.assertEqual(sum(name.startswith("toe_") for name in names), 12)
        self.assertFalse(
            any("source_region" in cube for cube in spec["cubes"]),
            "semantic model must not project the photograph onto cuboid faces",
        )
        self.assertFalse(
            any("source_texture" in material for material in spec["materials"].values())
        )


if __name__ == "__main__":
    unittest.main()
