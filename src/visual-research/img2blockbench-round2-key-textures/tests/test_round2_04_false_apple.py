"""Regression gates for the Round 2 False Apple benchmark."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "04-false-apple"


class RoundTwoFalseAppleTests(unittest.TestCase):
    """Require an asymmetric volumetric root beast rather than a flat biped."""

    def test_false_apple_is_native_carved_and_connected(self) -> None:
        """Gate the carved maw, apple junction, root layers, and contact tree."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = {cube["name"] for cube in spec["cubes"]}
        generation = spec["generation"]
        inventory = generation["feature_inventory"]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("false_apple_root_beast", spec["id"])
        self.assertEqual("agent-authored-semantic-volume", generation["lane"])
        self.assertEqual(189, len(spec["cubes"]))
        self.assertEqual(0, generation["source_skin_cuboids"])
        self.assertFalse(generation["source_projection"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )

        skull = generation["ellipsoids"]["skull"]
        self.assertEqual(78, skull["removed_voxels"])
        self.assertEqual(2, len(skull["cutouts"]))
        self.assertTrue(skull["carved_faces"])
        self.assertFalse(any(cube["material"] == "maw_shadow" for cube in spec["cubes"]))
        self.assertEqual(12, inventory["maw_teeth"])
        self.assertEqual(32, inventory["apple_cuboids"])
        self.assertEqual(3, inventory["apple_flesh_drips"])
        self.assertEqual(4, inventory["root_limbs"])
        self.assertEqual(2, inventory["near_root_limbs"])
        self.assertEqual(2, inventory["far_root_limbs"])
        self.assertIn("body_core", names)
        self.assertTrue(any(name.startswith("spine_rearward_") for name in names))

        links = [
            (record["first"], record["second"], record["joint"])
            for record in generation["declared_attachments"]
        ]
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertEqual(len(spec["cubes"]) - 1, len(links))
        self.assertEqual(names, {name for link in links for name in link[:2]})
        self.assertTrue(report["all_connected"])
        self.assertGreaterEqual(report["minimum_margin"], 0)

    def test_false_apple_evidence_passes_round_two_contract(self) -> None:
        """Gate silhouette, landmarks, local depth, root layering, and grounding."""
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["source_iou_gate_at_least_0.62"])
        self.assertGreaterEqual(report["alpha_silhouette"]["iou"], 0.62)
        self.assertTrue(report["keypoint_mean_gate_at_most_0.06_subject_heights"])
        self.assertLessEqual(
            report["alpha_silhouette"]["keypoints"]["mean_error_subject_heights"],
            0.06,
        )
        self.assertEqual(
            ["left", "right", "top", "bottom"],
            report["reference_frame_clipping"]["declared_edges"],
        )
        self.assertTrue(
            all(report["reference_frame_clipping"]["measured_edges"].values())
        )
        self.assertTrue(
            report["reference_frame_clipping"][
                "iou_cannot_establish_off_frame_continuation"
            ]
        )

        proportions = report["proportions"]
        self.assertGreaterEqual(proportions["apple_depth_to_width"], 0.75)
        self.assertGreaterEqual(proportions["head_maw_depth_to_height"], 0.55)
        self.assertGreaterEqual(proportions["root_layer_center_separation"], 10.0)
        self.assertTrue(report["all_proportion_gates_pass"])
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertTrue(report["negative_space"]["maw_is_empty_geometry_not_black_proxy"])
        self.assertEqual(0, report["negative_space"]["black_maw_proxy_solids"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertTrue(report["declared_link_tree_covers_every_cube"])
        self.assertIn(
            "explicit selected-oriented-cuboid world bounds",
            report["part_local_depth_audit"]["method"],
        )
        self.assertEqual(
            {"far_rear_arch", "far_under_root", "near_fore_hand", "near_right_root"},
            set(report["root_ground_contacts"]),
        )

    def test_reference_contract_and_required_artifacts_exist(self) -> None:
        """Require the exact private input contract, real views, and native build."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        reference_entry = next(
            asset
            for asset in json.loads(
                (ROOT / "benchmarks" / "round2" / "references.json").read_text(
                    encoding="utf-8"
                )
            )["assets"]
            if asset["id"] == "false_apple"
        )
        self.assertEqual(reference_entry["sha256"], spec["reference"]["sha256"])
        self.assertEqual([599, 290], [spec["reference"]["width"], spec["reference"]["height"]])
        local_reference = ROOT / "image-2.png"
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
            self.assertGreater(path.stat().st_size, 1000, relative)

        audit = json.loads(
            (CYCLE / "build" / "false_apple_root_beast.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        for relative in (
            "false_apple_root_beast.bbmodel",
            "false_apple_root_beast.geo.json",
            "false_apple_root_beast.manifest.json",
            "false_apple_root_beast.model-spec.json",
            "false_apple_root_beast.png",
        ):
            self.assertTrue((CYCLE / "build" / relative).is_file(), relative)
        if local_reference.is_file():
            self.assertTrue((CYCLE / "build" / "false_apple_root_beast.zip").is_file())


if __name__ == "__main__":
    unittest.main()
