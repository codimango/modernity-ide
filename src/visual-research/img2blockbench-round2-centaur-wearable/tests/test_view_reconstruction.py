import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

import img2blockbench
import view_reconstruction


class ViewReconstructionTests(unittest.TestCase):
    def _write_fixture(self, folder: Path, order: list[str]) -> Path:
        definitions = {
            "front": (0.0, (-0.625, 0.625), "#d84a3c", "observed"),
            "right": (90.0, (-0.375, 0.375), "#3158b8", "synthetic_proxy"),
            "back": (180.0, (-0.625, 0.625), "#ba9a54", "observed"),
            "left": (270.0, (-0.375, 0.375), "#4f9a64", "synthetic_proxy"),
        }
        views = []
        for name in sorted(definitions):
            azimuth, horizontal, color, _ = definitions[name]
            image_path = folder / f"{name}.png"
            mask_path = folder / f"{name}-mask.png"
            image = Image.new("RGB", (96, 96), "#101820")
            mask = Image.new("L", image.size, 0)
            left = round(48 + horizontal[0] * 28)
            right = round(48 + horizontal[1] * 28)
            top = round(80 - 1.75 * 28)
            bottom = round(80 - 0.25 * 28)
            ImageDraw.Draw(image).rectangle(
                (left, top, right, bottom), fill=color
            )
            ImageDraw.Draw(mask).rectangle(
                (left, top, right, bottom), fill=255
            )
            image.save(image_path)
            mask.save(mask_path)
        for name in order:
            azimuth, _, _, evidence_kind = definitions[name]
            views.append(
                {
                    "id": name,
                    "image": f"{name}.png",
                    "mask": f"{name}-mask.png",
                    "azimuth_degrees": azimuth,
                    "center_px": [48, 80],
                    "pixels_per_unit": 28,
                    "evidence_kind": evidence_kind,
                }
            )
        manifest = {
            "schema_version": 1,
            "calibration": {
                "projection": "orthographic-yaw",
                "volume_bounds": [[-1, 0, -1], [1, 2, 1]],
            },
            "reference_view": "front",
            "views": views,
        }
        path = folder / "views.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def _write_disconnected_fixture(self, folder: Path) -> Path:
        views = []
        for name, azimuth, color in (
            ("front", 0.0, "#d84a3c"),
            ("right", 90.0, "#3158b8"),
        ):
            image_path = folder / f"{name}.png"
            mask_path = folder / f"{name}-mask.png"
            image = Image.new("RGB", (96, 96), "#101820")
            mask = Image.new("L", image.size, 0)
            image_draw = ImageDraw.Draw(image)
            mask_draw = ImageDraw.Draw(mask)
            for bounds in ((39, 63, 57, 75), (39, 35, 57, 47)):
                image_draw.rectangle(bounds, fill=color)
                mask_draw.rectangle(bounds, fill=255)
            image.save(image_path)
            mask.save(mask_path)
            views.append(
                {
                    "id": name,
                    "image": image_path.name,
                    "mask": mask_path.name,
                    "azimuth_degrees": azimuth,
                    "center_px": [48, 80],
                    "pixels_per_unit": 28,
                    "evidence_kind": "observed",
                }
            )
        manifest = {
            "schema_version": 1,
            "calibration": {
                "projection": "orthographic-yaw",
                "volume_bounds": [[-1, 0, -1], [1, 2, 1]],
            },
            "reference_view": "front",
            "views": views,
        }
        path = folder / "disconnected-views.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_visual_hull_is_order_independent_strict_and_buildable(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = self._write_fixture(
                folder, ["front", "right", "back", "left"]
            )
            output = folder / "box.json"
            options = view_reconstruction.ViewReconstructionOptions(
                resolution=20,
                max_cuboids=12,
                palette_size=8,
            )
            first, first_report = view_reconstruction.reconstruct_view_spec(
                manifest,
                output,
                "calibrated_box",
                "A calibrated synthetic cuboid",
                "object",
                options,
            )
            manifest = self._write_fixture(
                folder, ["left", "back", "right", "front"]
            )
            second, second_report = view_reconstruction.reconstruct_view_spec(
                manifest,
                output,
                "calibrated_box",
                "A calibrated synthetic cuboid",
                "object",
                options,
            )

            self.assertEqual(first["cubes"], second["cubes"])
            self.assertEqual(first["materials"], second["materials"])
            self.assertEqual(
                first_report["voxelization"], second_report["voxelization"]
            )
            self.assertEqual(
                ["back", "front", "left", "right"],
                [view["id"] for view in first_report["views"]],
            )
            self.assertEqual(
                2,
                first_report["axis_constraints"]["horizontal_constraint_rank_all"],
            )
            self.assertEqual(
                1,
                first_report["axis_constraints"][
                    "horizontal_constraint_rank_observed"
                ],
            )
            self.assertFalse(
                first_report[
                    "hidden_geometry_established_from_observed_views"
                ]
            )
            self.assertGreater(
                first_report["color_transfer"][
                    "visible_sample_contributions_by_evidence_kind"
                ]["observed"],
                0,
            )
            self.assertGreater(
                first_report["color_transfer"][
                    "visible_sample_contributions_by_evidence_kind"
                ]["synthetic_proxy"],
                0,
            )
            attribution = first_report["color_transfer"][
                "exclusive_direct_color_attribution"
            ]
            self.assertEqual(
                attribution["union"],
                attribution["observed_only"]
                + attribution["synthetic_proxy_only"]
                + attribution["both_observed_and_proxy"],
            )
            self.assertEqual(
                "observed samples take precedence over synthetic proxies",
                first_report["color_transfer"]["color_precedence"],
            )
            self.assertFalse(
                first["generation"]["hidden_geometry"][
                    "hidden_geometry_established_from_observed_views"
                ]
            )
            self.assertEqual(
                {"observed", "synthetic_proxy"},
                {view["evidence_kind"] for view in first_report["views"]},
            )
            self.assertIn(
                "concavities that do not alter any supplied silhouette",
                first_report["hidden_geometry"]["cannot_recover"],
            )
            self.assertGreaterEqual(len(first["materials"]), 2)
            self.assertLessEqual(len(first["cubes"]), options.max_cuboids)
            for metrics in first_report["per_view_silhouette"].values():
                self.assertGreater(metrics["fitted_cuboids"]["iou"], 0.72)

            self.assertEqual([], img2blockbench.validate_spec(first, strict=True))
            img2blockbench.write_json(output, first)
            build = img2blockbench.build_model(output, folder / "build")
            self.assertTrue(build["audit"]["ok"])
            self.assertTrue((folder / "build" / "calibrated_box.bbmodel").is_file())

    def test_parallel_yaw_axes_are_rejected_as_depth_underconstrained(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = self._write_fixture(folder, ["front", "back"])
            with self.assertRaisesRegex(ValueError, "depth-underconstrained"):
                view_reconstruction.reconstruct_view_spec(
                    manifest,
                    folder / "invalid.json",
                    "invalid_views",
                    "Underconstrained views",
                    "object",
                    view_reconstruction.ViewReconstructionOptions(resolution=12),
                )

    def test_disconnected_components_are_all_retained_with_sufficient_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = self._write_disconnected_fixture(folder)
            spec, evidence = view_reconstruction.reconstruct_view_spec(
                manifest,
                folder / "disconnected.json",
                "disconnected_views",
                "Two disconnected calibrated visual-hull parts",
                "object",
                view_reconstruction.ViewReconstructionOptions(
                    resolution=20,
                    max_cuboids=2,
                    min_component_voxels=1,
                    min_component_fraction=0,
                ),
            )

            components = evidence["voxelization"]["components"]
            self.assertEqual(2, components["after_cleanup"])
            self.assertEqual(
                "fail rather than drop a retained component",
                components["budget_policy"],
            )
            self.assertEqual(
                {"visual hull component 1", "visual hull component 2"},
                {cube["role"] for cube in spec["cubes"]},
            )

    def test_multiview_reconstruction_does_not_import_trimesh(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = self._write_fixture(folder, ["front", "right"])
            real_import = __import__

            def reject_trimesh(name, *args, **kwargs):
                if name == "trimesh" or name.startswith("trimesh."):
                    raise AssertionError("multiview reconstruction imported trimesh")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=reject_trimesh):
                spec, evidence = view_reconstruction.reconstruct_view_spec(
                    manifest,
                    folder / "numpy-only.json",
                    "numpy_only_views",
                    "A NumPy-only calibrated view reconstruction",
                    "object",
                    view_reconstruction.ViewReconstructionOptions(
                        resolution=16,
                        max_cuboids=12,
                        palette_size=8,
                    ),
                )

            self.assertTrue(spec["cubes"])
            self.assertGreater(
                evidence["voxelization"]["components"]["after_cleanup"], 0
            )

    def test_missing_numpy_names_the_multiview_extra(self):
        real_import = __import__

        def reject_numpy(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise ModuleNotFoundError("numpy blocked for test")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=reject_numpy):
            with self.assertRaisesRegex(
                ValueError, "img2blockbench\\[multi-view\\]"
            ):
                view_reconstruction._numpy()

    def test_component_budget_fails_instead_of_dropping_visual_hull_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = self._write_disconnected_fixture(folder)

            with self.assertRaisesRegex(
                ValueError,
                "increase --max-cuboids rather than dropping visual-hull parts",
            ):
                view_reconstruction.reconstruct_view_spec(
                    manifest,
                    folder / "disconnected.json",
                    "disconnected_views",
                    "Two disconnected calibrated visual-hull parts",
                    "object",
                    view_reconstruction.ViewReconstructionOptions(
                        resolution=20,
                        max_cuboids=1,
                        min_component_voxels=1,
                        min_component_fraction=0,
                    ),
                )

    def test_duplicate_observed_images_do_not_claim_independent_depth(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = self._write_fixture(folder, ["front", "right"])
            Image.open(folder / "front.png").save(folder / "right.png")
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            for view in manifest_data["views"]:
                view["evidence_kind"] = "observed"
            manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
            _, evidence = view_reconstruction.reconstruct_view_spec(
                manifest,
                folder / "duplicate.json",
                "duplicate_views",
                "Two calibrations backed by the same observed pixels",
                "object",
                view_reconstruction.ViewReconstructionOptions(
                    resolution=16,
                    max_cuboids=12,
                    palette_size=8,
                ),
            )

            constraints = evidence["axis_constraints"]
            self.assertEqual(2, constraints["horizontal_constraint_rank_observed"])
            self.assertEqual(
                1,
                constraints[
                    "horizontal_constraint_rank_observed_independent_content"
                ],
            )
            self.assertEqual(1, constraints["independent_observed_view_count"])
            self.assertEqual(
                [["front", "right"]], constraints["observed_content_groups"]
            )
            self.assertEqual(
                [["front", "right"]],
                [
                    pair["views"]
                    for pair in constraints["duplicate_observed_view_pairs"]
                ],
            )
            self.assertFalse(
                evidence["hidden_geometry_established_from_observed_views"]
            )

    def test_from_views_cli_writes_evidence_and_optional_build(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = self._write_fixture(folder, ["front", "right"])
            output = folder / "cli.json"
            evidence = folder / "cli-evidence.json"
            with redirect_stdout(io.StringIO()):
                exit_code = img2blockbench.main(
                    [
                        "from-views",
                        str(manifest),
                        "--id",
                        "cli_views",
                        "--description",
                        "A CLI calibrated view reconstruction",
                        "--output",
                        str(output),
                        "--evidence",
                        str(evidence),
                        "--build-output",
                        str(folder / "cli-build"),
                        "--resolution",
                        "16",
                        "--max-cuboids",
                        "10",
                    ]
                )
            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())
            self.assertTrue(evidence.is_file())
            self.assertTrue((folder / "cli-build" / "cli_views.bbmodel").is_file())
            self.assertEqual(
                "calibrated-orthographic-yaw-visual-hull-cuboids-v1",
                img2blockbench.read_json(evidence)["algorithm"],
            )

    def test_clip_extraction_preserves_only_caller_calibration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            clip = folder / "turntable.mp4"
            clip.write_bytes(b"synthetic clip fixture")
            for name in ("front", "side"):
                mask = Image.new("L", (32, 32), 0)
                ImageDraw.Draw(mask).rectangle((8, 4, 23, 27), fill=255)
                mask.save(folder / f"{name}-mask.png")
            request = {
                "schema_version": 1,
                "calibration": {
                    "projection": "orthographic-yaw",
                    "volume_bounds": [[-1, 0, -1], [1, 2, 1]],
                },
                "reference_view": "front",
                "samples": [
                    {
                        "id": "side",
                        "timestamp_seconds": 1.25,
                        "azimuth_degrees": 90,
                        "center_px": [16, 28],
                        "pixels_per_unit": 12,
                        "mask": "side-mask.png",
                        "evidence_kind": "observed",
                    },
                    {
                        "id": "front",
                        "timestamp_seconds": 0.125,
                        "azimuth_degrees": 0,
                        "center_px": [16, 28],
                        "pixels_per_unit": 12,
                        "mask": "front-mask.png",
                        "evidence_kind": "observed",
                    },
                ],
            }
            samples = folder / "samples.json"
            samples.write_text(json.dumps(request), encoding="utf-8")

            def fake_run(command, **kwargs):
                Image.new("RGBA", (32, 32), "#7f624b").save(command[-1])
                return mock.Mock(returncode=0, stdout="", stderr="")

            output = folder / "extracted" / "views.json"
            with mock.patch.object(
                view_reconstruction.shutil, "which", return_value="/test/ffmpeg"
            ), mock.patch.object(
                view_reconstruction.subprocess, "run", side_effect=fake_run
            ) as run:
                result = view_reconstruction.extract_clip_view_manifest(
                    clip,
                    samples,
                    output,
                    folder / "extracted" / "frames",
                    "ffmpeg",
                )

            generated = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(["front", "side"], [view["id"] for view in generated["views"]])
            self.assertEqual(
                [0.125, 1.25],
                [view["timestamp_seconds"] for view in generated["views"]],
            )
            self.assertEqual([0.0, 90.0], [view["azimuth_degrees"] for view in generated["views"]])
            self.assertEqual(2, run.call_count)
            self.assertFalse(result["camera_motion_inferred"])
            self.assertIn(
                "not inferred",
                generated["clip_provenance"]["camera_motion"],
            )

    def test_clip_request_is_validated_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            clip = folder / "turntable.mp4"
            clip.write_bytes(b"synthetic clip fixture")
            mask = Image.new("L", (32, 32), 0)
            ImageDraw.Draw(mask).rectangle((8, 4, 23, 27), fill=255)
            mask.save(folder / "mask.png")
            request = {
                "schema_version": 1,
                "calibration": {
                    "projection": "orthographic-yaw",
                    "volume_bounds": [[1, 0, -1], [-1, 2, 1]],
                },
                "reference_view": "missing",
                "samples": [
                    {
                        "id": "front",
                        "timestamp_seconds": 0,
                        "azimuth_degrees": 0,
                        "center_px": [16, 28],
                        "pixels_per_unit": 12,
                        "mask": "mask.png",
                        "evidence_kind": "observed",
                    },
                    {
                        "id": "back",
                        "timestamp_seconds": 1,
                        "azimuth_degrees": 180,
                        "center_px": [16, 28],
                        "pixels_per_unit": 12,
                        "mask": "mask.png",
                        "evidence_kind": "observed",
                    },
                ],
            }
            samples = folder / "samples.json"
            samples.write_text(json.dumps(request), encoding="utf-8")
            with mock.patch.object(view_reconstruction.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "volume_bounds"):
                    view_reconstruction.extract_clip_view_manifest(
                        clip,
                        samples,
                        folder / "views.json",
                        folder / "frames",
                    )
            run.assert_not_called()

            request["calibration"]["volume_bounds"] = [[-1, 0, -1], [1, 2, 1]]
            samples.write_text(json.dumps(request), encoding="utf-8")
            with mock.patch.object(view_reconstruction.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "reference_view"):
                    view_reconstruction.extract_clip_view_manifest(
                        clip,
                        samples,
                        folder / "views.json",
                        folder / "frames",
                    )
            run.assert_not_called()

            request["reference_view"] = "front"
            samples.write_text(json.dumps(request), encoding="utf-8")
            with mock.patch.object(view_reconstruction.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "depth-underconstrained"):
                    view_reconstruction.extract_clip_view_manifest(
                        clip,
                        samples,
                        folder / "views.json",
                        folder / "frames",
                    )
            run.assert_not_called()

    def test_clip_rejects_frame_mask_dimension_mismatch_without_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            clip = folder / "turntable.mp4"
            clip.write_bytes(b"synthetic clip fixture")
            mask = Image.new("L", (32, 32), 0)
            ImageDraw.Draw(mask).rectangle((8, 4, 23, 27), fill=255)
            mask.save(folder / "mask.png")
            request = {
                "schema_version": 1,
                "calibration": {
                    "projection": "orthographic-yaw",
                    "volume_bounds": [[-1, 0, -1], [1, 2, 1]],
                },
                "reference_view": "front",
                "samples": [
                    {
                        "id": "front",
                        "timestamp_seconds": 0,
                        "azimuth_degrees": 0,
                        "center_px": [16, 28],
                        "pixels_per_unit": 12,
                        "mask": "mask.png",
                        "evidence_kind": "observed",
                    },
                    {
                        "id": "side",
                        "timestamp_seconds": 1,
                        "azimuth_degrees": 90,
                        "center_px": [16, 28],
                        "pixels_per_unit": 12,
                        "mask": "mask.png",
                        "evidence_kind": "observed",
                    },
                ],
            }
            samples = folder / "samples.json"
            samples.write_text(json.dumps(request), encoding="utf-8")

            def fake_run(command, **kwargs):
                Image.new("RGBA", (96, 96), "#7f624b").save(command[-1])
                return mock.Mock(returncode=0, stdout="", stderr="")

            output = folder / "extracted" / "views.json"
            with mock.patch.object(
                view_reconstruction.shutil, "which", return_value="/test/ffmpeg"
            ), mock.patch.object(
                view_reconstruction.subprocess, "run", side_effect=fake_run
            ):
                with self.assertRaisesRegex(ValueError, "but its mask is 32x32"):
                    view_reconstruction.extract_clip_view_manifest(
                        clip,
                        samples,
                        output,
                        folder / "extracted" / "frames",
                    )
            self.assertFalse(output.exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_real_ffmpeg_clip_round_trip_is_strict_and_observed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            definitions = (
                ("front", (30, 31, 66, 73), "#c74b42", 0),
                ("side", (38, 31, 58, 73), "#4167bd", 90),
            )
            samples = []
            for index, (name, bounds, color, azimuth) in enumerate(definitions):
                frame = Image.new("RGB", (96, 96), "#101820")
                ImageDraw.Draw(frame).rectangle(bounds, fill=color)
                frame.save(folder / f"source-{index:02d}.png")
                mask = Image.new("L", (96, 96), 0)
                ImageDraw.Draw(mask).rectangle(bounds, fill=255)
                mask.save(folder / f"{name}-mask.png")
                samples.append(
                    {
                        "id": name,
                        "timestamp_seconds": index,
                        "azimuth_degrees": azimuth,
                        "center_px": [48, 80],
                        "pixels_per_unit": 28,
                        "mask": f"{name}-mask.png",
                        "evidence_kind": "observed",
                    }
                )
            clip = folder / "turntable.mp4"
            subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-framerate",
                    "1",
                    "-i",
                    str(folder / "source-%02d.png"),
                    "-c:v",
                    "libx264",
                    "-g",
                    "1",
                    "-pix_fmt",
                    "yuv420p",
                    str(clip),
                ],
                check=True,
            )
            request = {
                "schema_version": 1,
                "calibration": {
                    "projection": "orthographic-yaw",
                    "volume_bounds": [[-1, 0, -1], [1, 2, 1]],
                },
                "reference_view": "front",
                "samples": samples,
            }
            request_path = folder / "samples.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            manifest = folder / "extracted" / "views.json"
            view_reconstruction.extract_clip_view_manifest(
                clip,
                request_path,
                manifest,
                folder / "extracted" / "frames",
            )
            spec, evidence = view_reconstruction.reconstruct_view_spec(
                manifest,
                folder / "model.json",
                "real_clip_round_trip",
                "Real ffmpeg integration fixture",
                "object",
                view_reconstruction.ViewReconstructionOptions(
                    resolution=16,
                    max_cuboids=12,
                    palette_size=8,
                ),
            )
            self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
            self.assertEqual(
                2,
                evidence["axis_constraints"]["horizontal_constraint_rank_observed"],
            )
            self.assertTrue(
                evidence["hidden_geometry_established_from_observed_views"]
            )
            self.assertEqual(
                0,
                evidence["color_transfer"][
                    "visible_sample_contributions_by_evidence_kind"
                ]["synthetic_proxy"],
            )

if __name__ == "__main__":
    unittest.main()
