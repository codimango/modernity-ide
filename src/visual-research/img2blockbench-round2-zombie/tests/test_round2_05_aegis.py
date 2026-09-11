"""Regression gates for the Round 2 Aegis X2 turret benchmark."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "05-aegis-x2"


class RoundTwoAegisX2Tests(unittest.TestCase):
    """Require a detailed native turret with explicit mechanisms and evidence."""

    def test_model_is_native_detailed_and_semantically_complete(self) -> None:
        """Gate the native model, identity assemblies, and articulation axes."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = {cube["name"] for cube in spec["cubes"]}
        generation = spec["generation"]
        inventory = generation["feature_inventory"]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("aegis_x2_turret", spec["id"])
        self.assertEqual("agent-authored-semantic-volume", generation["lane"])
        self.assertGreaterEqual(len(spec["cubes"]), 120)
        self.assertLessEqual(len(spec["cubes"]), 180)
        self.assertEqual(0, generation["source_skin_cuboids"])
        self.assertFalse(generation["source_projection"])
        self.assertFalse(generation["visual_hull_used"])
        self.assertFalse(generation["hidden_geometry_established"])
        self.assertTrue(generation["camera_parameters_are_estimated"])

        self.assertEqual(4, inventory["outrigger_assemblies"])
        self.assertEqual(4, inventory["grounded_feet"])
        self.assertEqual(4, inventory["vertical_outer_pistons"])
        self.assertGreaterEqual(inventory["pedestal_cuboids"], 20)
        self.assertGreaterEqual(inventory["pitch_drive_drum_cuboids"], 12)
        self.assertGreaterEqual(inventory["cannon_cuboids"], 15)
        self.assertGreaterEqual(inventory["launcher_cuboids"], 14)
        self.assertGreaterEqual(inventory["cable_cuboids"], 17)
        self.assertGreaterEqual(inventory["texture_landmarks"], 30)
        for required in (
            "yaw_ring_core",
            "cradle_crossbeam",
            "cannon_barrel",
            "cannon_muzzle_brake",
            "launcher_receiver_core",
            "launcher_grip_pad",
        ):
            self.assertIn(required, names)

        self.assertEqual("+Y", generation["yaw_axis"]["axis"])
        self.assertEqual("+Z", generation["pitch_axis"]["axis"])
        self.assertEqual([1, 0, 0], generation["weapon_axes"]["cannon"]["direction"])
        self.assertEqual([-1, 0, 0], generation["weapon_axes"]["launcher"]["direction"])

    def test_all_three_private_references_have_pinned_provenance(self) -> None:
        """Require reproducible metadata and verify local private files when present."""
        provenance = json.loads(
            (CYCLE / "provenance.json").read_text(encoding="utf-8")
        )
        expected = {
            "image-3.png": "31bb69536ce0f26540034096402cebc6e006ee9cb7ec56b38deb5bf04afb2e23",
            "image-4.png": "d53b51bd62a7f64f1a4c792f1bd1005de204ed1ba0475ca4fb527784163ade4b",
            "image-5.png": "83f83385de5d68c3b4b1f8bc7d371dc086780f4388754a8414b07f0294cfe7a6",
        }
        records = {
            record["source"].removeprefix("local Round 2 "): record["sha256"]
            for record in provenance["references"]
        }
        self.assertEqual(expected, records)
        for filename, digest in expected.items():
            reference = ROOT / filename
            if reference.is_file():
                self.assertEqual(
                    digest,
                    hashlib.sha256(reference.read_bytes()).hexdigest(),
                    filename,
                )

    def test_attachment_contact_and_part_depth_audits_pass(self) -> None:
        """Gate a connected cube tree separately from four ground contacts."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        attachment = semantic_geometry.audit_attachments(spec, links)
        self.assertTrue(attachment["all_connected"])
        self.assertGreaterEqual(attachment["minimum_margin"], 0)
        self.assertEqual(len(spec["cubes"]) - 1, len(links))

        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["declared_link_tree_covers_every_cube"])
        contacts = report["contact_constraints"]
        self.assertTrue(contacts["all_four_supports_grounded"])
        self.assertTrue(contacts["distinct_xz_quadrants"])
        self.assertEqual(4, len(contacts["supports"]))
        self.assertTrue(all(item["minimum_y"] == 0.0 for item in contacts["supports"]))
        self.assertTrue(report["articulation_audit"]["weapon_axes_opposed"])
        self.assertEqual(-1.0, report["articulation_audit"]["weapon_axis_dot_product"])
        for part in ("pedestal", "cradle", "cannon", "launcher", "outriggers"):
            extents = report["part_local_depth_audit"]["parts"][part][
                "effective_world_extents"
            ]
            self.assertTrue(all(value > 0 for value in extents), part)
            self.assertGreater(
                report["part_local_depth_audit"]["parts"][part][
                    "minimum_to_maximum_extent_ratio"
                ],
                0.1,
                part,
            )

    def test_three_fixed_perspective_views_pass_raw_evidence_targets(self) -> None:
        """Gate three independent fixed frames with no fitting or hull claims."""
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["all_perspective_aspirations_pass"])
        self.assertTrue(report["camera_parameters_are_estimated"])
        self.assertFalse(report["visual_hull_used"])
        self.assertFalse(report["hidden_geometry_established"])
        cameras = report["perspective_camera_contract"]
        self.assertEqual(
            "three-independent-manually-frozen-perspective-cameras-v1",
            cameras["method"],
        )
        self.assertFalse(cameras["runtime_camera_fitting"])
        self.assertFalse(cameras["automatic_fit_or_recentering"])
        self.assertEqual(3, len(cameras["cameras"]))

        for source_name in ("source-3", "source-4", "source-5"):
            evidence = report["perspective_source_evidence"][source_name]
            gate = report["perspective_source_gates"][source_name]
            self.assertEqual("fixed-camera-perspective-evidence-v1", evidence["method"])
            self.assertIn("no automatic fitting", evidence["alignment"])
            self.assertTrue(evidence["held_out_keypoints"])
            self.assertFalse(evidence["visual_hull_used"])
            self.assertFalse(evidence["hidden_geometry_established"])
            self.assertGreaterEqual(gate["iou"], 0.60)
            self.assertLessEqual(
                gate["held_out_keypoint_mean_error_subject_heights"], 0.06
            )
            self.assertTrue(gate["iou_pass"])
            self.assertTrue(gate["keypoint_pass"])

    def test_required_views_and_native_build_exist(self) -> None:
        """Require every review image and deterministic native artifact."""
        evaluation = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        for relative in evaluation["views"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 1000, relative)
        for relative in evaluation["evidence_files"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 500, relative)

        audit = json.loads(
            (CYCLE / "build" / "aegis_x2_turret.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        self.assertEqual(145, audit["cuboids"])
        for relative in (
            "aegis_x2_turret.bbmodel",
            "aegis_x2_turret.geo.json",
            "aegis_x2_turret.png",
            "aegis_x2_turret.manifest.json",
            "aegis_x2_turret.model-spec.json",
        ):
            self.assertTrue((CYCLE / "build" / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
