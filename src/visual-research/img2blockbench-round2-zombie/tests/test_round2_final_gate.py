"""Cumulative evidence gates for the four-asset Round 2 final review."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "benchmarks" / "round2"


def _sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a local artifact."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RoundTwoFinalGateTests(unittest.TestCase):
    """Lock the independent four-asset review and its pinned comparison sheet."""

    def test_showcase_pins_four_unaligned_source_render_pairs(self) -> None:
        """Require four selected cycles and byte-exact render evidence."""
        manifest = json.loads(
            (ROUND / "final-showcase.json").read_text(encoding="utf-8")
        )
        self.assertEqual([2, 5, 7, 8], [pair["cycle"] for pair in manifest["pairs"]])
        self.assertFalse(manifest["post_render_alignment"])
        showcase = ROUND / "final-showcase.png"
        self.assertEqual(manifest["output_sha256"], _sha256(showcase))
        for pair in manifest["pairs"]:
            render = ROOT / pair["render"]
            self.assertTrue(render.is_file(), pair["render"])
            self.assertEqual(pair["render_sha256"], _sha256(render))
            source = ROOT / pair["source"]
            if source.is_file():
                self.assertEqual(pair["source_sha256"], _sha256(source))

    def test_independent_gate_passes_every_asset_and_category(self) -> None:
        """Reject a cumulative pass if one asset or rubric category regresses."""
        judging = json.loads(
            (ROUND / "final-judging.json").read_text(encoding="utf-8")
        )
        self.assertEqual("PASS", judging["cumulative_verdict"])
        self.assertTrue(judging["all_assets_pass"])
        self.assertEqual("HONEST", judging["evidence_integrity"]["verdict"])
        self.assertEqual(
            {"chimera", "aegis_x2", "centaur", "zombie_devil"},
            set(judging["assets"]),
        )
        expected_categories = {
            "silhouette",
            "proportions",
            "identity",
            "materials_color",
            "topology_attachments",
            "3d_coherence",
        }
        for asset in judging["assets"].values():
            self.assertEqual("PASS", asset["verdict"])
            self.assertEqual([], asset["blockers"])
            self.assertEqual(expected_categories, set(asset["scores"]))
            self.assertGreaterEqual(min(asset["scores"].values()), 3)

    def test_rejected_four_leg_chimera_cannot_regain_pass_status(self) -> None:
        """Preserve the user's six-leg correction as a cumulative hard gate."""
        grade = json.loads(
            (ROUND / "grades" / "cycle-02.json").read_text(encoding="utf-8")
        )
        self.assertTrue(grade["previous_four_leg_grade_invalidated"])
        self.assertTrue(grade["user_correction_substantively_addressed"])
        self.assertEqual(6, grade["quantitative"]["mechanical_leg_chains"])


if __name__ == "__main__":
    unittest.main()
