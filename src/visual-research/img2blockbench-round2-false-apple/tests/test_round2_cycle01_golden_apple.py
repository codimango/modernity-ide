import hashlib
import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
CYCLE = ROOT / "benchmarks" / "round2" / "cycles" / "01-golden-apple"


class RoundTwoCycleOneGoldenAppleTests(unittest.TestCase):
    def test_golden_apple_is_native_volumetric_and_connected(self):
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        names = {cube["name"] for cube in spec["cubes"]}
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual("golden_apple_rooted", spec["id"])
        self.assertEqual(155, len(spec["cubes"]))
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertFalse(spec["generation"]["source_projection"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )
        ellipsoid = spec["generation"]["ellipsoid"]
        self.assertEqual(3912, ellipsoid["base_occupied_voxels"])
        self.assertEqual(3530, ellipsoid["occupied_voxels"])
        self.assertEqual(382, ellipsoid["removed_voxels"])
        self.assertEqual(2, len(ellipsoid["cutouts"]))
        self.assertFalse(any(cube["material"] == "cut_shadow" for cube in spec["cubes"]))
        self.assertTrue(ellipsoid["dark_exposed_faces"])

        root_graphs = [
            graph
            for graph in spec["generation"]["branch_graphs"]
            if graph["name"].startswith("root_")
        ]
        self.assertEqual(4, len(root_graphs))
        quadrants = {
            (record["x_sign"], record["z_sign"])
            for record in spec["generation"]["root_quadrants"]
        }
        self.assertEqual({(-1, -1), (-1, 1), (1, -1), (1, 1)}, quadrants)

        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertEqual(len(spec["cubes"]) - 1, len(links))
        self.assertEqual(names, {name for link in links for name in link[:2]})
        self.assertTrue(report["all_connected"])
        self.assertGreaterEqual(report["minimum_margin"], 0)

    def test_golden_apple_evidence_passes_round_two_contract(self):
        report = json.loads(
            (CYCLE / "render" / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["source_iou_gate_at_least_0.70"])
        self.assertGreaterEqual(report["alpha_silhouette"]["iou"], 0.70)
        self.assertTrue(report["keypoint_mean_gate_at_most_0.05_subject_heights"])
        self.assertLessEqual(
            report["alpha_silhouette"]["keypoints"]["mean_error_subject_heights"],
            0.05,
        )
        self.assertTrue(report["apple_depth_width_gate_0.8_to_1.1"])
        self.assertTrue(report["four_roots_in_four_xz_quadrants"])
        self.assertTrue(report["attachments"]["all_connected"])
        self.assertTrue(report["declared_link_tree_covers_every_cube"])
        self.assertTrue(report["recorded_feature_inventory_matches"])
        self.assertEqual(382, report["negative_space"]["removed_voxels"])
        self.assertEqual(0, report["negative_space"]["black_proxy_solids"])
        self.assertTrue(
            report["negative_space"]["cutout_is_empty_geometry_not_a_black_proxy"]
        )
        clipping = report["reference_frame_clipping"]
        self.assertTrue(clipping["iou_cannot_establish_off_frame_continuation"])
        self.assertEqual(["left", "right", "bottom"], clipping["declared_edges"])

    def test_reference_contract_and_required_artifacts_exist(self):
        spec = json.loads((CYCLE / "model-spec.json").read_text(encoding="utf-8"))
        reference_entry = next(
            asset
            for asset in json.loads(
                (ROOT / "benchmarks" / "round2" / "references.json").read_text(
                    encoding="utf-8"
                )
            )["assets"]
            if asset["id"] == "golden_apple"
        )
        self.assertEqual(reference_entry["sha256"], spec["reference"]["sha256"])
        self.assertEqual([600, 704], [spec["reference"]["width"], spec["reference"]["height"]])
        local_reference = ROOT / "image-1.png"
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
            (CYCLE / "build" / "golden_apple_rooted.audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(audit["ok"])
        self.assertEqual([], audit["errors"])
        for suffix in ("bbmodel", "geo.json", "png"):
            self.assertTrue((CYCLE / "build" / f"golden_apple_rooted.{suffix}").is_file())
        # The bundle embeds the private reference and is intentionally ignored.
        # Require it whenever that local-only reference is available, while
        # keeping a clean checkout reproducibly testable.
        if (ROOT / "image-1.png").is_file():
            self.assertTrue(
                (CYCLE / "build" / "golden_apple_rooted.zip").is_file()
            )


if __name__ == "__main__":
    unittest.main()
