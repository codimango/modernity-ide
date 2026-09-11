"""Regression gates for the Round 3 Atlus holistic-vehicle benchmark."""

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
CYCLE = ROOT / "benchmarks" / "round3" / "cycles" / "02-atlus"
REFERENCE = ROOT / "round3-inputs" / "atlus.png"
MULTIVIEW = ROOT / "round3-inputs" / "atlus-multiview"
EXPECTED_REFERENCES = {
    "front-quarter": "12c3c09ae7ba0c10efe46411c57a13f1477b695923e05475ce34b07c6ca7e967",
    "front": "7bb5a2aebb27c2c4d42343f0ef3b19f993733a596b7187576d22d2623227daa4",
    "side": "c47b04501de8a59322ae03d6bfb8d2302e5f474f58a3f022bb5cfa22818c0d98",
    "rear": "6454b749f851f58f77b3d670683855cb020c18d6e61b2642a47b24fb37b2d83d",
    "top": "a4a01fa0d23029f3299e493428db8c737fddca533e66e221f464eb10be79a4f0",
}
PRESERVED_NATIVE_HASHES = {
    "atlus_trauma_team_aerodyne.bbmodel": "d6167ec4e99fac88bf1734612bcc643cf4ffd018632822164496391ab78022cd",
    "atlus_trauma_team_aerodyne.geo.json": "e1ddda87b4b05d89682643ebab3639c130abdd3af42270c34f489c5843a647b6",
    "atlus_trauma_team_aerodyne.png": "a15ce4edcbab67d4a791b06066808832673155de6f5891eee12ef6f8265c427d",
    "atlus_trauma_team_aerodyne.audit.json": (
        "2aa86b67819b8d55e10210e312723d7d45b03ed99e7012e0139f55a76ed83fea"
    ),
}


