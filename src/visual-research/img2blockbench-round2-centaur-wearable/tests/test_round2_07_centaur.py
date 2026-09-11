"""Regression gates for the Round 2 piloted Centaur exoskeleton."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry
import wearable_export


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "07-centaur-exoskeleton"


class RoundTwoCentaurTests(unittest.TestCase):
    """Require a nested pilot, paired powered legs, shield, and thermal weapon."""

    def test_model_preserves_pilot_and_exoframe_as_distinct_structures(self) -> None:
        """Gate the operator inside—not substituted for—the powered chassis."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        generation = spec["generation"]
        inventory = generation["feature_inventory"]
        names = {cube["name"] for cube in spec["cubes"]}

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("militech_centaur_piloted_exoskeleton", spec["id"])
        self.assertEqual("agent-authored-semantic-volume", generation["lane"])
        self.assertFalse(generation["source_projection"])
        self.assertEqual(0, generation["source_skin_cuboids"])
        self.assertEqual(192, len(spec["cubes"]))
        self.assertEqual(1, inventory["human_pilots"])
        self.assertEqual(2, inventory["powered_exo_legs"])
        self.assertEqual(2, inventory["human_leg_chains"])
        self.assertEqual(2, inventory["human_arm_chains"])
        self.assertEqual(2, inventory["boot_restraints"])
        self.assertEqual(6, inventory["segmented_ankle_cuboids"])
        self.assertEqual(6, inventory["backpack_canister_collars"])
        self.assertEqual(2, inventory["backpack_hoses"])
        self.assertIn("pilot_head_core", names)
        self.assertIn("left_exo_thigh_beam", names)
        self.assertIn("right_exo_thigh_beam", names)
        pilot_bones = {bone["name"] for bone in spec["bones"] if bone["name"].startswith("pilot_")}
        exo_bones = {bone["name"] for bone in spec["bones"] if "exo_" in bone["name"]}
        self.assertTrue(pilot_bones)
        self.assertTrue(exo_bones)
        self.assertTrue(pilot_bones.isdisjoint(exo_bones))

    def test_player_wearable_shell_is_separate_from_preview_pilot(self) -> None:
        """Gate the replaceable player cavity, anchors, and shell-only export."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        wearable = spec["wearable"]
        self.assertEqual([], wearable_export.validate_wearable(spec))
        self.assertEqual("minecraft_player", wearable["target"])
        self.assertEqual("replaceable", wearable["occupant_mode"])
        self.assertEqual(7, len(wearable["occupant_bones"]))
        self.assertEqual(
            {
                "waist_harness",
                "back_harness",
                "left_boot_stirrup",
                "right_boot_stirrup",
                "left_hand_control",
                "right_hand_control",
            },
            {point["name"] for point in wearable["attachment_points"]},
        )
        self.assertEqual(
            [0.0, 0.0, 0.0],
            [
                round(
                    coordinate * wearable["fit"]["scale"]
                    + wearable["fit"]["offset"][index],
                    6,
                )
                for index, coordinate in enumerate(wearable["fit"]["player_anchor"])
            ],
        )

        shell = wearable_export.make_wearable_spec(spec)
        self.assertEqual([], img2blockbench.validate_spec(shell, strict=True))
        occupant_bones = set(wearable["occupant_bones"])
        self.assertFalse(
            occupant_bones & {bone["name"] for bone in shell["bones"]}
        )
        self.assertFalse(
            any(cube["bone"] in occupant_bones for cube in shell["cubes"])
        )
        self.assertFalse(
            any(cube["name"].startswith("pilot_") for cube in shell["cubes"])
        )
        self.assertNotIn("pilot_leg_chains", shell["generation"])
        self.assertNotIn("pilot_exoframe_contacts", shell["generation"])
        self.assertEqual(
            [0, 0, 0],
            shell["generation"]["wearable_export"]["player_anchor_after_fit"],
        )
        self.assertEqual(168, len(shell["cubes"]))
        self.assertEqual(21, len(shell["bones"]))

    def test_reference_texture_transfer_is_bounded_minecraft_pixel_art(self) -> None:
        """Require source-guided pixel art and solid fallback without speckle."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        transfer = spec["generation"]["texture_transfer"]
        coverage = transfer["coverage"]
        self.assertFalse(spec["texture"]["quantize_source"])
        self.assertEqual(1, spec["texture"]["density"])
        self.assertEqual(1024, transfer["texture"]["resolved_atlas_size"])
        self.assertTrue(transfer["palette_quantization"])
        self.assertEqual("minecraft", transfer["style"]["name"])
        self.assertFalse(transfer["style"]["dithering"])
        self.assertLessEqual(len(transfer["style"]["actual_palette"]), 24)
        self.assertGreaterEqual(coverage["source_fraction"], 0.20)
        self.assertGreaterEqual(coverage["faces_with_source"], 480)
        self.assertEqual(3, len(transfer["views"]))
        self.assertEqual(
            [],
            [
                name
                for name, material in spec["materials"].items()
                if material["pattern"] == "dither"
            ],
        )

    def test_articulation_contacts_and_grounding_are_physical(self) -> None:
        """Gate the link tree, two shield contacts, and nested boot interfaces."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        generation = spec["generation"]
        links = [
            (record["first"], record["second"], record["joint"])
            for record in generation["declared_attachments"]
        ]
        names = {cube["name"] for cube in spec["cubes"]}
        linked_children = {second for _, second, _ in links}
        structural = semantic_geometry.audit_attachments(spec, links)

        self.assertEqual(len(spec["cubes"]) - 1, len(links))
        self.assertEqual({"pelvis_frame_core"}, names - linked_children)
        self.assertTrue(structural["all_connected"])
        self.assertGreaterEqual(structural["minimum_margin"], 0)

        for field in ("shield_contacts", "pilot_exoframe_contacts"):
            contacts = [
                (record["first"], record["second"], record["joint"])
                for record in generation[field]
            ]
            audit = semantic_geometry.audit_attachments(spec, contacts)
            self.assertEqual(2, len(contacts))
            self.assertTrue(audit["all_connected"])

        self.assertEqual(2, len(generation["exo_leg_chains"]))
        self.assertEqual({"left", "right"}, {record["side"] for record in generation["exo_leg_chains"]})
        self.assertTrue(all(record["ground_minimum_y"] == 0.0 for record in generation["exo_leg_chains"]))

    def test_fixed_camera_multiview_evidence_and_identity_gates_pass(self) -> None:
        """Gate all three raw frames and the critical component inventory."""
        report = json.loads((CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8"))

        self.assertEqual(3, len(report["perspective_source_evidence"]))
        self.assertTrue(report["all_perspective_aspirations_pass"])
        iou_targets = {"source-6": 0.50, "source-7": 0.45, "source-8": 0.50}
        for source_name, evidence in report["perspective_source_evidence"].items():
            self.assertEqual("fixed-camera-perspective-evidence-v1", evidence["method"], source_name)
            self.assertEqual(
                "raw source pixels; no automatic fitting or recentering",
                evidence["alignment"],
                source_name,
            )
            self.assertTrue(evidence["camera_parameters_are_estimated"], source_name)
            self.assertFalse(evidence["visual_hull_used"], source_name)
            self.assertFalse(evidence["hidden_geometry_established"], source_name)
            self.assertGreaterEqual(
                evidence["silhouette"]["iou"], iou_targets[source_name], source_name
            )
            self.assertLessEqual(
                evidence["keypoints"]["mean_error_subject_heights"], 0.09, source_name
            )
        self.assertTrue(report["declared_link_tree_covers_every_cube"])
        self.assertTrue(report["all_two_shield_contacts_touch"])
        self.assertTrue(report["both_pilot_boots_retained_in_exoframe"])
        self.assertTrue(report["both_exo_feet_grounded"])
        self.assertTrue(report["recorded_feature_inventory_matches"])
        inventory = report["feature_inventory"]
        self.assertEqual(4, inventory["thermal_weapon_grille_bays"])
        self.assertEqual(5, inventory["thermal_weapon_heat_tubes"])
        self.assertEqual(6, inventory["knee_tread_guard_cuboids"])
        self.assertEqual(12, inventory["shield_grille_ribs"])
        self.assertGreaterEqual(
            report["leg_nesting_audit"]["minimum_knee_centerline_x_separation"], 10.0
        )
        self.assertGreaterEqual(
            report["leg_nesting_audit"]["minimum_ankle_centerline_x_separation"], 6.0
        )
        self.assertTrue(report["leg_nesting_audit"]["materials_are_distinct"])
        self.assertTrue(
            report["powered_leg_mass_audit"]["both_powered_chains_are_massive"]
        )
        for record in report["powered_leg_mass_audit"]["sides"].values():
            self.assertTrue(record["massive_powered_chain"])

        cubes = {
            cube["name"]: cube
            for cube in json.loads(
                (CYCLE / "model-spec.json").read_text(encoding="utf-8")
            )["cubes"]
        }
        self.assertEqual([60.0, 17.0, 16.0], cubes["thermal_weapon_core"]["size"])
        self.assertEqual(4.2, cubes["shield_core"]["size"][0])
        for side in ("left", "right"):
            self.assertGreaterEqual(
                min(cubes[f"{side}_exo_hip_block"]["size"]), 11.0
            )
            self.assertGreaterEqual(
                min(cubes[f"{side}_exo_knee_core"]["size"]), 10.0
            )
            self.assertGreaterEqual(
                cubes[f"{side}_exo_ground_foot"]["size"][0], 16.0
            )

    def test_reference_contract_and_native_artifacts_exist(self) -> None:
        """Require exact input hashes, review views, and Blockbench outputs."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        entry = next(
            asset
            for asset in json.loads(
                (ROOT / "benchmarks" / "round2" / "references.json").read_text(encoding="utf-8")
            )["assets"]
            if asset["id"] == "centaur_exoskeleton"
        )
        self.assertEqual(entry["sha256"][0], spec["reference"]["sha256"])
        for filename, expected_hash in zip(entry["sources"], entry["sha256"]):
            local_reference = ROOT / filename
            if local_reference.is_file():
                self.assertEqual(expected_hash, hashlib.sha256(local_reference.read_bytes()).hexdigest())

        evaluation = json.loads((CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8"))
        for relative in evaluation["views"] + evaluation["evidence_files"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            minimum_size = 200 if path.suffix == ".json" else 1000
            self.assertGreater(path.stat().st_size, minimum_size, relative)

        audit = json.loads(
            (CYCLE / "build" / "militech_centaur_piloted_exoskeleton.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        for relative in (
            "militech_centaur_piloted_exoskeleton.bbmodel",
            "militech_centaur_piloted_exoskeleton.geo.json",
            "militech_centaur_piloted_exoskeleton.manifest.json",
            "militech_centaur_piloted_exoskeleton.model-spec.json",
            "militech_centaur_piloted_exoskeleton.png",
            "militech_centaur_piloted_exoskeleton_wearable.bbmodel",
            "militech_centaur_piloted_exoskeleton_wearable.geo.json",
            "militech_centaur_piloted_exoskeleton_wearable.attachable.json",
            "militech_centaur_piloted_exoskeleton_wearable.model-spec.json",
            "militech_centaur_piloted_exoskeleton_wearable.png",
            "militech_centaur_piloted_exoskeleton_wearable.audit.json",
        ):
            self.assertTrue((CYCLE / "build" / relative).is_file(), relative)
        if all((ROOT / filename).is_file() for filename in entry["sources"]):
            self.assertTrue((CYCLE / "build" / "militech_centaur_piloted_exoskeleton.zip").is_file())


if __name__ == "__main__":
    unittest.main()
