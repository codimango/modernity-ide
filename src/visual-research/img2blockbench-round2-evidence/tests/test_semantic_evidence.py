import importlib.util
import unittest
from dataclasses import FrozenInstanceError

from PIL import Image, ImageDraw


HAS_NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(HAS_NUMPY, "install img2blockbench[semantic-evidence] to render")
class SemanticEvidenceTests(unittest.TestCase):
    @staticmethod
    def _perspective_spec(
        cubes: list[dict], colors: tuple[str, ...] = ("#dd331f", "#2255dd")
    ) -> dict:
        """Create a compact renderer fixture with deterministic solid materials."""
        materials = {
            f"paint_{index}": {
                "base": color,
                "shade": color,
                "highlight": color,
                "pattern": "solid",
                "pattern_scale": 1,
            }
            for index, color in enumerate(colors)
        }
        return {
            "geometry": {"precision": 256},
            "texture": {
                "density": 2,
                "palette_size": 8,
                "gutter": 1,
                "atlas_size": 64,
            },
            "materials": materials,
            "cubes": cubes,
            "landmarks": [],
        }

    @staticmethod
    def _perspective_cube(
        name: str,
        center: tuple[float, float, float],
        size: tuple[float, float, float] = (1.0, 1.0, 1.0),
        material: str = "paint_0",
    ) -> dict:
        """Create one unrotated cube for fixed-camera renderer tests."""
        return {
            "name": name,
            "bone": "root",
            "center": list(center),
            "size": list(size),
            "rotation": [0, 0, 0],
            "origin": list(center),
            "role": "perspective test cube",
            "material": material,
            "faces": {},
        }

    def test_front_back_render_is_deterministic_and_respects_face_material(self):
        from semantic_evidence import foreground_mask, render_view

        material = lambda base: {
            "base": base,
            "shade": base,
            "highlight": base,
            "pattern": "solid",
            "pattern_scale": 1,
        }
        spec = {
            "texture": {"density": 2, "palette_size": 4, "gutter": 1, "atlas_size": 64},
            "materials": {
                "red": material("#dd331f"),
                "blue": material("#2255dd"),
            },
            "cubes": [
                {
                    "name": "box",
                    "bone": "root",
                    "center": [0, 0, 0],
                    "size": [4, 5, 3],
                    "rotation": [0, 0, 0],
                    "origin": [0, 0, 0],
                    "role": "test box",
                    "material": "red",
                    "faces": {"south": {"material": "blue"}},
                }
            ],
            "landmarks": [],
        }
        first = render_view(spec, (0, 0, 1), size=(96, 96))
        second = render_view(spec, (0, 0, 1), size=(96, 96))
        back = render_view(spec, (0, 0, -1), size=(96, 96))
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertIsNotNone(foreground_mask(first).getbbox())
        front_pixel = first.convert("RGB").getpixel((48, 48))
        back_pixel = back.convert("RGB").getpixel((48, 48))
        self.assertGreater(front_pixel[2], front_pixel[0])
        self.assertGreater(back_pixel[0], back_pixel[2])

    def test_alpha_silhouette_preserves_aspect_and_scores_keypoints(self):
        from semantic_evidence import alpha_silhouette_metrics

        reference = Image.new("RGBA", (80, 120), (0, 0, 0, 0))
        ImageDraw.Draw(reference).rectangle((20, 10, 59, 109), fill="#ffffff")
        rendered = Image.new("RGBA", (160, 160), (13, 20, 28, 255))
        ImageDraw.Draw(rendered).rectangle((60, 20, 99, 119), fill="#aa3322")
        metrics = alpha_silhouette_metrics(
            reference,
            rendered,
            reference_keypoints={"eye": (40, 35), "hem": (40, 105)},
            rendered_keypoints={"eye": (80, 45), "hem": (80, 115)},
            target_height=100,
        )
        self.assertEqual(1.0, metrics["iou"])
        self.assertEqual(0.4, metrics["reference_aspect_ratio"])
        self.assertEqual(0.4, metrics["rendered_aspect_ratio"])
        self.assertEqual(2, metrics["keypoints"]["count"])
        self.assertEqual(0.0, metrics["keypoints"]["maximum_error_subject_heights"])

    def test_alpha_silhouette_rejects_opaque_or_mismatched_inputs(self):
        from semantic_evidence import alpha_mask, alpha_silhouette_metrics

        with self.assertRaisesRegex(ValueError, "within 1..255"):
            alpha_mask(Image.new("RGBA", (8, 8), (0, 0, 0, 0)), threshold=0)
        with self.assertRaisesRegex(ValueError, "no transparent pixels"):
            alpha_mask(Image.new("RGB", (8, 8), "white"))
        reference = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
        ImageDraw.Draw(reference).rectangle((2, 2, 9, 9), fill="white")
        rendered = Image.new("RGB", (12, 12), (13, 20, 28))
        ImageDraw.Draw(rendered).rectangle((2, 2, 9, 9), fill="red")
        with self.assertRaisesRegex(ValueError, "names must match"):
            alpha_silhouette_metrics(
                reference,
                rendered,
                reference_keypoints={"a": (3, 3)},
                rendered_keypoints={"b": (3, 3)},
            )

    def test_perspective_camera_projects_center_offset_and_behind(self):
        from semantic_evidence import (
            PerspectiveCamera,
            ProjectedPoint,
            project_perspective_point,
        )

        camera = PerspectiveCamera(
            image_size=(100, 80),
            focal_x=80,
            focal_y=80,
            principal_point=(50, 40),
            world_to_camera=((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            translation=(0, 0, 0),
            near=0.1,
        )
        center = project_perspective_point(camera, (0, 0, -2))
        offset_x = project_perspective_point(camera, (1, 0, -2))
        offset_y = project_perspective_point(camera, (0, 1, -2))
        outside = project_perspective_point(camera, (2, 0, -2))
        behind = project_perspective_point(camera, (0, 0, 1))
        self.assertEqual(ProjectedPoint((50, 40), 2, True, True), center)
        self.assertEqual(ProjectedPoint((90, 40), 2, True, True), offset_x)
        self.assertEqual(ProjectedPoint((50, 0), 2, True, True), offset_y)
        self.assertEqual(ProjectedPoint((130, 40), 2, True, False), outside)
        self.assertEqual(ProjectedPoint(None, -1, False, False), behind)
        with self.assertRaises(FrozenInstanceError):
            camera.near = 1.0
        with self.assertRaises(FrozenInstanceError):
            center.depth = 1.0
        with self.assertRaisesRegex(ValueError, "require pixels"):
            ProjectedPoint(None, 1, True, False)

    def test_orbit_camera_yaw_and_pitch_projection(self):
        from semantic_evidence import (
            PerspectiveCamera,
            ProjectedPoint,
            project_perspective_point,
        )

        front = PerspectiveCamera.from_orbit(
            (100, 100),
            yaw_degrees=0,
            pitch_degrees=0,
            vertical_fov_degrees=90,
            target=(0, 0, 0),
            distance=10,
        )
        yawed = PerspectiveCamera.from_orbit(
            (100, 100),
            yaw_degrees=90,
            pitch_degrees=0,
            vertical_fov_degrees=90,
            target=(0, 0, 0),
            distance=10,
        )
        pitched = PerspectiveCamera.from_orbit(
            (100, 100),
            yaw_degrees=0,
            pitch_degrees=30,
            vertical_fov_degrees=90,
            target=(0, 0, 0),
            distance=10,
        )
        center = project_perspective_point(front, (0, 0, 0))
        front_offset = project_perspective_point(front, (1, 0, 0))
        yawed_offset = project_perspective_point(yawed, (0, 0, 1))
        pitched_offset = project_perspective_point(pitched, (0, 1, 0))
        self.assertEqual(ProjectedPoint((50, 50), 10, True, True), center)
        self.assertGreater(front_offset.pixel[0], 50)
        self.assertLess(yawed_offset.pixel[0], 50)
        self.assertLess(pitched_offset.pixel[1], 50)
        self.assertAlmostEqual(1.0, __import__("numpy").linalg.det(yawed.world_to_camera))

    def test_orbit_camera_roll_rotates_image_axes(self):
        from semantic_evidence import PerspectiveCamera, project_perspective_point

        camera = PerspectiveCamera.from_orbit(
            (100, 100),
            yaw_degrees=0,
            pitch_degrees=0,
            roll_degrees=90,
            vertical_fov_degrees=90,
            target=(0, 0, 0),
            distance=10,
        )
        world_right = project_perspective_point(camera, (1, 0, 0))
        world_up = project_perspective_point(camera, (0, 1, 0))
        self.assertAlmostEqual(50, world_right.pixel[0])
        self.assertGreater(world_right.pixel[1], 50)
        self.assertGreater(world_up.pixel[0], 50)
        self.assertAlmostEqual(50, world_up.pixel[1])

    def test_perspective_camera_rejects_invalid_parameters(self):
        from semantic_evidence import PerspectiveCamera

        valid = {
            "image_size": (100, 80),
            "focal_x": 80,
            "focal_y": 80,
            "principal_point": (50, 40),
            "world_to_camera": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            "translation": (0, 0, 0),
            "near": 0.1,
        }
        invalid = (
            {**valid, "image_size": (0, 80)},
            {**valid, "image_size": None},
            {**valid, "focal_x": 0},
            {**valid, "principal_point": (float("nan"), 40)},
            {**valid, "principal_point": None},
            {**valid, "world_to_camera": ((2, 0, 0), (0, 1, 0), (0, 0, 1))},
            {**valid, "world_to_camera": ((1, 0, 0), (0, 1, 0), (0, 0, -1))},
            {**valid, "world_to_camera": None},
            {**valid, "translation": (0, float("nan"), 0)},
            {**valid, "translation": None},
            {**valid, "near": 0},
        )
        for parameters in invalid:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                PerspectiveCamera(**parameters)
        off_axis = PerspectiveCamera(**{**valid, "principal_point": (120, -10)})
        self.assertEqual((120.0, -10.0), off_axis.principal_point)
        nearly_orthonormal = PerspectiveCamera(
            **{
                **valid,
                "world_to_camera": ((1, 5e-7, 0), (0, 1, 0), (0, 0, 1)),
            }
        )
        self.assertEqual(5e-7, nearly_orthonormal.world_to_camera[0][1])
        with self.assertRaisesRegex(ValueError, "pitch_degrees"):
            PerspectiveCamera.from_orbit(
                (100, 80), yaw_degrees=0, pitch_degrees=90, distance=10
            )
        with self.assertRaisesRegex(ValueError, "vertical_fov_degrees"):
            PerspectiveCamera.from_orbit(
                (100, 80),
                yaw_degrees=0,
                pitch_degrees=0,
                vertical_fov_degrees=180,
                distance=10,
            )
        with self.assertRaisesRegex(ValueError, "near plane"):
            PerspectiveCamera.from_orbit(
                (100, 80),
                yaw_degrees=0,
                pitch_degrees=0,
                distance=0.1,
                near=0.1,
            )
        with self.assertRaisesRegex(ValueError, "target"):
            PerspectiveCamera.from_orbit(
                (100, 80), yaw_degrees=0, pitch_degrees=0, target=None
            )

    def test_perspective_projection_rejects_non_finite_result(self):
        import sys

        from semantic_evidence import PerspectiveCamera, project_perspective_point

        camera = PerspectiveCamera(
            (100, 80),
            sys.float_info.max,
            80,
            (50, 40),
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            (0, 0, 0),
            0.1,
        )
        with self.assertRaisesRegex(ValueError, "non-finite pixel"):
            project_perspective_point(camera, (2, 0, -1))
        with self.assertRaisesRegex(ValueError, "point"):
            project_perspective_point(camera, None)

    def test_perspective_near_plane_is_clipped_without_nan(self):
        import warnings

        import numpy as np

        from semantic_evidence import (
            PerspectiveCamera,
            foreground_mask,
            project_perspective_point,
            render_perspective_view,
        )

        camera = PerspectiveCamera(
            (128, 96),
            90,
            90,
            (64, 48),
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            (0, 0, 0),
            0.1,
        )
        spec = self._perspective_spec(
            [self._perspective_cube("crossing", (0.12, 0, -0.12), (0.16, 0.08, 0.16))]
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            rendered = render_perspective_view(spec, camera)
        self.assertTrue(np.isfinite(np.asarray(rendered, dtype=np.float64)).all())
        self.assertIsNotNone(foreground_mask(rendered).getbbox())
        self.assertFalse(project_perspective_point(camera, (0, 0, -0.099)).in_front)
        self.assertTrue(project_perspective_point(camera, (0, 0, -0.1)).in_front)

    def test_perspective_uv_interpolation_uses_reciprocal_depth(self):
        import numpy as np

        from semantic_evidence import _raster_perspective_triangle

        canvas = np.zeros((12, 12, 4), dtype=np.uint8)
        zbuffer = np.full((12, 12), np.inf, dtype=np.float64)
        atlas = np.zeros((8, 8, 4), dtype=np.uint8)
        for y in range(8):
            for x in range(8):
                atlas[y, x] = (x, y, 0, 255)
        _raster_perspective_triangle(
            canvas,
            zbuffer,
            np.asarray(((1, 1), (9, 1), (1, 9)), dtype=np.float64),
            np.asarray((1, 4, 4), dtype=np.float64),
            np.asarray(((0, 0), (7, 0), (0, 7)), dtype=np.float64),
            atlas,
            1.0,
        )
        self.assertEqual((2, 2, 0, 255), tuple(canvas[4, 4]))

    def test_perspective_render_makes_nearer_cube_larger(self):
        from semantic_evidence import PerspectiveCamera, foreground_mask, render_perspective_view

        camera = PerspectiveCamera(
            (160, 120),
            100,
            100,
            (80, 60),
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            (0, 0, 0),
            0.1,
        )
        near = self._perspective_spec([self._perspective_cube("box", (0, 0, -3))])
        far = self._perspective_spec([self._perspective_cube("box", (0, 0, -6))])
        near_box = foreground_mask(render_perspective_view(near, camera)).getbbox()
        far_box = foreground_mask(render_perspective_view(far, camera)).getbbox()
        self.assertIsNotNone(near_box)
        self.assertIsNotNone(far_box)
        self.assertGreater(near_box[2] - near_box[0], far_box[2] - far_box[0])
        self.assertGreater(near_box[3] - near_box[1], far_box[3] - far_box[1])

    def test_perspective_zbuffer_fully_occludes_far_cube(self):
        from semantic_evidence import PerspectiveCamera, render_perspective_view

        camera = PerspectiveCamera(
            (128, 128),
            90,
            90,
            (64, 64),
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            (0, 0, 0),
            0.1,
        )
        spec = self._perspective_spec(
            [
                self._perspective_cube("far", (0, 0, -6), (2, 2, 1), "paint_1"),
                self._perspective_cube("near", (0, 0, -3), (2, 2, 1), "paint_0"),
            ]
        )
        complete = render_perspective_view(spec, camera)
        near_only = render_perspective_view(spec, camera, selected_names={"near"})
        self.assertEqual(near_only.tobytes(), complete.tobytes())

    def test_perspective_renderer_culls_faces_seen_only_from_inside(self):
        from semantic_evidence import PerspectiveCamera, foreground_mask, render_perspective_view

        camera = PerspectiveCamera(
            (96, 96),
            70,
            70,
            (48, 48),
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            (0, 0, 0),
            0.1,
        )
        spec = self._perspective_spec(
            [self._perspective_cube("surrounding", (0, 0, 0), (4, 4, 4))]
        )
        rendered = render_perspective_view(spec, camera)
        self.assertIsNone(foreground_mask(rendered).getbbox())

    def test_fixed_frame_evidence_penalizes_translation_and_discloses_limits(self):
        from semantic_evidence import (
            PerspectiveCamera,
            fixed_camera_perspective_evidence,
            foreground_mask,
            render_perspective_view,
        )

        spec = self._perspective_spec([self._perspective_cube("box", (0, 0, -4), (2, 2, 2))])
        camera = PerspectiveCamera(
            (128, 96),
            90,
            90,
            (64, 48),
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            (0, 0, 0),
            0.1,
        )
        reference = foreground_mask(render_perspective_view(spec, camera))
        _, exact = fixed_camera_perspective_evidence(
            spec,
            camera,
            reference,
            reference_keypoints={"center": (64, 48)},
            world_keypoints={"center": (0, 0, -4)},
        )
        shifted_camera = PerspectiveCamera(
            (128, 96),
            90,
            90,
            (64, 48),
            ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
            (0.6, 0, 0),
            0.1,
        )
        _, shifted = fixed_camera_perspective_evidence(
            spec,
            shifted_camera,
            reference,
            reference_keypoints={"center": (64, 48)},
            world_keypoints={"center": (0, 0, -4)},
        )
        self.assertEqual(1.0, exact["silhouette"]["iou"])
        self.assertLess(shifted["silhouette"]["iou"], exact["silhouette"]["iou"])
        self.assertGreater(shifted["keypoints"]["mean_error_image_heights"], 0)
        self.assertGreater(
            shifted["keypoints"]["mean_error_subject_heights"],
            shifted["keypoints"]["mean_error_image_heights"],
        )
        self.assertFalse(shifted["visual_hull_used"])
        self.assertFalse(shifted["hidden_geometry_established"])
        self.assertTrue(shifted["camera_parameters_are_estimated"])
        self.assertIn("no automatic fitting", shifted["alignment"])

    def test_aligned_metrics_report_subject_height_and_frame_contact(self):
        from semantic_evidence import aligned_keypoint_metrics, aligned_mask_metrics

        reference = Image.new("L", (50, 50), 0)
        ImageDraw.Draw(reference).rectangle((0, 10, 49, 29), fill=255)
        mask_metrics = aligned_mask_metrics(reference, reference)
        self.assertEqual([0, 10, 50, 30], mask_metrics["reference_bbox"])
        self.assertEqual(
            {"left": True, "top": False, "right": True, "bottom": False},
            mask_metrics["reference_touches_frame_edges"],
        )
        self.assertTrue(mask_metrics["reference_may_be_clipped"])

        keypoint_metrics = aligned_keypoint_metrics(
            {"point": (10, 10)},
            {"point": (10, 15)},
            reference.size,
            reference_subject_height=20,
        )
        self.assertEqual(0.1, keypoint_metrics["mean_error_image_heights"])
        self.assertEqual(0.25, keypoint_metrics["mean_error_subject_heights"])

    def test_perspective_render_is_deterministic_across_cube_order(self):
        from semantic_evidence import PerspectiveCamera, render_perspective_view

        cubes = [
            self._perspective_cube("near", (-0.35, 0, -3.5), material="paint_0"),
            self._perspective_cube("far", (0.35, 0, -5.0), material="paint_1"),
        ]
        first_spec = self._perspective_spec(cubes)
        second_spec = self._perspective_spec(list(reversed(cubes)))
        camera = PerspectiveCamera.from_orbit(
            (144, 112),
            yaw_degrees=12,
            pitch_degrees=8,
            roll_degrees=2,
            vertical_fov_degrees=52,
            target=(0, 0, -4),
            distance=7,
        )
        first = render_perspective_view(first_spec, camera)
        second = render_perspective_view(second_spec, camera)
        repeated = render_perspective_view(first_spec, camera)
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(first.tobytes(), repeated.tobytes())


if __name__ == "__main__":
    unittest.main()