class RoundThreeAtlusTests(unittest.TestCase):
    """Require a deep, all-angle Trauma Team vehicle instead of a relief."""

    def test_atlus_is_native_semantic_and_multi_axis(self) -> None:
        """Gate native volume, semantic inventory, clean materials, and markings."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = {cube["name"] for cube in spec["cubes"]}
        inventory = spec["generation"]["feature_inventory"]

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("atlus_trauma_team_aerodyne", spec["id"])
        self.assertEqual("agent-authored-holistic-semantic-volume", spec["generation"]["lane"])
        self.assertEqual("multi-axis-hard-surface-vehicle-v1", spec["generation"]["algorithm"])
        self.assertEqual(165, len(spec["cubes"]))
        self.assertEqual(9, len(spec["bones"]))
        self.assertEqual(28, len(spec["landmarks"]))
        self.assertFalse(spec["generation"]["source_projection"])
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertFalse(spec["generation"]["texture_contract"]["procedural_noise"])
        self.assertTrue(spec["generation"]["texture_contract"]["all_material_patterns_solid"])
        self.assertTrue(all(value["pattern"] == "solid" for value in spec["materials"].values()))
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )

        self.assertEqual(20, inventory["central_fuselage_cuboids"])
        self.assertEqual(22, inventory["left_side_pod_cuboids"])
        self.assertEqual(22, inventory["right_side_pod_cuboids"])
        self.assertEqual(4, inventory["landing_gear_modules"])
        self.assertEqual(20, inventory["landing_gear_cuboids"])
        self.assertEqual(6, inventory["rear_thruster_cuboids"])
        self.assertEqual(3, inventory["roof_aerials"])
        self.assertEqual(16, inventory["medical_marking_strokes"])
        self.assertEqual(8, inventory["under_nose_weapon_barrels"])
        self.assertEqual(8, inventory["under_nose_weapon_muzzles"])
        self.assertEqual(8, inventory["rear_pod_louvers"])
        self.assertEqual(6, inventory["ventral_machinery_cuboids"])
        self.assertGreaterEqual(inventory["side_detail_cuboids"], 80)
        for required in (
            "front_grille", "front_grille_louver_7", "left_outer_door",
            "right_outer_door", "left_rear_light_rail", "right_rear_light_rail",
            "left_front_hover_core", "right_rear_hover_core", "roof_medical_panel",
        ):
            self.assertIn(required, names)

        cross_faces = {
            mark["name"]: mark["face"]
            for mark in spec["landmarks"]
            if "cross" in mark["name"]
        }
        self.assertEqual("west", cross_faces["left_door_cross_vertical"])
        self.assertEqual("east", cross_faces["right_door_cross_vertical"])
        self.assertEqual("up", cross_faces["roof_cross_vertical"])
        self.assertEqual("north", cross_faces["rear_cross_vertical"])

    def test_atlus_uses_all_observed_exterior_directions(self) -> None:
        """Require exact front, side, rear, top, and quarter-view provenance."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        provenance = json.loads((CYCLE / "provenance.json").read_text(encoding="utf-8"))
        records = {record["view"]: record for record in spec["generation"]["geometry_references"]}
        provenance_records = {
            record["view"]: record for record in provenance["geometry_references"]
        }
        self.assertEqual(set(EXPECTED_REFERENCES), set(records))
        self.assertEqual(set(EXPECTED_REFERENCES), set(provenance_records))
        self.assertFalse(Path(spec["reference"]["image"]).is_absolute())
        self.assertEqual("../../../../round3-inputs/atlus.png", spec["reference"]["image"])
        self.assertEqual(
            "5458ba42d698b38ed2a0a3a55e17a4608a2a4579f3bcdfc22a9b3e7018c74a25",
            provenance["primary_reference"]["sha256"],
        )
        for view, expected_hash in EXPECTED_REFERENCES.items():
            path = MULTIVIEW / f"{view}.webp"
            self.assertEqual(expected_hash, records[view]["sha256"])
            self.assertEqual(expected_hash, provenance_records[view]["sha256"])
            self.assertEqual([1920, 1080], [records[view]["width"], records[view]["height"]])
            self.assertEqual("geometry-and-marking-evidence-only", records[view]["use"])
            if path.is_file():
                self.assertEqual(expected_hash, hashlib.sha256(path.read_bytes()).hexdigest())
        if REFERENCE.is_file():
            self.assertEqual(
                provenance["primary_reference"]["sha256"],
                hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
            )
        self.assertIn("underside", spec["generation"]["single_view_hidden_geometry"])

    def test_atlus_connections_and_holistic_evidence_pass(self) -> None:
        """Gate connected geometry, substantial depth, and directional distinction."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        self.assertEqual(46, len(links))
        attachment = semantic_geometry.audit_attachments(spec, links)
        self.assertTrue(attachment["all_connected"])
        self.assertGreater(attachment["minimum_margin"], 0)

        report = json.loads((CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8"))
        self.assertTrue(report["all_anti_pancake_gates_pass"])
        self.assertTrue(report["all_feature_gates_pass"])
        self.assertTrue(report["all_five_reference_direction_gates_pass"])
        self.assertFalse(report["camera_calibration_claimed"])
        self.assertFalse(report["hidden_geometry_established_by_source"])
        self.assertTrue(report["underside_inference_disclosed"])
        metrics = report["metrics"]
        self.assertGreaterEqual(metrics["overall_length_to_width"], 1.15)
        self.assertGreaterEqual(metrics["overall_width_to_height"], 1.35)
        self.assertGreaterEqual(metrics["central_hull_length_to_width"], 1.75)
        self.assertGreaterEqual(metrics["left_pod_length_fraction"], 0.65)
        self.assertGreaterEqual(metrics["right_pod_length_fraction"], 0.65)
        self.assertGreaterEqual(metrics["minimum_axis_to_maximum_axis"], 0.25)
        self.assertEqual([0.0, 0.0, 0.0, 0.0], metrics["shoe_ground_heights"])
        self.assertGreaterEqual(metrics["front_back_pixel_difference"], 0.02)
        self.assertGreaterEqual(metrics["top_underside_pixel_difference"], 0.02)
        for view in ("front", "back", "left", "right", "top", "isometric"):
            self.assertGreaterEqual(metrics["orthographic_silhouette_occupancy"][view], 0.12)
        directional = report["multiview_directional_evidence"]
        self.assertEqual(set(EXPECTED_REFERENCES), set(directional))
        self.assertTrue(all(record["gate"] for record in directional.values()))
        self.assertTrue(all(len(record["observed_anchors"]) >= 3 for record in directional.values()))

    def test_atlus_texture_is_bounded_and_noise_free(self) -> None:
        """Require the clean Minecraft panel palette requested by the user."""
        evidence = json.loads((CYCLE / "texture-evidence.json").read_text(encoding="utf-8"))
        atlas = Image.open(CYCLE / evidence["atlas"]).convert("RGBA")
        pixels = (
            atlas.get_flattened_data()
            if hasattr(atlas, "get_flattened_data")
            else atlas.getdata()
        )
        opaque = [pixel for pixel in pixels if pixel[3] > 0]
        palette = {"#%02x%02x%02x" % pixel[:3] for pixel in opaque}
        self.assertEqual(evidence["opaque_texels"], len(opaque))
        self.assertEqual(evidence["opaque_color_count"], len(palette))
        self.assertEqual(set(evidence["opaque_palette"]), palette)
        self.assertLessEqual(len(palette), evidence["palette_limit"])
        self.assertFalse(evidence["procedural_noise"])
        self.assertFalse(evidence["dithering"])
        self.assertFalse(evidence["source_pixels_embedded_verbatim"])
        self.assertTrue(evidence["bounded_minecraft_palette"])

    def test_atlus_native_build_and_every_review_view_exist(self) -> None:
        """Require Blockbench/Bedrock outputs and complete directional evidence."""
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        report = json.loads((CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8"))
        required = set(spec["quality_contract"]["required_views"])
        self.assertIn("underside", required)
        self.assertEqual(
            {f"{name}.png" for name in required},
            set(report["render_sha256"]) - {"all-angle-sheet.png"},
        )
        self.assertEqual(set(report["views"]), set(report["render_sha256"]))
        for relative in report["views"]:
            path = CYCLE / "render" / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 1000, relative)
            self.assertEqual(
                report["render_sha256"][relative],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        self.assertFalse((CYCLE / "render" / "comparison-sheet.png").exists())
        self.assertFalse((CYCLE / "render" / "multiview-comparison-sheet.png").exists())
        self.assertEqual(
            [
                "round3-inputs/local-review/02-atlus/user-source-comparison.png",
                "round3-inputs/local-review/02-atlus/multiview-source-comparison.png",
            ],
            report["ignored_local_source_review"],
        )

        audit = json.loads(
            (CYCLE / "build" / "atlus_trauma_team_aerodyne.audit.json").read_text(encoding="utf-8")
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        for relative in (
            "atlus_trauma_team_aerodyne.bbmodel",
            "atlus_trauma_team_aerodyne.geo.json",
            "atlus_trauma_team_aerodyne.png",
            "atlus_trauma_team_aerodyne.manifest.json",
            "atlus_trauma_team_aerodyne.model-spec.json",
        ):
            path = CYCLE / "build" / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 500, relative)

        manifest = json.loads(
            (CYCLE / "build" / "atlus_trauma_team_aerodyne.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(manifest["reference"]["bundled"])
        self.assertEqual("private-optional", manifest["reference"]["availability"])
        self.assertFalse(manifest["reference"]["required_for_model_use"])
        self.assertEqual(1, len(manifest["private_optional_artifacts"]))
        self.assertFalse(manifest["private_optional_artifacts"][0]["bundled"])
        self.assertFalse(
            any(record["path"].endswith(".reference.png") for record in manifest["artifacts"])
        )
        manifest_by_path = {record["path"]: record for record in manifest["artifacts"]}
        self.assertEqual(
            PRESERVED_NATIVE_HASHES,
            {
                path: manifest_by_path[path]["sha256"]
                for path in PRESERVED_NATIVE_HASHES
            },
        )
        for record in manifest["artifacts"]:
            artifact = CYCLE / "build" / record["path"]
            self.assertTrue(artifact.is_file(), record["path"])
            self.assertEqual(record["bytes"], artifact.stat().st_size)
            self.assertEqual(
                record["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest()
            )

        build = CYCLE / "build"
        delivery_spec = json.loads(
            (build / "atlus_trauma_team_aerodyne.model-spec.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(delivery_spec["reference"]["bundled"])
        self.assertEqual("private-optional", delivery_spec["reference"]["availability"])
        self.assertFalse(delivery_spec["reference"]["required_for_model_use"])
        self.assertFalse(Path(delivery_spec["reference"]["image"]).is_absolute())
        if REFERENCE.is_file():
            self.assertEqual([], img2blockbench.validate_spec(delivery_spec, strict=True))
        self.assertFalse((build / "atlus_trauma_team_aerodyne.reference.png").exists())
        archive = build / "atlus_trauma_team_aerodyne.zip"
        if archive.is_file():
            with zipfile.ZipFile(archive) as opened:
                names = set(opened.namelist())
                self.assertFalse(any(name.endswith(".reference.png") for name in names))
                self.assertTrue(
                    {record["path"] for record in manifest["artifacts"]} <= names
                )
                self.assertIn("atlus_trauma_team_aerodyne.manifest.json", names)

    def test_atlus_grade_is_exact_commit_and_artifacts_are_portable(self) -> None:
        """Record the independent exact-commit pass and portable artifacts."""
        grade = json.loads((CYCLE / "grade.json").read_text(encoding="utf-8"))
        self.assertEqual("PASS", grade["status"])
        self.assertEqual(
            "640b8e7fe4e1179d2ce58fc16c9bb9935e6f4feb", grade["graded_commit"]
        )
        self.assertEqual("pass", grade["exact_commit_grade"])
        self.assertEqual(
            {
                "decision": "pass",
                "silhouette": 3,
                "proportions": 3,
                "identity": 3,
                "materials_color": 4,
                "topology_attachments": 3,
                "holistic_3d_coherence": 4,
            },
            grade["independent_visual_grade"],
        )

        text_suffixes = {".json", ".md", ".py", ".ts", ".bbmodel"}
        for path in CYCLE.rglob("*"):
            if path.is_file() and path.suffix in text_suffixes:
                self.assertNotIn(
                    Path.home().as_posix(), path.read_text(encoding="utf-8"), str(path)
                )


if __name__ == "__main__":
    unittest.main()
