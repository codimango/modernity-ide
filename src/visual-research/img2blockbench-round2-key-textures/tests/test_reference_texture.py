"""Focused tests for calibrated reference texture baking."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image, ImageDraw

import img2blockbench
import reference_texture
from semantic_evidence import PerspectiveCamera


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReferenceTextureTests(unittest.TestCase):
    """Require visible-only, deterministic, orientation-correct texture transfer."""

    def _write_inputs(
        self,
        folder: Path,
        *,
        color: str | None = None,
        view_id: str = "front",
        image_name: str = "source.png",
        manifest_name: str = "views.json",
        yaw_degrees: float = 0,
    ) -> tuple[Path, Path, PerspectiveCamera]:
        image_path = folder / image_name
        if color is None:
            image = Image.new("RGBA", (64, 64), "#000000")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 31, 31), fill="#ff0000")
            draw.rectangle((32, 0, 63, 31), fill="#00ff00")
            draw.rectangle((0, 32, 31, 63), fill="#0000ff")
            draw.rectangle((32, 32, 63, 63), fill="#ffff00")
        else:
            image = Image.new("RGBA", (64, 64), color)
        image.save(image_path)
        mask_path = folder / f"{Path(image_name).stem}-mask.png"
        Image.new("L", image.size, 255).save(mask_path)
        camera = PerspectiveCamera.from_orbit(
            image.size,
            yaw_degrees=yaw_degrees,
            pitch_degrees=0,
            target=(0, 0, 0),
            distance=12,
            vertical_fov_degrees=60,
        )
        manifest_path = folder / manifest_name
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "views": [
                        {
                            "id": view_id,
                            "image": image_path.name,
                            "image_sha256": _sha256(image_path),
                            "mask": mask_path.name,
                            "mask_sha256": _sha256(mask_path),
                            "camera": camera.as_dict(),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return image_path, manifest_path, camera

    def _spec(self, reference: Path, cubes: list[dict] | None = None) -> dict:
        if cubes is None:
            cubes = [
                {
                    "name": "body",
                    "bone": "root",
                    "center": [0, 0, 0],
                    "size": [4, 4, 4],
                    "rotation": [0, 0, 0],
                    "origin": [0, 0, 0],
                    "role": "test body",
                    "material": "body",
                    "faces": {},
                }
            ]
        return {
            "schema_version": 1,
            "id": "reference_bake_test",
            "reference": {
                "image": reference.name,
                "sha256": _sha256(reference),
                "width": 64,
                "height": 64,
            },
            "subject": {
                "type": "object",
                "description": "A synthetic texture projection fixture",
                "symmetry": "none",
                "uncertainties": ["unseen faces use solid fallback"],
            },
            "quality_contract": {
                "complexity": "simple",
                "target_cuboids": [1, len(cubes)],
                "identity_features": ["four-color source orientation"],
                "required_views": ["front"],
                "review_targets": ["texture"],
            },
            "texture": {
                "density": 2,
                "palette_size": 16,
                "gutter": 1,
                "atlas_size": 64,
            },
            "materials": {
                "body": {
                    "base": "#112233",
                    "shade": "#08111a",
                    "highlight": "#334455",
                    "pattern": "dither",
                    "pattern_scale": 2,
                }
            },
            "bones": [{"name": "root", "parent": None, "pivot": [0, 0, 0]}],
            "cubes": cubes,
            "landmarks": [],
            "collision": {"width": 1, "height": 1, "eye_height": 0.5},
        }

    def test_bake_preserves_source_orientation_and_uses_solid_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, manifest, _ = self._write_inputs(folder)
            spec = self._spec(reference)

            baked, audit = reference_texture.bake_reference_textures(spec, manifest)

            south = img2blockbench.decode_source_texture(
                {
                    "source_texture": baked["cubes"][0]["faces"]["south"][
                        "source_texture"
                    ]
                }
            )
            north = img2blockbench.decode_source_texture(
                {
                    "source_texture": baked["cubes"][0]["faces"]["north"][
                        "source_texture"
                    ]
                }
            )
            assert south is not None and north is not None
            self.assertEqual((255, 0, 0, 255), south.getpixel((0, 0)))
            self.assertEqual((0, 255, 0, 255), south.getpixel((south.width - 1, 0)))
            self.assertEqual((0, 0, 255, 255), south.getpixel((0, south.height - 1)))
            self.assertEqual(
                (255, 255, 0, 255),
                south.getpixel((south.width - 1, south.height - 1)),
            )
            self.assertEqual({(17, 34, 51, 255)}, set(north.get_flattened_data()))
            self.assertFalse(baked["texture"]["quantize_source"])
            self.assertEqual(1, audit["coverage"]["faces_with_source"])
            self.assertEqual(5, audit["coverage"]["fallback_only_faces"])

    def test_side_face_patch_accounts_for_blockbench_uv_flip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, manifest, _ = self._write_inputs(folder, yaw_degrees=90)

            baked, _ = reference_texture.bake_reference_textures(
                self._spec(reference), manifest
            )

            east = img2blockbench.decode_source_texture(
                {
                    "source_texture": baked["cubes"][0]["faces"]["east"][
                        "source_texture"
                    ]
                }
            )
            assert east is not None
            self.assertEqual((0, 255, 0, 255), east.getpixel((0, 0)))
            self.assertEqual((255, 0, 0, 255), east.getpixel((east.width - 1, 0)))
            self.assertEqual(
                (255, 255, 0, 255), east.getpixel((0, east.height - 1))
            )
            self.assertEqual(
                (0, 0, 255, 255),
                east.getpixel((east.width - 1, east.height - 1)),
            )

    def test_occluded_face_never_receives_foreground_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, manifest, _ = self._write_inputs(folder, color="#ff0000")
            cubes = [
                {
                    "name": name,
                    "bone": "root",
                    "center": [0, 0, z],
                    "size": [4, 4, 4],
                    "rotation": [0, 0, 0],
                    "origin": [0, 0, z],
                    "role": f"{name} test cube",
                    "material": "body",
                    "faces": {},
                }
                for name, z in (("front", 3), ("rear", 0))
            ]
            spec = self._spec(reference, cubes)

            baked, audit = reference_texture.bake_reference_textures(spec, manifest)
            rear_record = next(
                record
                for record in audit["faces"]
                if record["cube"] == "rear" and record["face"] == "south"
            )
            rear = next(cube for cube in baked["cubes"] if cube["name"] == "rear")
            patch = img2blockbench.decode_source_texture(
                {"source_texture": rear["faces"]["south"]["source_texture"]}
            )
            assert patch is not None
            self.assertEqual(0, rear_record["source_texels"])
            self.assertEqual({(17, 34, 51, 255)}, set(patch.get_flattened_data()))

    def test_foreground_mask_blocks_background_texture_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, manifest, _ = self._write_inputs(folder, color="#ff0000")
            data = json.loads(manifest.read_text(encoding="utf-8"))
            mask_path = folder / data["views"][0]["mask"]
            mask = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(mask).rectangle((0, 0, 31, 63), fill=255)
            mask.save(mask_path)
            data["views"][0]["mask_sha256"] = _sha256(mask_path)
            manifest.write_text(json.dumps(data), encoding="utf-8")

            baked, audit = reference_texture.bake_reference_textures(
                self._spec(reference), manifest
            )
            south = img2blockbench.decode_source_texture(
                {
                    "source_texture": baked["cubes"][0]["faces"]["south"][
                        "source_texture"
                    ]
                }
            )
            assert south is not None
            self.assertEqual((255, 0, 0, 255), south.getpixel((0, 0)))
            self.assertEqual(
                (17, 34, 51, 255), south.getpixel((south.width - 1, 0))
            )
            south_record = next(
                record
                for record in audit["faces"]
                if record["cube"] == "body" and record["face"] == "south"
            )
            self.assertGreater(south_record["source_texels"], 0)
            self.assertGreater(south_record["fallback_texels"], 0)

    def test_equal_incidence_uses_lexicographic_view_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            red, _, camera = self._write_inputs(
                folder,
                color="#ff0000",
                view_id="z-view",
                image_name="red.png",
                manifest_name="unused.json",
            )
            green, _, _ = self._write_inputs(
                folder,
                color="#00ff00",
                view_id="a-view",
                image_name="green.png",
                manifest_name="unused-two.json",
            )
            records = []
            for view_id, image_path in (("z-view", red), ("a-view", green)):
                mask_path = folder / f"{image_path.stem}-mask.png"
                records.append(
                    {
                        "id": view_id,
                        "image": image_path.name,
                        "image_sha256": _sha256(image_path),
                        "mask": mask_path.name,
                        "mask_sha256": _sha256(mask_path),
                        "camera": camera.as_dict(),
                    }
                )
            manifest = folder / "views.json"
            manifest.write_text(
                json.dumps({"schema_version": 1, "views": records}),
                encoding="utf-8",
            )
            spec = self._spec(red)

            first, first_audit = reference_texture.bake_reference_textures(spec, manifest)
            second, second_audit = reference_texture.bake_reference_textures(spec, manifest)
            patch = img2blockbench.decode_source_texture(
                {
                    "source_texture": first["cubes"][0]["faces"]["south"][
                        "source_texture"
                    ]
                }
            )
            assert patch is not None
            self.assertEqual({(0, 255, 0, 255)}, set(patch.get_flattened_data()))
            self.assertEqual(first, second)
            self.assertEqual(first_audit, second_audit)
            self.assertGreater(first_audit["views"][0]["selected_source_texels"], 0)
            self.assertEqual(0, first_audit["views"][1]["selected_source_texels"])

    def test_hash_mismatch_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, manifest, _ = self._write_inputs(folder)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["views"][0]["image_sha256"] = "0" * 64
            manifest.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                reference_texture.bake_reference_textures(
                    self._spec(reference), manifest
                )

    def test_cli_writes_a_strict_buildable_spec_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, manifest, _ = self._write_inputs(folder)
            spec_path = folder / "input.json"
            img2blockbench.write_json(spec_path, self._spec(reference))
            output = folder / "nested" / "baked.json"
            audit = folder / "nested" / "texture-audit.json"

            with redirect_stdout(io.StringIO()):
                exit_code = img2blockbench.main(
                    [
                        "bake-reference-textures",
                        str(spec_path),
                        "--views",
                        str(manifest),
                        "--output",
                        str(output),
                        "--audit",
                        str(audit),
                        "--atlas-size",
                        "1024",
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())
            self.assertTrue(audit.is_file())
            baked = img2blockbench.validated_spec(output, strict=True)
            self.assertEqual(1024, baked["texture"]["atlas_size"])
            self.assertEqual(
                reference_texture.ALGORITHM,
                baked["generation"]["texture_transfer"]["algorithm"],
            )
            self.assertEqual(
                1024,
                baked["generation"]["texture_transfer"]["texture"][
                    "resolved_atlas_size"
                ],
            )
            self.assertTrue(img2blockbench.build_texture(baked)[0].getbbox())
            self.assertTrue(
                img2blockbench.build_model(output, folder / "build")["audit"]["ok"]
            )

    def test_input_is_unchanged_and_large_atlases_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, manifest, _ = self._write_inputs(folder)
            spec = self._spec(reference)
            original = copy.deepcopy(spec)
            legacy_texture = img2blockbench.png_bytes(
                img2blockbench.build_texture(spec)[0]
            )

            baked, _ = reference_texture.bake_reference_textures(
                spec,
                manifest,
                reference_texture.ReferenceTextureBakeOptions(
                    texture_density=4,
                    atlas_size=1024,
                ),
            )

            self.assertEqual(original, spec)
            self.assertEqual(
                legacy_texture,
                img2blockbench.png_bytes(img2blockbench.build_texture(spec)[0]),
            )
            self.assertEqual([], img2blockbench.validate_spec(baked, strict=True))
            self.assertEqual(1024, img2blockbench.pack_faces(baked)[0])
            baked["texture"]["atlas_size"] = 2048
            self.assertEqual([], img2blockbench.validate_spec(baked, strict=True))
            self.assertEqual(2048, img2blockbench.pack_faces(baked)[0])

    def test_source_region_requires_an_effective_source_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference, _, _ = self._write_inputs(folder)
            spec = self._spec(reference)
            spec["cubes"][0]["faces"]["south"] = {
                "source_region": [0, 0, 1, 1]
            }

            errors = img2blockbench.validate_spec(spec, strict=True)

            self.assertTrue(
                any("requires an effective source_texture" in error for error in errors)
            )


if __name__ == "__main__":
    unittest.main()
