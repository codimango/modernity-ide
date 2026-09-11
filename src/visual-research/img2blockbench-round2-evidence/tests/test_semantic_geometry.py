import hashlib
import math
import tempfile
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry
from PIL import Image
from photo_reconstruction import _rotate_point


class SemanticGeometryTests(unittest.TestCase):
    def test_segment_rotation_reaches_arbitrary_endpoint(self):
        start = (2.5, 7.0, -3.0)
        end = (-4.0, 1.5, 6.25)
        cube = semantic_geometry.segment_cube(
            "limb",
            "limb",
            start,
            end,
            1.25,
            "articulated limb",
            "skin",
            overlap=0.4,
        )
        length = math.dist(start, end)
        rotated_end = _rotate_point(
            (start[0], start[1] + length, start[2]),
            start,
            tuple(cube["rotation"]),
        )
        for actual, expected in zip(rotated_end, end):
            self.assertAlmostEqual(expected, actual, places=5)
        self.assertEqual(start, tuple(cube["origin"]))
        self.assertAlmostEqual(length + 0.8, cube["size"][1], places=5)
        self.assertAlmostEqual(
            0.4, semantic_geometry.point_to_cuboid_margin(cube, start), places=5
        )
        self.assertAlmostEqual(
            0.4, semantic_geometry.point_to_cuboid_margin(cube, end), places=5
        )

    def test_normal_rotation_aims_local_front_at_direction(self):
        direction = (3.0, -2.0, 5.0)
        length = math.sqrt(sum(value * value for value in direction))
        expected = tuple(value / length for value in direction)
        rotation = semantic_geometry.normal_rotation(direction)
        actual = _rotate_point((0, 0, 1), (0, 0, 0), tuple(rotation))
        for value, target in zip(actual, expected):
            self.assertAlmostEqual(target, value, places=5)

    def test_flat_blade_segment_uses_local_z_as_long_axis(self):
        start = (1.0, 4.0, -2.0)
        end = (7.0, 5.5, 3.0)
        cube = semantic_geometry.segment_cube(
            "leaf",
            "leaf",
            start,
            end,
            (2.0, 0.4),
            "flat leaf",
            "green",
            overlap=0.3,
            longitudinal_axis="z",
        )
        length = math.dist(start, end)
        rotated_end = _rotate_point(
            (start[0], start[1], start[2] + length),
            start,
            tuple(cube["rotation"]),
        )
        for actual, expected in zip(rotated_end, end):
            self.assertAlmostEqual(expected, actual, places=5)
        self.assertAlmostEqual(0.4, cube["size"][1])
        self.assertAlmostEqual(length + 0.6, cube["size"][2], places=5)

    def test_ellipsoid_voxels_merge_exactly_and_deterministically(self):
        first = semantic_geometry.ellipsoid_cuboids(
            "globe",
            "body",
            (1, 8, -2),
            (6, 7, 5),
            (10, 10, 10),
            "rounded body",
            "red",
            max_cuboids=64,
        )
        second = semantic_geometry.ellipsoid_cuboids(
            "globe",
            "body",
            (1, 8, -2),
            (6, 7, 5),
            (10, 10, 10),
            "rounded body",
            "red",
            max_cuboids=64,
        )
        self.assertEqual(first, second)
        self.assertLess(len(first.cubes), first.occupied_voxels)
        voxel_volume = math.prod(first.voxel_size)
        merged_volume = sum(math.prod(cube["size"]) for cube in first.cubes)
        self.assertAlmostEqual(
            first.occupied_voxels * voxel_volume, merged_volume, places=4
        )
        self.assertEqual(
            list(range(1, len(first.cubes) + 1)),
            [int(cube["name"].rsplit("_", 1)[1]) for cube in first.cubes],
        )

    def test_ellipsoid_budget_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "reduce subdivisions"):
            semantic_geometry.ellipsoid_cuboids(
                "globe",
                "body",
                (0, 0, 0),
                (5, 5, 5),
                (12, 12, 12),
                "rounded body",
                "red",
                max_cuboids=10,
            )

    def test_superellipsoid_roundness_is_exact_and_budgeted(self):
        result = semantic_geometry.ellipsoid_cuboids(
            "tomato",
            "body",
            (0, 0, 0),
            (13, 12.5, 12.5),
            (14, 14, 14),
            "organic globe",
            "red",
            max_cuboids=64,
            exponent=2.4,
        )
        self.assertEqual(1712, result.occupied_voxels)
        self.assertEqual(57, len(result.cubes))
        self.assertTrue(
            any(
                semantic_geometry.point_to_cuboid_margin(
                    cube, (8.0, 0.0, 8.0)
                )
                >= 0
                for cube in result.cubes
            )
        )
        with self.assertRaisesRegex(ValueError, "exponent"):
            semantic_geometry.ellipsoid_cuboids(
                "bad",
                "body",
                (0, 0, 0),
                (1, 1, 1),
                (4, 4, 4),
                "bad",
                "red",
                exponent=math.nan,
            )

    def test_radial_polyline_is_cumulative_in_requested_plane(self):
        points = semantic_geometry.radial_polyline(
            (1, 9, 2),
            90,
            ((4, -3), (2, -5), (-1, 0)),
        )
        expected = ((1, 9, 2), (1, 6, 6), (1, 1, 8), (1, 1, 7))
        for actual_point, expected_point in zip(points, expected):
            for actual, value in zip(actual_point, expected_point):
                self.assertAlmostEqual(value, actual, places=5)

    def test_radial_profile_is_mirrored_at_half_turn(self):
        profile = ((0, 2, 3), (1, -1, 7), (-2, -5, 9))
        first = semantic_geometry.transform_radial_profile((0, 10, 0), 0, profile)
        opposite = semantic_geometry.transform_radial_profile((0, 10, 0), 180, profile)
        for left, right in zip(first, opposite):
            self.assertAlmostEqual(left[0], -right[0], places=5)
            self.assertAlmostEqual(left[1], right[1], places=5)
            self.assertAlmostEqual(left[2], -right[2], places=5)

    def test_builder_emits_parented_connected_chain(self):
        builder = semantic_geometry.SemanticModelBuilder()
        builder.add_bone("body", "root", (0, 8, 0))
        result = builder.add_chain(
            "left_leg",
            "body",
            ((-2, 7, 0), (-4, 4, 1), (-5, 0, 3)),
            (1.5, 1.0),
            ("skin", "skin_dark"),
            "left leg",
            overlap=0.5,
            depths=(0.8, 0.6),
        )
        self.assertEqual(("left_leg_1", "left_leg_2"), result.bones)
        self.assertEqual("body", builder.bones[-2]["parent"])
        self.assertEqual("left_leg_1", builder.bones[-1]["parent"])
        self.assertEqual([1.5, 1.0], [cube["size"][0] for cube in builder.cubes])
        self.assertEqual([0.8, 0.6], [cube["size"][2] for cube in builder.cubes])
        audit = semantic_geometry.audit_attachments(builder.cubes, result.attachments)
        self.assertTrue(audit["all_connected"])
        self.assertGreater(audit["minimum_margin"], 0)
        compiled_audit = semantic_geometry.audit_attachments(
            {
                "geometry": {"precision": 16},
                "texture": {"density": 1},
                "cubes": builder.cubes,
            },
            result.attachments,
        )
        self.assertTrue(compiled_audit["all_connected"])
        self.assertIn("compiled", compiled_audit["method"])

        detached = [dict(cube) for cube in builder.cubes]
        detached[1] = dict(detached[1], center=[12, 12, 12], origin=[12, 12, 12])
        failed = semantic_geometry.audit_attachments(detached, result.attachments)
        self.assertFalse(failed["all_connected"])

    def test_builder_output_passes_strict_model_validation(self):
        builder = semantic_geometry.SemanticModelBuilder()
        builder.add_bone("body", "root", (0, 3, 0))
        builder.add_chain(
            "antenna",
            "body",
            ((0, 3, 0), (1, 5, 1)),
            1,
            "skin",
            "antenna",
        )
        spec = {
            "schema_version": 1,
            "id": "semantic_chain",
            "reference": {
                "image": "reference.png",
                "sha256": "0" * 64,
                "width": 16,
                "height": 16,
            },
            "subject": {
                "type": "mob",
                "description": "Synthetic articulated chain",
                "symmetry": "none",
                "uncertainties": ["none identified"],
            },
            "quality_contract": {
                "complexity": "simple",
                "target_cuboids": [1, 1],
                "identity_features": ["connected antenna"],
                "required_views": ["front"],
                "review_targets": ["attachment"],
            },
            "texture": {
                "density": 1,
                "palette_size": 4,
                "gutter": 1,
                "atlas_size": 32,
            },
            "materials": {
                "skin": {
                    "base": "#aa5533",
                    "shade": "#663322",
                    "highlight": "#dd8866",
                    "pattern": "solid",
                    "pattern_scale": 1,
                }
            },
            "bones": builder.bones,
            "cubes": builder.cubes,
            "landmarks": [],
            "collision": {"width": 1.0, "height": 1.0, "eye_height": 0.8},
        }
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            reference = folder / "reference.png"
            Image.new("RGB", (16, 16), "#aa5533").save(reference)
            spec["reference"]["sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
            spec_path = folder / "spec.json"
            img2blockbench.write_json(spec_path, spec)
            img2blockbench.build_model(spec_path, folder / "first")
            img2blockbench.build_model(spec_path, folder / "second")
            self.assertEqual(
                img2blockbench.read_json(folder / "first" / "semantic_chain.bbmodel"),
                img2blockbench.read_json(folder / "second" / "semantic_chain.bbmodel"),
            )
            self.assertEqual(
                (folder / "first" / "semantic_chain.zip").read_bytes(),
                (folder / "second" / "semantic_chain.zip").read_bytes(),
            )

    def test_builder_rejects_duplicates_and_degenerate_segments(self):
        builder = semantic_geometry.SemanticModelBuilder()
        builder.add_bone("body", "root", (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "duplicate bone"):
            builder.add_bone("body", "root", (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "distinct"):
            semantic_geometry.segment_cube(
                "bad", "body", (0, 0, 0), (0, 0, 0), 1, "bad", "skin"
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            semantic_geometry.segment_cube(
                "bad", "body", (0, 0, 0), (0, 1, 0), math.inf, "bad", "skin"
            )
        with self.assertRaisesRegex(ValueError, "tolerance"):
            semantic_geometry.audit_attachments([], [], tolerance=math.inf)
        duplicate = semantic_geometry.segment_cube(
            "same", "body", (0, 0, 0), (0, 2, 0), 1, "same", "skin"
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            semantic_geometry.audit_attachments([duplicate, duplicate], [])

    def test_failed_chain_is_atomic(self):
        builder = semantic_geometry.SemanticModelBuilder()
        builder.add_bone("body", "root", (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "distinct"):
            builder.add_chain(
                "bad",
                "body",
                ((0, 0, 0), (0, 2, 0), (0, 2, 0)),
                1,
                "skin",
                "bad chain",
            )
        self.assertEqual(["root", "body"], [bone["name"] for bone in builder.bones])
        self.assertEqual([], builder.cubes)
        with self.assertRaisesRegex(ValueError, "overlap"):
            builder.add_chain(
                "also_bad",
                "body",
                ((0, 0, 0), (0, 2, 0)),
                1,
                "skin",
                "bad overlap",
                overlap=math.nan,
            )
        self.assertEqual(["root", "body"], [bone["name"] for bone in builder.bones])
        self.assertEqual([], builder.cubes)

    def test_branch_graph_tapers_parents_and_manifests_shared_joint(self):
        builder = semantic_geometry.SemanticModelBuilder()
        builder.add_bone("body", "root", (0, 4, 0))
        builder.add_cube(
            semantic_geometry.segment_cube(
                "body_core", "body", (0, 3, 0), (0, 5, 0), 2, "body", "dark"
            )
        )
        nodes = (
            semantic_geometry.BranchNode("root_joint", (0, 4, 0)),
            semantic_geometry.BranchNode("fork", (0, 8, 1)),
            semantic_geometry.BranchNode("left_tip", (-4, 11, 2)),
            semantic_geometry.BranchNode("right_tip", (4, 10, -1)),
        )
        edges = (
            semantic_geometry.BranchEdge(
                "trunk", "root_joint", "fork", 2.4, 1.6, "dark", "trunk", 2
            ),
            semantic_geometry.BranchEdge(
                "left", "fork", "left_tip", 1.5, 0.45, "red", "left tine", 3
            ),
            semantic_geometry.BranchEdge(
                "right", "fork", "right_tip", 1.5, 0.35, "red", "right tine", 3
            ),
        )
        result = builder.add_branch_graph(
            "crown",
            "body",
            "root_joint",
            nodes,
            edges,
            overlap=0.3,
            parent_cube="body_core",
        )
        self.assertEqual(8, len(result.cubes))
        self.assertEqual(
            "crown_trunk_2",
            next(bone for bone in builder.bones if bone["name"] == "crown_left_1")["parent"],
        )
        self.assertEqual(
            "crown_trunk_2",
            next(bone for bone in builder.bones if bone["name"] == "crown_right_1")["parent"],
        )
        left_widths = [
            next(cube for cube in builder.cubes if cube["name"] == f"crown_left_{index}")[
                "size"
            ][0]
            for index in range(1, 4)
        ]
        self.assertGreater(left_widths[0], left_widths[1])
        self.assertGreater(left_widths[1], left_widths[2])
        self.assertTrue(
            semantic_geometry.audit_attachments(builder.cubes, result.attachments)[
                "all_connected"
            ]
        )
        self.assertEqual(8, len(result.manifest["attachments"]))
        self.assertEqual(
            ["left", "right", "trunk"],
            sorted(edge["name"] for edge in result.manifest["edges"]),
        )
        final_cube = next(
            cube for cube in builder.cubes if cube["name"] == "crown_left_3"
        )
        final_origin = tuple(final_cube["origin"])
        authored_length = math.dist(final_origin, (-4, 11, 2))
        endpoint = _rotate_point(
            (final_origin[0], final_origin[1] + authored_length, final_origin[2]),
            final_origin,
            tuple(final_cube["rotation"]),
        )
        for actual, expected in zip(endpoint, (-4, 11, 2)):
            self.assertAlmostEqual(expected, actual, places=5)

        second = semantic_geometry.SemanticModelBuilder()
        second.add_bone("body", "root", (0, 4, 0))
        second.add_cube(
            semantic_geometry.segment_cube(
                "body_core", "body", (0, 3, 0), (0, 5, 0), 2, "body", "dark"
            )
        )
        permuted = second.add_branch_graph(
            "crown",
            "body",
            "root_joint",
            tuple(reversed(nodes)),
            tuple(reversed(edges)),
            overlap=0.3,
            parent_cube="body_core",
        )
        self.assertEqual(result.manifest, permuted.manifest)
        self.assertEqual(builder.bones, second.bones)
        self.assertEqual(builder.cubes, second.cubes)
        self.assertEqual(
            "piecewise-constant-midpoint-sampling", result.manifest["taper_method"]
        )

        original_bones = list(builder.bones)
        original_cubes = list(builder.cubes)
        detached_nodes = (
            semantic_geometry.BranchNode("far_root", (100, 100, 100)),
            semantic_geometry.BranchNode("far_tip", (100, 102, 100)),
        )
        detached_edges = (
            semantic_geometry.BranchEdge(
                "edge", "far_root", "far_tip", 1, 0.5, "dark", "far edge"
            ),
        )
        with self.assertRaisesRegex(ValueError, "detached from its parent cube"):
            builder.add_branch_graph(
                "detached",
                "body",
                "far_root",
                detached_nodes,
                detached_edges,
                parent_cube="body_core",
            )
        with self.assertRaisesRegex(ValueError, "belong to the parent bone"):
            builder.add_branch_graph(
                "wrong_parent",
                "root",
                "far_root",
                detached_nodes,
                detached_edges,
                parent_cube="body_core",
            )
        self.assertEqual(original_bones, builder.bones)
        self.assertEqual(original_cubes, builder.cubes)

    def test_invalid_branch_graphs_are_rejected_atomically(self):
        builder = semantic_geometry.SemanticModelBuilder()
        builder.add_bone("body", "root", (0, 0, 0))
        original_bones = list(builder.bones)
        cases = (
            (
                (
                    semantic_geometry.BranchNode("a", (0, 0, 0)),
                    semantic_geometry.BranchNode("b", (0, 2, 0)),
                    semantic_geometry.BranchNode("c", (0, 4, 0)),
                    semantic_geometry.BranchNode("d", (2, 4, 0)),
                ),
                (
                    semantic_geometry.BranchEdge("ab", "a", "b", 1, 1, "m", "ab"),
                    semantic_geometry.BranchEdge("cd", "c", "d", 1, 1, "m", "cd"),
                    semantic_geometry.BranchEdge("dc", "d", "c", 1, 1, "m", "dc"),
                ),
                "contains a cycle",
            ),
            (
                (
                    semantic_geometry.BranchNode("a", (0, 0, 0)),
                    semantic_geometry.BranchNode("a", (0, 2, 0)),
                ),
                (semantic_geometry.BranchEdge("ab", "a", "a", 1, 1, "m", "ab"),),
                "duplicate branch node",
            ),
            (
                (
                    semantic_geometry.BranchNode("a", (0, 0, 0)),
                    semantic_geometry.BranchNode("b", (math.nan, 2, 0)),
                ),
                (semantic_geometry.BranchEdge("ab", "a", "b", 1, 1, "m", "ab"),),
                "finite",
            ),
            (
                (
                    semantic_geometry.BranchNode("a", (0, 0, 0)),
                    semantic_geometry.BranchNode("b", (0, 2, 0)),
                ),
                (semantic_geometry.BranchEdge("ab", "a", "b", 0, 1, "m", "ab"),),
                "finite and positive",
            ),
            (
                (
                    semantic_geometry.BranchNode("a", (0, 0, 0)),
                    semantic_geometry.BranchNode("b", (0, 2, 0)),
                ),
                (
                    semantic_geometry.BranchEdge(
                        "bad!", "a", "b", 1, 1, "m", "invalid id"
                    ),
                ),
                "invalid branch segment name",
            ),
            (
                (
                    semantic_geometry.BranchNode("a", (0, 0, 0)),
                    semantic_geometry.BranchNode("b", (0, 2, 0)),
                    semantic_geometry.BranchNode("c", (2, 2, 0)),
                ),
                (
                    semantic_geometry.BranchEdge("same", "a", "b", 1, 1, "m", "ab"),
                    semantic_geometry.BranchEdge("same", "a", "c", 1, 1, "m", "ac"),
                ),
                "duplicate branch edge",
            ),
            (
                (
                    semantic_geometry.BranchNode("a", (0, 0, 0)),
                    semantic_geometry.BranchNode("b", (0, 2, 0)),
                    semantic_geometry.BranchNode("c", (2, 2, 0)),
                ),
                (
                    semantic_geometry.BranchEdge("ab", "a", "b", 1, 1, "m", "ab"),
                    semantic_geometry.BranchEdge("cb", "c", "b", 1, 1, "m", "cb"),
                ),
                "multiple incoming",
            ),
        )
        for nodes, edges, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    builder.add_branch_graph("bad", "body", "a", nodes, edges)
                self.assertEqual(original_bones, builder.bones)
                self.assertEqual([], builder.cubes)


if __name__ == "__main__":
    unittest.main()
