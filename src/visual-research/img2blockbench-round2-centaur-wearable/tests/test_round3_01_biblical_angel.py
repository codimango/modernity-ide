"""Regression gates for the Round 3 holistic biblical angel benchmark."""

from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from pathlib import Path

from PIL import Image

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round3" / "cycles" / "01-biblical-angel"
MODEL_ID = "biblical_angel_many_eyed_six_wing"


class RoundThreeBiblicalAngelTests(unittest.TestCase):
    """Require a many-eyed six-wing asset that remains readable from every axis."""

    def test_semantic_inventory_and_strict_contract(self) -> None:
        """Gate the actual identity geometry instead of accepting a front relief."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        inventory = spec["generation"]["feature_inventory"]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual(MODEL_ID, spec["id"])
        self.assertEqual("agent-authored-holistic-semantic-volume", spec["generation"]["lane"])
        self.assertFalse(spec["generation"]["source_projection"])
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertEqual(189, len(spec["cubes"]))
        self.assertEqual(6, inventory["bilateral_wings"])
        self.assertEqual(3, inventory["wing_layers"])
        self.assertEqual(18, inventory["primary_feathers"])
        self.assertEqual(54, inventory["feather_segments"])
        self.assertEqual(12, inventory["broad_overlap_vanes"])
        self.assertEqual(36, inventory["broad_overlap_vane_segments"])
        self.assertEqual(21, inventory["total_geometric_eyes"])
        self.assertEqual(7, inventory["front_crown_eyes"])
        self.assertEqual(5, inventory["back_crown_eyes"])
        self.assertEqual(2, inventory["side_eyes"])
        self.assertEqual(1, inventory["top_eyes"])
        self.assertEqual(6, inventory["wing_eyes"])
        self.assertEqual(8, len(spec["generation"]["eye_crown"]["segments"]))
        self.assertIn("bottom", spec["quality_contract"]["required_views"])
        cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
        profiles = [
            profile
            for wing in spec["generation"]["wing_records"]
            for key in ("feather_profiles", "overlap_vane_profiles")
            for profile in wing[key]
        ]
        self.assertEqual(30, len(profiles))
        for profile in profiles:
            self.assertEqual(3, len(profile["segments"]))
            self.assertEqual(
                profile["widths"],
                [cube_by_name[name]["size"][0] for name in profile["segments"]],
            )
            self.assertEqual(
                profile["depths"],
                [cube_by_name[name]["size"][1] for name in profile["segments"]],
            )

    def test_attachment_tree_is_compiled_geometry_connected(self) -> None:
        """Require every feather, wing spar, eye, and body shell to touch its parent."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        audit = semantic_geometry.audit_attachments(spec, links)
        names = {cube["name"] for cube in spec["cubes"]}

        self.assertEqual(len(spec["cubes"]) - 1, len(links))
        self.assertEqual(names, {name for first, second, _ in links for name in (first, second)})
        self.assertTrue(audit["all_connected"])
        self.assertGreaterEqual(audit["minimum_margin"], 0)

    def test_explicit_anti_pancake_and_view_diversity_gates_pass(self) -> None:
        """Gate depth, side coverage, depth-band occupancy, and axial eye surfaces."""
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        proportions = report["proportions"]

        self.assertTrue(report["all_view_diversity_gates_pass"])
        self.assertTrue(all(report["view_diversity_gates"].values()))
        self.assertGreaterEqual(proportions["depth_to_width"], 0.40)
        self.assertGreaterEqual(proportions["body_depth_to_width"], 0.85)
        self.assertEqual([-14.0, 7.5, 16.0], proportions["wing_depth_centers"])
        self.assertGreaterEqual(proportions["wing_depth_span"], 30.0)
        for side in ("left", "right"):
            self.assertGreaterEqual(
                proportions["side_to_front_silhouette_area"][side], 0.60
            )
            self.assertGreaterEqual(
                proportions["side_to_front_bbox_width"][side], 0.50
            )
        self.assertTrue(all(value >= 20 for value in report["depth_occupancy"].values()))
        self.assertGreaterEqual(report["eye_orientations"]["south"], 7)
        self.assertGreaterEqual(report["eye_orientations"]["north"], 5)
        self.assertEqual(1, report["eye_orientations"]["west"])
        self.assertEqual(1, report["eye_orientations"]["east"])
        self.assertEqual(1, report["eye_orientations"]["up"])
        self.assertEqual(len(report["views"]), len(set(report["render_sha256"].values())))
        self.assertGreaterEqual(
            proportions["axis_to_front_silhouette_area"]["bottom"], 0.55
        )
        self.assertTrue(report["declared_link_tree_covers_every_cube"])
        self.assertGreaterEqual(
            proportions["axis_to_front_silhouette_area"]["back"], 0.90
        )
        self.assertGreaterEqual(
            proportions["axis_to_front_silhouette_area"]["top"], 0.70
        )
        self.assertEqual(1.0, report["wing_yaw"]["nonzero_yaw_fraction"])
        self.assertEqual(108, report["wing_yaw"]["nonzero_yaw_cuboids"])
        self.assertEqual([42.70939], report["wing_yaw"]["sector_sweeps_degrees"]["rear_upper"])
        self.assertEqual([21.037511], report["wing_yaw"]["sector_sweeps_degrees"]["middle"])
        self.assertEqual([40.100908], report["wing_yaw"]["sector_sweeps_degrees"]["front_lower"])
        self.assertTrue(report["distal_taper"]["all_profiles_have_three_segments"])
        self.assertTrue(report["distal_taper"]["all_widths_strictly_decrease"])
        self.assertTrue(report["distal_taper"]["all_depths_strictly_decrease"])
        self.assertLessEqual(report["distal_taper"]["maximum_terminal_width"], 1.4)
        self.assertLessEqual(report["distal_taper"]["maximum_terminal_depth"], 1.0)
        self.assertGreaterEqual(report["distal_taper"]["distinct_terminal_lengths"], 6)
        self.assertEqual(8, report["eye_crown"]["segment_count"])
        self.assertEqual(4, report["eye_crown"]["angled_corner_segments"])

    def test_texture_is_minecraft_native_and_noise_free(self) -> None:
        """Require a restrained authored atlas rather than copied or generated noise."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        self.assertEqual(1, spec["texture"]["density"])
        self.assertEqual(1024, spec["texture"]["atlas_size"])
        self.assertFalse(spec["texture"]["quantize_source"])
        self.assertTrue(
            all(material["pattern"] == "solid" for material in spec["materials"].values())
        )
        self.assertEqual(
            {"#e8ddd5", "#f5eee7", "#c6b7b7", "#c58e88", "#8e5656", "#8c443f",
             "#f1ede7", "#d5c7c2", "#63c1c8", "#2c7782", "#17232a", "#d6b67c"},
            {material["base"] for material in spec["materials"].values()},
        )
        atlas, _ = img2blockbench.build_texture(spec)
        self.assertEqual((1024, 1024), atlas.size)

    def test_private_reference_contract_and_native_artifacts(self) -> None:
        """Require exact ignored-input provenance and native Blockbench products."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        provenance = json.loads((CYCLE / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["input"]["sha256"], spec["reference"]["sha256"])
        self.assertFalse(provenance["input"]["tracked"])
        self.assertFalse(provenance["contextual_research"]["asset_identity_match"])
        self.assertFalse(provenance["contextual_research"]["geometry_measurement_used"])
        reference = ROOT / "round3-inputs" / "biblically-accurate-angel.png"
        if reference.is_file():
            self.assertEqual(
                spec["reference"]["sha256"], hashlib.sha256(reference.read_bytes()).hexdigest()
            )

        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        hashes = json.loads(
            (CYCLE / "render" / "render-hashes.json").read_text(encoding="utf-8")
        )
        self.assertTrue(hashes["model_only"])
        self.assertEqual("sha256", hashes["algorithm"])
        self.assertEqual(report["render_sha256"], hashes["required_renders"])
        self.assertEqual(set(report["views"]), set(report["render_sha256"]))
        self.assertIn("bottom.png", report["views"])
        self.assertIn("all-angle-sheet.png", report["views"])
        self.assertNotIn("comparison-sheet.png", report["views"])
        for relative in report["views"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 1000, relative)
            self.assertEqual(
                report["render_sha256"][relative],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            with Image.open(path) as opened:
                self.assertGreaterEqual(
                    opened.width, 1200 if relative == "all-angle-sheet.png" else 640
                )
        self.assertFalse((CYCLE / "render" / "comparison-sheet.png").exists())
        self.assertTrue(report["local_source_comparison_is_ignored"])

        build = CYCLE / "build"
        audit = json.loads((build / f"{MODEL_ID}.audit.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        self.assertEqual(189, audit["cuboids"])
        for suffix in ("bbmodel", "geo.json", "manifest.json", "model-spec.json", "png"):
            self.assertTrue((build / f"{MODEL_ID}.{suffix}").is_file(), suffix)
        manifest = json.loads(
            (build / f"{MODEL_ID}.manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["reference"]["bundled"])
        self.assertEqual("private-optional", manifest["reference"]["availability"])
        self.assertFalse(manifest["reference"]["required_for_model_use"])
        self.assertEqual(1, len(manifest["private_optional_artifacts"]))
        self.assertFalse(manifest["private_optional_artifacts"][0]["bundled"])
        self.assertFalse(
            any(record["path"].endswith(".reference.png") for record in manifest["artifacts"])
        )
        for record in manifest["artifacts"]:
            path = build / record["path"]
            self.assertTrue(path.is_file(), record["path"])
            self.assertEqual(record["bytes"], path.stat().st_size)
            self.assertEqual(record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        if reference.is_file():
            delivery_spec = json.loads(
                (build / f"{MODEL_ID}.model-spec.json").read_text(encoding="utf-8")
            )
            self.assertEqual([], img2blockbench.validate_spec(delivery_spec, strict=True))
            self.assertFalse(delivery_spec["reference"]["bundled"])
            self.assertEqual(
                "private-optional", delivery_spec["reference"]["availability"]
            )
        self.assertFalse((build / f"{MODEL_ID}.reference.png").exists())
        archive = build / f"{MODEL_ID}.zip"
        if archive.is_file():
            with zipfile.ZipFile(archive) as opened:
                self.assertFalse(
                    any(name.endswith(".reference.png") for name in opened.namelist())
                )


if __name__ == "__main__":
    unittest.main()
