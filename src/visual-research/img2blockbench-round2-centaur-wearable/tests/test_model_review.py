from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import img2blockbench
import model_review
from img2blockbench import ModelSpecError, build_model, read_json, write_json
from model_review import MANIFEST_NAME, REQUIRED_VIEWS, SHEET_NAME, render_model_review


class ModelReviewTests(unittest.TestCase):
    @staticmethod
    def _write_strict_spec(folder: Path) -> Path:
        """Write a compact asymmetric model with a valid bound reference."""
        reference_path = folder / "private-reference.png"
        reference = Image.new("RGB", (11, 9), "#f04d7a")
        ImageDraw.Draw(reference).rectangle((1, 1, 4, 7), fill="#32b8d8")
        reference.save(reference_path)
        reference_bytes = reference_path.read_bytes()
        spec = {
            "schema_version": 1,
            "id": "review_fixture",
            "reference": {
                "image": reference_path.name,
                "sha256": hashlib.sha256(reference_bytes).hexdigest(),
                "width": 11,
                "height": 9,
            },
            "subject": {
                "type": "prop",
                "description": "An asymmetric review fixture",
                "symmetry": "asymmetric",
                "uncertainties": ["none identified"],
            },
            "quality_contract": {
                "complexity": "simple",
                "target_cuboids": [2, 4],
                "identity_features": ["offset blue cap"],
                "required_views": list(REQUIRED_VIEWS),
                "review_targets": ["silhouette", "all-angle volume"],
            },
            "texture": {
                "density": 1,
                "palette_size": 8,
                "gutter": 1,
                "atlas_size": 128,
            },
            "materials": {
                "red": {
                    "base": "#b83a32",
                    "shade": "#76251f",
                    "highlight": "#e56558",
                    "pattern": "solid",
                    "pattern_scale": 1,
                },
                "blue": {
                    "base": "#2879a8",
                    "shade": "#17435e",
                    "highlight": "#56add4",
                    "pattern": "solid",
                    "pattern_scale": 1,
                },
            },
            "bones": [{"name": "root", "parent": None, "pivot": [0, 0, 0]}],
            "cubes": [
                {
                    "name": "body",
                    "bone": "root",
                    "center": [0, 3, 0],
                    "size": [5, 6, 7],
                    "rotation": [0, 0, 0],
                    "origin": [0, 0, 0],
                    "role": "main body",
                    "material": "red",
                    "faces": {},
                },
                {
                    "name": "offset_cap",
                    "bone": "root",
                    "center": [2.8, 6.7, 1.4],
                    "size": [1.5, 2.0, 2.5],
                    "rotation": [12, 27, 8],
                    "origin": [0, 0, 0],
                    "role": "offset cap",
                    "material": "blue",
                    "faces": {},
                },
            ],
            "landmarks": [],
            "collision": {"width": 5, "height": 7.7, "eye_height": 6},
        }
        spec_path = folder / "model-spec.json"
        write_json(spec_path, spec)
        return spec_path

    def test_writes_deterministic_hash_bound_model_only_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            first_output = folder / "first"
            second_output = folder / "second"

            first = render_model_review(spec_path, first_output, image_size=(128, 112))
            second = render_model_review(spec_path, second_output, image_size=(128, 112))

            self.assertEqual(first, second)
            self.assertEqual(
                (first_output / MANIFEST_NAME).read_bytes(),
                (second_output / MANIFEST_NAME).read_bytes(),
            )
            self.assertEqual("complete", first["status"])
            self.assertTrue(first["complete"])
            self.assertTrue(first["model_only"])
            self.assertFalse(first["source_imagery_included"])
            self.assertFalse(first["resemblance_claimed"])
            self.assertTrue(first["agent_visual_review_required"])
            self.assertEqual("pending_agent_visual_review", first["approval_status"])
            self.assertEqual(list(REQUIRED_VIEWS), first["generated_views"])
            self.assertTrue(all(first["gates"].values()))
            self.assertTrue(first["unique_hash_gate"]["passed"])
            self.assertEqual(7, first["unique_hash_gate"]["unique_hashes"])

            expected_pngs = {f"{name}.png" for name in REQUIRED_VIEWS} | {SHEET_NAME}
            self.assertEqual(expected_pngs, {path.name for path in first_output.glob("*.png")})
            for record in first["views"]:
                image_path = first_output / record["image"]
                self.assertFalse(Path(record["image"]).is_absolute())
                self.assertNotIn("..", Path(record["image"]).parts)
                self.assertEqual(
                    hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    record["image_sha256"],
                )
                self.assertGreater(record["metrics"]["foreground"]["pixels"], 0)
                self.assertTrue(record["metrics"]["silhouette"]["nonempty"])
                self.assertIsNotNone(record["metrics"]["bbox"]["pixels"])

            sheet = first["all_angle_sheet"]
            self.assertEqual(
                hashlib.sha256((first_output / sheet["image"]).read_bytes()).hexdigest(),
                sheet["image_sha256"],
            )
            manifest_text = (first_output / MANIFEST_NAME).read_text(encoding="utf-8")
            self.assertNotIn("private-reference.png", manifest_text)
            self.assertNotIn(str(folder), manifest_text)

            build_output = folder / "build"
            build_result = build_model(
                spec_path,
                build_output,
                reference_policy="external",
                review_manifest=first_output / MANIFEST_NAME,
            )
            localized_manifest = Path(build_result["review_manifest"])
            self.assertEqual(
                "review_fixture.model-review.json", localized_manifest.name
            )
            self.assertTrue(localized_manifest.is_file())
            delivery = read_json(build_output / "review_fixture.model-spec.json")
            review = delivery["generation"]["model_review"]
            self.assertEqual(localized_manifest.name, review["manifest"])
            self.assertEqual(
                hashlib.sha256(localized_manifest.read_bytes()).hexdigest(),
                review["manifest_sha256"],
            )
            artifact_paths = {
                record["path"]
                for record in read_json(
                    build_output / "review_fixture.manifest.json"
                )["artifacts"]
            }
            self.assertIn("review_fixture.model-review.json", artifact_paths)
            self.assertIn(
                "review_fixture.model-review/all-angle-sheet.png", artifact_paths
            )
            self.assertFalse(
                any(path.endswith(".reference.png") for path in artifact_paths)
            )
            packaged_review = read_json(localized_manifest)
            self.assertFalse(packaged_review["model_spec"]["bundled"])
            self.assertEqual(
                "source-provenance-only",
                packaged_review["model_spec"]["availability"],
            )
            self.assertEqual(
                "review_fixture.model-spec.json",
                packaged_review["model_spec"]["delivery_file_name"],
            )

    def test_missing_numpy_names_the_review_extra(self) -> None:
        real_import = __import__

        def reject_numpy(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise ModuleNotFoundError("numpy blocked for test")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=reject_numpy):
            with self.assertRaisesRegex(
                ValueError, "img2blockbench\\[semantic-evidence\\]"
            ):
                model_review._numpy()

    def test_delivered_review_rebuilds_but_rejects_model_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            review_output = folder / "review"
            render_model_review(spec_path, review_output, image_size=(96, 96))

            first_build = folder / "first-build"
            build_model(
                spec_path,
                first_build,
                review_manifest=review_output / MANIFEST_NAME,
            )
            delivered_spec = first_build / "review_fixture.model-spec.json"
            second_build = folder / "second-build"
            rebuilt = build_model(delivered_spec, second_build)
            self.assertTrue(Path(rebuilt["bundle"]).is_file())
            self.assertTrue(Path(rebuilt["model_review_manifest"]).is_file())
            self.assertEqual(
                (first_build / "review_fixture.model-review.json").read_bytes(),
                (second_build / "review_fixture.model-review.json").read_bytes(),
            )

            changed = read_json(delivered_spec)
            changed["subject"]["description"] = "Changed after visual review"
            changed_spec = first_build / "changed.model-spec.json"
            write_json(changed_spec, changed)
            with self.assertRaisesRegex(
                ModelSpecError, "content SHA-256 does not match"
            ):
                build_model(changed_spec, folder / "changed-build")

    def test_strict_validation_happens_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            spec["subject"]["uncertainties"] = []
            write_json(spec_path, spec)
            output = folder / "review"

            with self.assertRaisesRegex(ModelSpecError, "strict: record"):
                render_model_review(spec_path, output, image_size=(96, 96))

            self.assertFalse(output.exists())

    def test_build_rejects_review_for_another_or_changed_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            review_output = folder / "review"
            render_model_review(spec_path, review_output, image_size=(96, 96))
            manifest_path = review_output / MANIFEST_NAME
            manifest = read_json(manifest_path)
            manifest["model_id"] = "another_model"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(ModelSpecError, "model_id does not match"):
                build_model(
                    spec_path,
                    folder / "wrong-model-build",
                    review_manifest=manifest_path,
                )

            render_model_review(spec_path, review_output, image_size=(96, 96))
            spec = read_json(spec_path)
            spec["subject"]["description"] = "A changed asymmetric fixture"
            write_json(spec_path, spec)
            with self.assertRaisesRegex(ModelSpecError, "SHA-256 does not match"):
                build_model(
                    spec_path,
                    folder / "stale-review-build",
                    review_manifest=manifest_path,
                )

    def test_build_rejects_non_model_only_or_escaping_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            review_output = folder / "review"
            render_model_review(spec_path, review_output, image_size=(96, 96))
            manifest_path = review_output / MANIFEST_NAME
            manifest = read_json(manifest_path)
            manifest["source_imagery_included"] = True
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(
                ModelSpecError, "source_imagery_included must be False"
            ):
                build_model(
                    spec_path,
                    folder / "source-review-build",
                    review_manifest=manifest_path,
                )

            render_model_review(spec_path, review_output, image_size=(96, 96))
            manifest = read_json(manifest_path)
            manifest["views"][0]["image"] = "../private-reference.png"
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ModelSpecError, "path must be portable"):
                build_model(
                    spec_path,
                    folder / "escaping-review-build",
                    review_manifest=manifest_path,
                )

    def test_review_refuses_to_overwrite_spec_or_reference_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            spec = read_json(spec_path)
            front_reference = folder / "front.png"
            front_reference.write_bytes((folder / "private-reference.png").read_bytes())
            spec["reference"]["image"] = front_reference.name
            write_json(spec_path, spec)
            source_hash = hashlib.sha256(front_reference.read_bytes()).hexdigest()

            with self.assertRaisesRegex(ValueError, "overwrite an input file"):
                render_model_review(spec_path, folder, image_size=(96, 96))
            self.assertEqual(
                source_hash, hashlib.sha256(front_reference.read_bytes()).hexdigest()
            )

            spec["reference"]["image"] = "private-reference.png"
            colliding_spec = folder / MANIFEST_NAME
            write_json(colliding_spec, spec)
            with self.assertRaisesRegex(ValueError, "overwrite an input file"):
                render_model_review(colliding_spec, folder, image_size=(96, 96))
            self.assertEqual(spec, read_json(colliding_spec))

    def test_review_cli_can_package_external_reference_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            review_output = folder / "review"
            build_output = folder / "build"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = img2blockbench.main(
                    [
                        "review",
                        str(spec_path),
                        "--output",
                        str(review_output),
                        "--image-size",
                        "96",
                        "96",
                        "--build-output",
                        str(build_output),
                        "--reference-policy",
                        "external",
                    ]
                )

            self.assertEqual(0, exit_code)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["ok"])
            self.assertTrue(result["agent_visual_review_required"])
            self.assertEqual("external", result["build"]["reference_policy"])
            self.assertTrue(Path(result["manifest"]).is_file())
            self.assertTrue(Path(result["all_angle_sheet"]).is_file())
            self.assertTrue(Path(result["build"]["review_manifest"]).is_file())

    def test_reference_policy_requires_a_requested_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = img2blockbench.main(
                    [
                        "review",
                        str(spec_path),
                        "--output",
                        str(folder / "review"),
                        "--reference-policy",
                        "external",
                    ]
                )

            self.assertEqual(2, exit_code)
            self.assertIn("only affects --build-output", stderr.getvalue())
            self.assertFalse((folder / "review").exists())

    def test_semantic_review_does_not_replace_existing_mesh_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            mesh_source = folder / "mesh-source"
            render_model_review(spec_path, mesh_source, image_size=(96, 96))
            mesh_manifest = read_json(mesh_source / MANIFEST_NAME)
            mesh_manifest["model_spec"] = {
                "content_hash_method": img2blockbench.MODEL_CONTENT_HASH_METHOD,
                "content_sha256": img2blockbench.model_content_sha256(
                    read_json(spec_path)
                ),
            }
            mesh_manifest.pop("all_angle_sheet")
            mesh_manifest["source_mesh"] = {
                "path": "private/source.glb",
                "sha256": "a" * 64,
            }
            for view in mesh_manifest["views"]:
                view["silhouette_iou"] = 1.0
            mesh_manifest_path = mesh_source / "mesh-review.json"
            write_json(mesh_manifest_path, mesh_manifest)

            spec = read_json(spec_path)
            spec["generation"] = {
                "multi_angle_review": {
                    "manifest": mesh_manifest_path.relative_to(folder).as_posix(),
                    "manifest_sha256": hashlib.sha256(
                        mesh_manifest_path.read_bytes()
                    ).hexdigest(),
                }
            }
            write_json(spec_path, spec)
            semantic_output = folder / "semantic-review"
            render_model_review(spec_path, semantic_output, image_size=(96, 96))

            build_output = folder / "dual-review-build"
            result = build_model(
                spec_path,
                build_output,
                reference_policy="external",
                review_manifest=semantic_output / MANIFEST_NAME,
            )
            self.assertNotEqual(
                result["multi_angle_review_manifest"],
                result["model_review_manifest"],
            )
            delivery = read_json(build_output / "review_fixture.model-spec.json")
            self.assertIn("multi_angle_review", delivery["generation"])
            self.assertIn("model_review", delivery["generation"])

    def test_duplicate_render_hashes_warn_without_rejecting_symmetry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            spec_path = self._write_strict_spec(folder)
            background = (13, 20, 28, 255)
            duplicate = Image.new("RGBA", (96, 96), background)
            ImageDraw.Draw(duplicate).rectangle((24, 18, 71, 77), fill="#d9463e")

            with patch("model_review.render_view", return_value=duplicate.copy()):
                manifest = render_model_review(
                    spec_path,
                    folder / "review",
                    image_size=(96, 96),
                    background=background,
                )

            self.assertEqual("complete", manifest["status"])
            self.assertTrue(manifest["complete"])
            self.assertFalse(manifest["gates"]["all_view_hashes_unique"])
            self.assertFalse(manifest["unique_hash_gate"]["passed"])
            self.assertEqual(1, manifest["unique_hash_gate"]["unique_hashes"])
            self.assertTrue(all(manifest["blocking_gates"].values()))
            self.assertEqual(1, len(manifest["warnings"]))
            self.assertTrue(manifest["agent_visual_review_required"])

            stdout = io.StringIO()
            with patch("model_review.render_view", return_value=duplicate.copy()):
                with redirect_stdout(stdout):
                    exit_code = img2blockbench.main(
                        [
                            "review",
                            str(spec_path),
                            "--output",
                            str(folder / "cli-review"),
                            "--image-size",
                            "96",
                            "96",
                        ]
                    )
            self.assertEqual(0, exit_code)

            empty = Image.new("RGBA", (96, 96), background)
            with patch("model_review.render_view", return_value=empty):
                with redirect_stdout(io.StringIO()):
                    incomplete_exit = img2blockbench.main(
                        [
                            "review",
                            str(spec_path),
                            "--output",
                            str(folder / "empty-cli-review"),
                            "--image-size",
                            "96",
                            "96",
                        ]
                    )
            self.assertEqual(1, incomplete_exit)


if __name__ == "__main__":
    unittest.main()
