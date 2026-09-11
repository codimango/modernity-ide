"""Regression gates for the Round 2 Militech Chimera benchmark."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "02-militech-chimera"
ALT_REFERENCE_SHA256 = (
    "28ecd39372be2f3df0a5be657392b31557f8a91fb90136a78722878548bf46f7"
)


class RoundTwoMilitechChimeraTests(unittest.TestCase):
    """Require a deep semantic hexapod rather than a source-photo relief."""

    def test_chimera_is_native_deep_and_semantically_complete(self) -> None:
        """Gate six articulated legs, layered armor, identity, and connectivity."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = [cube["name"] for cube in spec["cubes"]]
        inventory = spec["generation"]["feature_inventory"]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("militech_chimera", spec["id"])
        self.assertEqual("agent-authored-semantic-volume", spec["generation"]["lane"])
        self.assertEqual(
            "deep-hard-surface-hexapod-semantic-cuboids-v2",
            spec["generation"]["algorithm"],
        )
        self.assertEqual(174, len(spec["cubes"]))
        self.assertEqual(36, len(spec["bones"]))
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertFalse(spec["generation"]["source_projection"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )

        legs = spec["generation"]["leg_chains"]
        self.assertEqual(6, len(legs))
        self.assertEqual({"front", "middle", "rear"}, {leg["station"] for leg in legs})
        self.assertEqual(
            {"front": 2, "middle": 2, "rear": 2},
            {
                station: sum(leg["station"] == station for leg in legs)
                for station in ("front", "middle", "rear")
            },
        )
        self.assertEqual(6, len({tuple(record["root"]) for record in legs}))
        self.assertTrue(all(len(record["segments"]) == 4 for record in legs))
        self.assertTrue(all(len(record["hinges"]) == 3 for record in legs))
        self.assertTrue(all(len(record["shin_plates"]) == 2 for record in legs))

        expected_inventory = {
            "amber_status_lights": 12,
            "body_volumes": 27,
            "foot_armor_blocks": 6,
            "front_optics": 3,
            "grounded_feet": 6,
            "hip_housings": 6,
            "mechanical_hinges": 18,
            "mechanical_leg_chains": 6,
            "mechanical_leg_segments": 24,
            "panel_bolts": 24,
            "panel_seams": 6,
            "radar_pod_cuboids": 7,
            "roof_antennae": 3,
            "shin_armor_layers": 18,
            "shin_shields": 6,
            "toe_claws": 18,
            "turret_collar_segments": 12,
            "upper_turret_cuboids": 38,
        }
        self.assertEqual(expected_inventory, inventory)
        self.assertIn("front_sensor_bar", names)
        self.assertIn("cabin_core", names)

        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        self.assertEqual(191, len(links))
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertTrue(report["all_connected"])
        self.assertGreater(report["minimum_margin"], 0)

    def test_chimera_evidence_passes_volume_and_stance_contract(self) -> None:
        """Gate body depth, six grounded roots, inventory, and honest diagnostics."""
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["all_proportion_gates_pass"])
        self.assertGreaterEqual(
            report["proportion_metrics"]["chassis_depth_to_width"], 0.55
        )
        self.assertEqual([0.0] * 6, report["proportion_metrics"]["foot_ground_heights"])
        self.assertEqual(6, len({tuple(root) for root in report["root_positions"]}))
        self.assertEqual(
            {"front": 2, "middle": 2, "rear": 2}, report["leg_station_counts"]
        )
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertTrue(report["feature_contract_pass"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertEqual(191, len(report["attachments"]["attachments"]))

        diagnostics = report["perspective_source_evidence"]
        for label, minimum_iou in (("original", 0.58), ("alternate", 0.60)):
            perspective = diagnostics[label]
            self.assertEqual(
                "fixed-camera-perspective-evidence-v1", perspective["method"]
            )
            self.assertTrue(perspective["camera_parameters_are_estimated"])
            self.assertFalse(perspective["visual_hull_used"])
            self.assertFalse(perspective["hidden_geometry_established"])
            self.assertIn("no automatic fitting", perspective["alignment"])
            self.assertGreaterEqual(perspective["silhouette"]["iou"], minimum_iou)
            self.assertLessEqual(
                perspective["keypoints"]["mean_error_subject_heights"], 0.08
            )

        gate = report["perspective_source_gate"]
        self.assertEqual("pass_independent_visual_review", gate["status"])
        self.assertEqual(0.65, gate["target_iou_at_least"])
        self.assertEqual(0.06, gate["target_keypoint_mean_error_subject_heights_at_most"])
        self.assertFalse(gate["hard_acceptance_gate"])

        calibrations = report["perspective_camera_calibration"]
        for label, image_size in (("original", [600, 900]), ("alternate", [736, 414])):
            calibration = calibrations[label]
            self.assertFalse(calibration["runtime_camera_fitting"])
            self.assertFalse(calibration["geometry_modified_for_calibration"])
            self.assertEqual(10.0, calibration["orbit_parameters"]["pitch_degrees"])
            self.assertEqual(image_size, calibration["resolved_camera"]["image_size"])

    def test_chimera_dual_reference_contract_and_final_grade(self) -> None:
        """Require the user-supplied six-leg reference and replacement grade."""
        contract = json.loads(
            (CYCLE / "inputs" / "input-contract.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ALT_REFERENCE_SHA256, contract["alternate_source"]["sha256"])
        self.assertEqual([736, 414], contract["alternate_source"]["size"])
        self.assertEqual(
            "alternate-foreground-mask.png", contract["alternate_foreground"]["image"]
        )
        self.assertTrue((CYCLE / "inputs" / "alternate-foreground-mask.png").is_file())

        grade = json.loads((CYCLE / "grade.json").read_text(encoding="utf-8"))
        self.assertEqual("PASS", grade["status"])
        self.assertEqual(4.0, grade["independent_visual_mean"])
        self.assertTrue(grade["previous_grade_invalidated"])

    def test_chimera_required_views_and_native_build_exist(self) -> None:
        """Require every review image and all deterministic native artifacts."""
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
            (CYCLE / "build" / "militech_chimera.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        for relative in (
            "militech_chimera.bbmodel",
            "militech_chimera.geo.json",
            "militech_chimera.png",
            "militech_chimera.manifest.json",
            "militech_chimera.model-spec.json",
        ):
            self.assertTrue((CYCLE / "build" / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
