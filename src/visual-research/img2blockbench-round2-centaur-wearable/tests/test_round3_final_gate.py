"""Aggregate integrity gates for the unfinished Round 3 benchmark."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUND3 = ROOT / "benchmarks" / "round3"
STATUS_PATH = ROUND3 / "status.json"
EXPECTED_CYCLES = {
    "round3-01": (
        "01-biblical-angel",
        "Biblically accurate angel",
        "biblical_angel_many_eyed_six_wing",
    ),
    "round3-02": (
        "02-atlus",
        "Zetatech Atlus",
        "atlus_trauma_team_aerodyne",
    ),
    "round3-03": (
        "03-off-road-truck",
        "Minecraft-style off-road truck",
        "minecraft_off_road_truck_mesh",
    ),
    "round3-04": (
        "04-hovercraft",
        "Meshy Minecraft hovercraft",
        "meshy_minecraft_hovercraft_mesh",
    ),
}
GRADED_COMMIT = "640b8e7fe4e1179d2ce58fc16c9bb9935e6f4feb"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RoundThreeFinalGateTests(unittest.TestCase):
    """Prevent blocked mesh cycles from becoming a false cumulative pass."""

    def setUp(self) -> None:
        self.status = _read_json(STATUS_PATH)
        self.cycles = {
            cycle["cycle"]: cycle for cycle in self.status["cycles"]
        }

    def test_round_is_explicitly_in_progress_and_not_a_cumulative_pass(self) -> None:
        self.assertEqual("round3", self.status["round"])
        self.assertEqual("IN_PROGRESS", self.status["status"])
        self.assertEqual("PENDING", self.status["gate_status"])
        self.assertFalse(self.status["cumulative_pass"])
        self.assertEqual(
            {"MISSING_PRIVATE_INPUT"}, set(self.status["blocking_reasons"])
        )
        self.assertEqual("PASS", self.status["pipeline_grade"]["status"])
        self.assertEqual(
            GRADED_COMMIT, self.status["pipeline_grade"]["graded_commit"]
        )

    def test_all_four_cycles_are_unique_and_name_the_exact_assets(self) -> None:
        self.assertEqual(4, len(self.status["cycles"]))
        self.assertEqual(set(EXPECTED_CYCLES), set(self.cycles))
        self.assertEqual(4, len({cycle["slug"] for cycle in self.cycles.values()}))
        self.assertEqual(4, len({cycle["model_id"] for cycle in self.cycles.values()}))
        for cycle_id, (slug, asset, model_id) in EXPECTED_CYCLES.items():
            record = self.cycles[cycle_id]
            self.assertEqual(slug, record["slug"])
            self.assertEqual(asset, record["asset"])
            self.assertEqual(model_id, record["model_id"])
            self.assertTrue((ROUND3 / "cycles" / slug).is_dir())

    def test_image_cycles_have_exact_commit_independent_passes(self) -> None:
        for cycle_id in ("round3-01", "round3-02"):
            with self.subTest(cycle=cycle_id):
                record = self.cycles[cycle_id]
                grade = record["grade"]
                self.assertEqual("PASS", record["status"])
                self.assertEqual("pass", grade["decision"])
                self.assertEqual("FINAL", grade["status"])
                self.assertEqual(GRADED_COMMIT, grade["graded_commit"])
                self.assertEqual("pass", grade["exact_commit_grade"])

    def test_mesh_cycles_wait_for_private_inputs_without_pass_claims(self) -> None:
        for cycle_id in ("round3-03", "round3-04"):
            with self.subTest(cycle=cycle_id):
                record = self.cycles[cycle_id]
                grade = record["grade"]
                result = _read_json(
                    ROUND3 / "cycles" / record["slug"] / "results.json"
                )
                self.assertEqual("PENDING_INPUT", record["status"])
                self.assertEqual("MISSING_PRIVATE_INPUT", record["blocker"]["code"])
                self.assertIsNone(grade["decision"])
                self.assertEqual("NOT_STARTED", grade["status"])
                self.assertEqual("BLOCKED", result["status"])
                self.assertFalse(result["pass_claimed"])
                self.assertEqual(
                    "MISSING_PRIVATE_INPUT", result["blocker"]["code"]
                )

    def test_inputs_are_private_ignored_and_not_tracked(self) -> None:
        policy = self.status["input_policy"]
        self.assertEqual("round3-inputs/", policy["directory"])
        self.assertTrue(policy["gitignored"])
        self.assertFalse(policy["source_media_committed"])
        ignored_paths = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/round3-inputs/", ignored_paths)
        for cycle in self.cycles.values():
            source = cycle["input"]
            self.assertTrue(source["relative_path"].startswith("round3-inputs/"))
            self.assertTrue(source["private"])
            self.assertFalse(source["committed"])
            self.assertFalse(Path(source["relative_path"]).is_absolute())

        tracked = subprocess.run(
            ["git", "ls-files", "--", "round3-inputs"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", tracked.stdout.strip())

    def test_delivery_remains_local_without_remote_or_public_claim(self) -> None:
        delivery = self.status["repository_delivery"]
        self.assertEqual("LOCAL_ONLY", delivery["scope"])
        self.assertFalse(delivery["remote_configured"])
        self.assertFalse(delivery["public_push_performed"])
        self.assertFalse(delivery["pull_request_created"])

        remotes = subprocess.run(
            ["git", "remote"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", remotes.stdout.strip())

    def test_status_files_are_portable_and_make_no_final_pass_claim(self) -> None:
        status_text = STATUS_PATH.read_text(encoding="utf-8")
        summary_text = (ROUND3 / "STATUS.md").read_text(encoding="utf-8")
        for text in (status_text, summary_text):
            self.assertNotIn(Path.home().as_posix(), text)
            self.assertNotIn("/var/folders/", text)
            self.assertNotIn("/tmp/", text)
        self.assertNotIn("cumulative PASS", summary_text)
        self.assertIn("cumulative_pass` is false", summary_text)


if __name__ == "__main__":
    unittest.main()
