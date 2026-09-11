import base64
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


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "fox" / "model-spec.json"


class Img2BlockbenchTests(unittest.TestCase):
    def test_geometry_precision_is_independent_from_texture_density(self):
        spec = img2blockbench.read_json(EXAMPLE)
        spec["texture"]["density"] = 1
        spec["geometry"] = {"precision": 32}
        cube = spec["cubes"][0]
        cube["center"][0] = 0.03125
        cube["size"][0] = 1.0625

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        texture, placements = img2blockbench.build_texture(spec)
        bbmodel = img2blockbench.make_bbmodel(
            spec,
            img2blockbench.png_bytes(texture),
            texture.width,
            placements,
        )
        element = bbmodel["elements"][0]
        self.assertEqual(32, bbmodel["img2blockbench"]["geometry_precision"])
        self.assertEqual(1, bbmodel["img2blockbench"]["texture_density"])
        self.assertEqual(-0.5, element["from"][0])
        self.assertEqual(0.5625, element["to"][0])
        self.assertEqual(2, placements[(cube["name"], "south")][2])

        del spec["geometry"]
        legacy_minimum, legacy_maximum = img2blockbench.exported_cube_bounds(
            spec,
            cube,
        )
        self.assertEqual(-0.5, legacy_minimum[0])
        self.assertEqual(0.5, legacy_maximum[0])

    def test_oriented_reconstruction_preserves_a_thin_diagonal(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "diagonal.png"
            mask_path = folder / "diagonal-mask.png"
            depth_path = folder / "diagonal-depth.png"
            source = Image.new("RGB", (180, 160), "#1c242d")
            source_draw = ImageDraw.Draw(source)
            shaft = ((12, 18), (18, 12), (157, 132), (151, 139))
            guard = ((126, 104), (133, 98), (158, 111), (151, 118))
            source_draw.polygon(shaft, fill="#e8d79b")
            source_draw.polygon(guard, fill="#d7a82e")
            source.save(reference)

            mask = Image.new("L", source.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.polygon(shaft, fill=255)
            mask_draw.polygon(guard, fill=255)
            mask.save(mask_path)
            depth = Image.new("L", source.size, 0)
            depth_draw = ImageDraw.Draw(depth)
            depth_draw.polygon(shaft, fill=100)
            depth_draw.polygon(guard, fill=220)
            depth.save(depth_path)

            options = img2blockbench.PhotoReconstructionOptions(
                analysis_size=128,
                grid_size=96,
                max_cuboids=80,
                target_size=36,
                target_depth=8,
                relief_layers=3,
                geometry_precision=32,
                texture_density=1,
                foreground_mask=mask_path,
                depth_map=depth_path,
                depth_mode="symmetric",
                decomposition="oriented",
                mask_coverage=0.04,
            )
            output = folder / "diagonal.json"
            first, segmentation = img2blockbench.reconstruct_photo_spec(
                reference,
                output,
                "thin_diagonal",
                "A thin diagonal object",
                "object",
                options,
            )
            second, _ = img2blockbench.reconstruct_photo_spec(
                reference,
                output,
                "thin_diagonal",
                "A thin diagonal object",
                "object",
                options,
            )

            self.assertEqual(first, second)
            self.assertEqual("external-mask", segmentation.method)
            self.assertEqual(
                "principal-axis-depthfield-cuboids-v3",
                first["generation"]["algorithm"],
            )
            orientation = first["generation"]["relief"]["orientation"]
            self.assertEqual("mask-pca", orientation["selection"])
            self.assertGreater(abs(orientation["source_angle_degrees"]), 25)
            self.assertGreater(orientation["principal_axis_ratio"], 20)
            self.assertEqual(32, first["geometry"]["precision"])
            self.assertEqual(1, first["texture"]["density"])
            self.assertTrue(
                all(abs(cube["rotation"][2]) > 25 for cube in first["cubes"])
            )
            self.assertLessEqual(len(first["cubes"]), options.max_cuboids)

            img2blockbench.write_json(output, first)
            result = img2blockbench.build_model(output, folder / "build")
            self.assertTrue(result["audit"]["ok"])
            atlas, placements = img2blockbench.build_texture(first)
            evidence = img2blockbench.render_relief_evidence(
                first,
                reference,
                atlas,
                placements,
                folder / "render",
            )
            self.assertGreater(evidence["reprojected_fraction"], 0.03)
            self.assertGreater(evidence["silhouette_iou"], 0.85)
            self.assertGreater(evidence["silhouette_recall"], 0.9)
            self.assertTrue((folder / "render" / "isometric.png").is_file())
            self.assertTrue((folder / "render" / "profile.png").is_file())

    def test_oriented_segmentation_keeps_long_thin_connected_parts(self):
        source = Image.new("RGB", (180, 100), "#315d3c")
        draw = ImageDraw.Draw(source)
        draw.ellipse((30, 25, 100, 82), fill="#f0c92d")
        draw.line((92, 52, 169, 52), fill="#f0c92d", width=3)

        segmentation = img2blockbench.segment_foreground(
            source,
            img2blockbench.PhotoReconstructionOptions(
                analysis_size=180,
                decomposition="oriented",
            ),
        )

        self.assertGreaterEqual(segmentation.bbox[2], 168)
        self.assertLessEqual(segmentation.bbox[0], 31)

    def test_external_mask_depth_map_builds_symmetric_adaptive_volume(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "vehicle.png"
            mask_path = folder / "vehicle-mask.png"
            depth_path = folder / "vehicle-depth.png"
            source = Image.new("RGB", (180, 100), "#27445e")
            draw = ImageDraw.Draw(source)
            draw.rectangle((0, 60, 179, 99), fill="#d4b88b")
            draw.rounded_rectangle((35, 36, 150, 79), radius=12, fill="#b9c1c8")
            draw.rectangle((72, 23, 125, 55), fill="#697782")
            source.save(reference)

            mask = Image.new("L", source.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle((35, 36, 150, 79), radius=12, fill=255)
            mask_draw.rectangle((72, 23, 125, 55), fill=255)
            mask.save(mask_path)

            depth = Image.new("L", source.size, 0)
            depth_draw = ImageDraw.Draw(depth)
            depth_draw.rounded_rectangle((35, 36, 150, 79), radius=12, fill=90)
            depth_draw.rectangle((48, 43, 140, 70), fill=175)
            depth_draw.rectangle((72, 27, 125, 57), fill=255)
            depth.save(depth_path)

            options = img2blockbench.PhotoReconstructionOptions(
                analysis_size=80,
                grid_size=40,
                max_cuboids=45,
                target_depth=12,
                relief_layers=3,
                foreground_mask=mask_path,
                subject_bbox=(30, 18, 156, 84),
                depth_map=depth_path,
                depth_mode="symmetric",
                decomposition="adaptive",
            )
            output = folder / "vehicle.json"
            first, segmentation = img2blockbench.reconstruct_photo_spec(
                reference,
                output,
                "masked_vehicle",
                "A hard-surface test vehicle",
                "vehicle",
                options,
            )
            second, _ = img2blockbench.reconstruct_photo_spec(
                reference,
                output,
                "masked_vehicle",
                "A hard-surface test vehicle",
                "vehicle",
                options,
            )

            self.assertEqual(first, second)
            self.assertEqual("external-mask+subject-bbox", segmentation.method)
            self.assertEqual((35, 23, 151, 80), segmentation.bbox)
            self.assertEqual(
                "ray-depthfield-adaptive-cuboids-v2",
                first["generation"]["algorithm"],
            )
            relief = first["generation"]["relief"]
            self.assertEqual("symmetric", relief["depth_mode"])
            self.assertEqual("adaptive", relief["decomposition"])
            self.assertEqual(3, relief["layers"])
            self.assertEqual(
                hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                first["generation"]["segmentation"]["input_mask"]["sha256"],
            )
            self.assertEqual(
                hashlib.sha256(depth_path.read_bytes()).hexdigest(),
                relief["depth_map"]["sha256"],
            )
            self.assertEqual({0.0}, {cube["center"][2] for cube in first["cubes"]})
            self.assertEqual(
                {4.0, 8.0, 12.0},
                {cube["size"][2] for cube in first["cubes"]},
            )
            outer = [
                cube
                for cube in first["cubes"]
                if cube["role"] == "foreground relief shell 1"
            ]
            left = min(cube["center"][0] - cube["size"][0] / 2 for cube in outer)
            right = max(cube["center"][0] + cube["size"][0] / 2 for cube in outer)
            self.assertAlmostEqual(options.target_size, right - left)
            self.assertTrue(
                all(
                    "source_region" in cube["faces"]["south"]
                    and "source_region" in cube["faces"]["north"]
                    for cube in first["cubes"]
                )
            )
            embedded = img2blockbench.decode_source_texture(
                first["materials"]["reference_photo"]
            )
            self.assertIsNotNone(embedded)
            self.assertEqual(0, embedded.getpixel((0, 0))[3])
            center = embedded.getpixel(
                (embedded.width // 2, embedded.height // 2)
            )
            self.assertGreater(center[3], 0)
            img2blockbench.write_json(output, first)
            self.assertTrue(img2blockbench.build_model(output, folder / "build")["audit"]["ok"])

    def test_subject_bbox_is_an_auto_segmentation_roi_not_a_solid_mask(self):
        source = Image.new("RGB", (120, 80), "#25663a")
        draw = ImageDraw.Draw(source)
        draw.ellipse((45, 32, 72, 51), fill="#e6c323")
        options = img2blockbench.PhotoReconstructionOptions(
            analysis_size=80,
            subject_bbox=(20, 15, 100, 70),
        )
        segmentation = img2blockbench.segment_foreground(source, options)
        self.assertTrue(segmentation.method.startswith("subject-bbox-roi/"))
        self.assertEqual((20, 15, 100, 70), segmentation.requested_bbox)
        self.assertLess(segmentation.bbox[0], 50)
        self.assertGreater(segmentation.bbox[2], 68)
        self.assertLess(segmentation.foreground_fraction, 0.2)

    def test_external_mask_requires_source_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "source.png"
            mask_path = folder / "mask.png"
            Image.new("RGB", (48, 32), "#ffffff").save(reference)
            Image.new("L", (24, 16), 255).save(mask_path)
            options = img2blockbench.PhotoReconstructionOptions(
                foreground_mask=mask_path
            )
            with self.assertRaisesRegex(ValueError, "dimensions must exactly match"):
                img2blockbench.reconstruct_photo_spec(
                    reference,
                    folder / "model.json",
                    "bad_mask",
                    "Mismatched input",
                    "object",
                    options,
                )

    def test_photo_relief_reconstruction_is_deterministic_and_buildable(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "photo.png"
            image = Image.new("RGB", (160, 100), "#527648")
            draw = ImageDraw.Draw(image)
            draw.ellipse((28, 24, 136, 82), fill="#f1c91b")
            draw.polygon(((24, 48), (4, 58), (30, 62)), fill="#d99035")
            draw.ellipse((43, 36, 51, 44), fill="#111820")
            draw.polygon(((82, 45), (145, 58), (91, 67)), fill="#16191f")
            image.save(reference)

            options = img2blockbench.PhotoReconstructionOptions(
                analysis_size=64,
                grid_size=48,
                max_cuboids=60,
            )
            first_path = folder / "first.json"
            second_path = folder / "second.json"
            first, segmentation = img2blockbench.reconstruct_photo_spec(
                reference,
                first_path,
                "photo_bird",
                "A synthetic bird-like subject",
                "bird",
                options,
            )
            second, _ = img2blockbench.reconstruct_photo_spec(
                reference,
                second_path,
                "photo_bird",
                "A synthetic bird-like subject",
                "bird",
                options,
            )
            self.assertEqual(first, second)
            self.assertEqual("photo-relief", first["generation"]["lane"])
            self.assertEqual("photo.png", first["reference"]["image"])
            self.assertLessEqual(len(first["cubes"]), 60)
            self.assertGreater(len(first["cubes"]), 1)
            self.assertLess(segmentation.foreground_fraction, 0.75)
            projected = [
                cube
                for cube in first["cubes"]
                if "source_region" in cube.get("faces", {}).get("south", {})
            ]
            self.assertTrue(projected)
            self.assertGreater(first["generation"]["relief"]["layers"], 1)
            for cube in projected:
                region = cube["faces"]["south"]["source_region"]
                self.assertLess(region[0], region[2])
                self.assertLess(region[1], region[3])

            img2blockbench.write_json(first_path, first)
            result = img2blockbench.build_model(first_path, folder / "build")
            self.assertTrue(result["audit"]["ok"])
            atlas, placements = img2blockbench.build_texture(first)
            evidence = img2blockbench.render_relief_evidence(
                first,
                reference,
                atlas,
                placements,
                folder / "render",
            )
            self.assertGreater(evidence["texture_psnr_db"], 15)
            self.assertTrue((folder / "render" / "comparison-sheet.png").is_file())

            cli_path = folder / "cli.json"
            with redirect_stdout(io.StringIO()):
                exit_code = img2blockbench.main(
                    [
                        "from-image",
                        str(reference),
                        "--id",
                        "photo_bird_cli",
                        "--description",
                        "A CLI reconstruction",
                        "--output",
                        str(cli_path),
                        "--grid-size",
                        "32",
                        "--max-cuboids",
                        "50",
                    ]
                )
            self.assertEqual(0, exit_code)
            self.assertEqual(
                "photo.png",
                img2blockbench.read_json(cli_path)["reference"]["image"],
            )
            self.assertNotIn("geometry", img2blockbench.read_json(cli_path))

    def test_source_region_samples_only_declared_image_area(self):
        source = Image.new("RGBA", (4, 2))
        source.putdata(
            [(255, 0, 0, 255)] * 4 + [(0, 0, 255, 255)] * 4
        )
        material = {
            "source_texture": {
                "repeat": [1, 1],
                "offset": [0, 0],
                "center": [0, 0],
                "rotation": 0,
                "wrap": [1001, 1001],
                "flip_y": True,
            }
        }
        top = img2blockbench.source_texture_pixel(
            material,
            source,
            0,
            0,
            1,
            1,
            [0, 0, 1, 0.5],
        )
        bottom = img2blockbench.source_texture_pixel(
            material,
            source,
            0,
            0,
            1,
            1,
            [0, 0.5, 1, 1],
        )
        self.assertEqual((255, 0, 0, 255), top)
        self.assertEqual((0, 0, 255, 255), bottom)

    def test_invalid_source_region_is_rejected(self):
        spec = copy.deepcopy(img2blockbench.read_json(EXAMPLE))
        spec["cubes"][0]["faces"]["south"] = {
            "source_region": [0.8, 0.1, 0.2, 0.9]
        }
        errors = img2blockbench.validate_spec(spec, strict=True)
        self.assertTrue(any("source_region" in error for error in errors))

    def test_public_json_reports_do_not_embed_local_home_paths(self):
        for path in (ROOT / "examples").rglob("*.json"):
            contents = path.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", contents, str(path))
            self.assertNotIn("/home/", contents, str(path))
            self.assertNotIn(":\\Users\\", contents, str(path))

    def test_mesh_guided_examples_record_provider_and_source_hash(self):
        for animal in (
            "platypus",
            "chimpanzee",
            "elephant",
            "tiger",
            "coyote",
        ):
            lane = ROOT / "examples" / animal / "lane2"
            provenance = img2blockbench.read_json(lane / "provenance.json")
            source = lane / "source.glb"
            mesh_source = provenance["mesh_source"]

            self.assertEqual("glb", mesh_source["format"])
            self.assertTrue(mesh_source["provider"])
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                mesh_source["sha256"],
            )

    def test_cycle_four_nian_is_a_bounded_semantic_hybrid(self):
        spec = img2blockbench.read_json(
            ROOT / "benchmarks" / "cycles" / "04-nian" / "model-spec.json"
        )
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual(
            "agent-authored-semantic-hybrid",
            spec["generation"]["lane"],
        )
        self.assertNotIn("relief", {cube["bone"] for cube in spec["cubes"]})
        semantic = [
            cube
            for cube in spec["cubes"]
            if cube["role"] != "attached source-side silhouette skin"
        ]
        skin = [
            cube
            for cube in spec["cubes"]
            if cube["role"] == "attached source-side silhouette skin"
        ]
        self.assertEqual(80, len(semantic))
        self.assertEqual([], skin)
        self.assertTrue(spec["texture"]["quantize_source"])
        self.assertEqual(32, spec["texture"]["palette_size"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in semantic
                for override in cube.get("faces", {}).values()
            )
        )
        self.assertTrue(
            spec["generation"]["source_facing_texture"]["bilateral_landmarks"]
        )
        semantic_parts = spec["generation"]["semantic_parts"]
        self.assertEqual(
            80,
            semantic_parts["body_volumes"]
            + semantic_parts["head_and_face"]
            + semantic_parts["fangs"]
            + semantic_parts["mane_volumes"]
            + semantic_parts["horn_segments"]
            + semantic_parts["limb_chains"] * semantic_parts["limb_segments_per_chain"]
            + semantic_parts["attached_claws"]
            + semantic_parts["front_paw_pads"]
            + semantic_parts["surface_decal_cuboids"]
            + semantic_parts["tail_segments"],
        )
        self.assertEqual(2, semantic_parts["pixel_motif_faces"])
        cubes = {cube["name"]: cube for cube in semantic}
        self.assertGreaterEqual(
            cubes["shoulder_mass"]["size"][0] / cubes["pelvis_mass"]["size"][0],
            2.0,
        )
        trunk_names = ("pelvis_mass", "torso_core", "ribcage", "shoulder_mass")
        trunk_rear = min(
            cubes[name]["center"][2] - cubes[name]["size"][2] / 2
            for name in trunk_names
        )
        trunk_front = max(
            cubes[name]["center"][2] + cubes[name]["size"][2] / 2
            for name in trunk_names
        )
        self.assertLessEqual(trunk_front - trunk_rear, 16.5)
        shoulder_top = (
            cubes["shoulder_mass"]["center"][1]
            + cubes["shoulder_mass"]["size"][1] / 2
        )
        rump_top = (
            cubes["pelvis_mass"]["center"][1]
            + cubes["pelvis_mass"]["size"][1] / 2
        )
        self.assertGreaterEqual(shoulder_top - rump_top, 10.5)
        self.assertGreater(
            cubes["front_near_upper"]["size"][0],
            cubes["rear_near_upper"]["size"][0] * 1.7,
        )
        self.assertEqual(
            [10, 8, 12],
            [
                abs(cubes[name]["rotation"][0])
                for name in (
                    "front_near_upper",
                    "front_near_lower",
                    "front_near_paw",
                )
            ],
        )
        self.assertLessEqual(cubes["front_near_paw"]["size"][2], 3.2)
        self.assertLessEqual(cubes["front_near_paw_pad"]["size"][2], 1.8)
        self.assertFalse(
            any(cube["role"].startswith("raised near-") for cube in semantic)
        )
        motif_sizes = {
            "rump_spiral_decal": (10, 14),
            "front_near_upper": (13, 22),
        }
        for cube_name, motif_size in motif_sizes.items():
            self.assertNotIn("east", cubes[cube_name]["faces"])
            source = cubes[cube_name]["faces"]["west"]["source_texture"]
            decoded = img2blockbench.decode_source_texture(
                {"source_texture": source}
            )
            self.assertIsNotNone(decoded)
            assert decoded is not None
            self.assertEqual(motif_size, decoded.size)
            self.assertEqual((255, 255), decoded.getextrema()[3])
            self.assertGreaterEqual(
                len(decoded.getcolors(maxcolors=1024) or []),
                5,
            )
        self.assertLessEqual(cubes["rump_spiral_decal"]["size"][0], 0.125)
        self.assertLessEqual(cubes["muzzle"]["size"][2], 3.5)
        self.assertEqual(
            4,
            len(
                {
                    cube["center"][2]
                    for cube in spec["cubes"]
                    if cube["name"] in {
                        "rear_near_upper",
                        "rear_far_upper",
                        "front_near_upper",
                        "front_far_upper",
                    }
                }
            ),
        )
        for side in ("near", "far"):
            horn = [
                cubes[f"horn_{side}_{segment}"]
                for segment in ("base", "mid", "curve", "return", "tip")
            ]
            self.assertEqual(5, len(horn))
            self.assertTrue(
                all(segment["material"] == "horn_brown" for segment in horn[:-1])
            )
            self.assertEqual("horn_tip", horn[-1]["material"])
            self.assertGreaterEqual(
                abs(horn[2]["center"][0]) - abs(horn[0]["center"][0]),
                4.5,
            )
            self.assertGreaterEqual(
                horn[-1]["center"][2] - horn[2]["center"][2],
                4.5,
            )
            self.assertLess(horn[3]["size"][0], horn[0]["size"][0] * 0.6)
            self.assertGreaterEqual(abs(horn[2]["center"][0]), 10.5)
            self.assertGreaterEqual(horn[-1]["center"][2], 22)
            self.assertGreaterEqual(abs(horn[-1]["rotation"][2]), 25)
            self.assertLessEqual(abs(horn[-1]["rotation"][2]), 35)

    def test_lane3_preserves_native_threejs_texture_transforms(self):
        for animal in (
            "platypus",
            "chimpanzee",
            "elephant",
            "tiger",
            "coyote",
        ):
            lane = ROOT / "examples" / animal / "lane3"
            spec = img2blockbench.read_json(lane / "model-spec.json")
            audit = img2blockbench.read_json(lane / "projection-audit.json")
            self.assertEqual(
                "img2threejs-native-albedo-transfer",
                audit["algorithm"],
            )
            self.assertTrue(audit["preserved_texture_transforms"])
            self.assertFalse(audit["palette_quantization"])
            self.assertFalse(spec["texture"]["quantize_source"])
            for material_name, material in spec["materials"].items():
                source = material["source_texture"]
                self.assertEqual(
                    audit["texture_transforms"][material_name]["repeat"],
                    source["repeat"],
                )
                self.assertEqual([1000, 1000], source["wrap"])
                self.assertEqual([3, 3], source["repeat"])
                self.assertTrue(source["flip_y"])

    def test_lane3_recipes_never_paint_front_and_side_eyes(self):
        recipes = img2blockbench.read_json(
            ROOT / "tools" / "img2threejs" / "semantic-recipes.json"
        )
        for animal, recipe in recipes.items():
            eye_faces = {
                landmark["face"]
                for landmark in recipe["landmarks"]
                if "eye" in landmark["name"]
                and "glint" not in landmark["name"]
            }
            self.assertFalse(
                eye_faces.intersection({"south", "north"})
                and eye_faces.intersection({"east", "west"}),
                animal,
            )

    def test_example_is_strictly_valid(self):
        spec = img2blockbench.read_json(EXAMPLE)
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))

    def test_probe_and_new_create_valid_starter(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            image_path = folder / "reference.png"
            Image.new("RGB", (64, 32), "#b95832").save(image_path)
            probe = img2blockbench.image_probe(image_path)
            self.assertEqual((probe["width"], probe["height"]), (64, 32))
            output = folder / "model-spec.json"
            starter = img2blockbench.starter_spec(
                image_path,
                output,
                "test_fox",
                "A test fox",
                "moderate",
            )
            self.assertEqual([], img2blockbench.validate_spec(starter))
            self.assertTrue(img2blockbench.validate_spec(starter, strict=True))

    def test_build_is_audited_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            first = folder / "first"
            second = folder / "second"
            result = img2blockbench.build_model(EXAMPLE, first)
            img2blockbench.build_model(EXAMPLE, second)
            self.assertTrue(result["audit"]["ok"])
            self.assertEqual(
                (first / "fox.zip").read_bytes(),
                (second / "fox.zip").read_bytes(),
            )
            bbmodel = img2blockbench.read_json(first / "fox.bbmodel")
            self.assertTrue(img2blockbench.audit_bbmodel(bbmodel)["ok"])
            self.assertTrue((first / "fox.geo.json").exists())
            self.assertTrue((first / "fox.png").exists())
            manifest = img2blockbench.read_json(first / "fox.manifest.json")
            self.assertEqual("direct", manifest["generator"]["lane"])

    def test_missing_bone_is_rejected(self):
        spec = copy.deepcopy(img2blockbench.read_json(EXAMPLE))
        spec["cubes"][0]["bone"] = "missing"
        errors = img2blockbench.validate_spec(spec, strict=True)
        self.assertTrue(any("missing bone" in error for error in errors))

    def test_threejs_factory_uses_same_cuboids(self):
        spec = img2blockbench.read_json(EXAMPLE)
        factory = img2blockbench.make_threejs_factory(spec)
        self.assertIn("export function createFoxModel(): THREE.Group", factory)
        self.assertEqual(len(spec["cubes"]), factory.count("new THREE.BoxGeometry("))
        self.assertIn('representation: "minecraft-cuboids"', factory)

    def test_imports_constrained_threejs_scene(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "reference.png"
            Image.new("RGB", (64, 32), "#70451f").save(reference)
            scene = {
                "metadata": {
                    "version": 4.7,
                    "type": "Object",
                    "generator": "Object3D.toJSON",
                },
                "geometries": [
                    {
                        "uuid": "geometry",
                        "type": "BoxGeometry",
                        "width": 8,
                        "height": 5,
                        "depth": 12,
                    }
                ],
                "materials": [
                    {
                        "uuid": "material",
                        "type": "MeshBasicMaterial",
                        "name": "brown_fur",
                        "color": 0x70451F,
                    }
                ],
                "object": {
                    "uuid": "root",
                    "type": "Group",
                    "name": "test",
                    "matrix": identity,
                    "children": [
                        {
                            "uuid": "pivot",
                            "type": "Group",
                            "name": "body_pivot",
                            "matrix": identity[:12] + [0, 7, 0, 1],
                            "userData": {
                                "img2blockbench": {
                                    "bone": "body",
                                    "parent": "root",
                                    "role": "main body",
                                }
                            },
                            "children": [
                                {
                                    "uuid": "mesh",
                                    "type": "Mesh",
                                    "name": "body",
                                    "matrix": identity,
                                    "geometry": "geometry",
                                    "material": ["material"] * 6,
                                }
                            ],
                        }
                    ],
                },
            }
            scene_path = folder / "scene.json"
            scene_path.write_text(json.dumps(scene))
            output = folder / "model-spec.json"
            spec = img2blockbench.import_threejs_scene(
                scene_path,
                reference,
                output,
                "threejs_test",
                "A procedural test model",
            )
            self.assertEqual(1, len(spec["cubes"]))
            self.assertEqual("brown_fur", spec["cubes"][0]["material"])
            self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))

    def test_imports_img2threejs_scaled_pivots_and_physical_materials(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "reference.png"
            Image.new("RGB", (64, 32), "#6f4525").save(reference)
            scene = {
                "geometries": [
                    {
                        "uuid": "geometry",
                        "type": "BoxGeometry",
                        "width": 1,
                        "height": 1,
                        "depth": 1,
                    }
                ],
                "materials": [
                    {
                        "uuid": "material",
                        "type": "MeshPhysicalMaterial",
                        "color": 0xFFFFFF,
                        "userData": {
                            "sculptMaterial": {
                                "id": "fur",
                                "baseColor": "#6f4525",
                                "colorVariation": {
                                    "palette": [
                                        "#6f4525",
                                        "#4c2d1c",
                                        "#946039",
                                    ]
                                },
                            }
                        },
                    }
                ],
                "object": {
                    "uuid": "root",
                    "type": "Group",
                    "matrix": identity,
                    "children": [
                        {
                            "uuid": "pivot",
                            "type": "Group",
                            "name": "body_pivot",
                            "matrix": [8, 0, 0, 0, 0, 5, 0, 0, 0, 0, 12, 0, 0, 7, 0, 1],
                            "children": [
                                {
                                    "uuid": "mesh",
                                    "type": "Mesh",
                                    "name": "body",
                                    "matrix": identity,
                                    "geometry": "geometry",
                                    "material": "material",
                                }
                            ],
                        }
                    ],
                },
            }
            scene_path = folder / "scene.json"
            scene_path.write_text(json.dumps(scene))
            spec = img2blockbench.import_threejs_scene(
                scene_path,
                reference,
                folder / "model-spec.json",
                "img2threejs_test",
                "An official img2threejs-style scene",
            )
            self.assertEqual([8, 5, 12], spec["cubes"][0]["size"])
            self.assertEqual([0, 7, 0], spec["cubes"][0]["center"])
            material = spec["materials"][spec["cubes"][0]["material"]]
            self.assertEqual("#6f4525", material["base"])
            self.assertEqual("fur", material["source_material_id"])
            self.assertEqual(
                ["#6f4525", "#4c2d1c", "#946039"],
                material["reference_palette"],
            )
            self.assertEqual("threejs", spec["generation"]["lane"])

    def test_imports_and_bakes_img2threejs_albedo_map(self):
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        source_image = Image.new("RGBA", (2, 2))
        source_image.putdata(
            [
                (255, 0, 0, 255),
                (0, 255, 0, 255),
                (0, 0, 255, 255),
                (255, 255, 0, 255),
            ]
        )
        buffer = io.BytesIO()
        source_image.save(buffer, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(
            buffer.getvalue()
        ).decode("ascii")

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "reference.png"
            Image.new("RGB", (64, 32), "#6f4525").save(reference)
            scene = {
                "geometries": [
                    {
                        "uuid": "geometry",
                        "type": "BoxGeometry",
                        "width": 4,
                        "height": 4,
                        "depth": 4,
                    }
                ],
                "materials": [
                    {
                        "uuid": "material",
                        "type": "MeshPhysicalMaterial",
                        "color": 0xFFFFFF,
                        "map": "texture",
                    }
                ],
                "textures": [
                    {
                        "uuid": "texture",
                        "image": "image",
                        "repeat": [1, 1],
                        "offset": [0, 0],
                        "center": [0, 0],
                        "rotation": 0,
                        "wrap": [1001, 1001],
                        "flipY": True,
                    }
                ],
                "images": [{"uuid": "image", "url": data_uri}],
                "object": {
                    "uuid": "root",
                    "type": "Group",
                    "matrix": identity,
                    "children": [
                        {
                            "uuid": "pivot",
                            "type": "Group",
                            "name": "body_pivot",
                            "matrix": identity,
                            "children": [
                                {
                                    "uuid": "mesh",
                                    "type": "Mesh",
                                    "name": "body",
                                    "matrix": identity,
                                    "geometry": "geometry",
                                    "material": "material",
                                }
                            ],
                        }
                    ],
                },
            }
            scene_path = folder / "scene.json"
            scene_path.write_text(json.dumps(scene))
            spec = img2blockbench.import_threejs_scene(
                scene_path,
                reference,
                folder / "model-spec.json",
                "textured_threejs_test",
                "A textured official img2threejs-style scene",
            )
            material = spec["materials"][spec["cubes"][0]["material"]]
            self.assertEqual(data_uri, material["source_texture"]["data_uri"])
            atlas, _ = img2blockbench.build_texture(spec)
            colors = {
                color
                for _, color in (
                    atlas.getcolors(maxcolors=atlas.width * atlas.height) or []
                )
            }
            self.assertTrue(
                {
                    (255, 0, 0, 255),
                    (0, 255, 0, 255),
                    (0, 0, 255, 255),
                    (255, 255, 0, 255),
                }.issubset(colors)
            )

    def test_face_texture_overrides_procedural_material_and_quantizes(self):
        patch = Image.new("RGBA", (2, 2))
        patch.putdata(
            [
                (255, 0, 0, 255),
                (0, 255, 0, 255),
                (0, 0, 255, 255),
                (255, 255, 0, 255),
            ]
        )
        buffer = io.BytesIO()
        patch.save(buffer, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(
            buffer.getvalue()
        ).decode("ascii")

        spec = copy.deepcopy(img2blockbench.read_json(EXAMPLE))
        spec["texture"]["palette_size"] = 4
        spec["texture"]["quantize_source"] = True
        spec["landmarks"] = []
        spec["cubes"][0]["faces"]["north"] = {
            "source_texture": {
                "data_uri": data_uri,
                "repeat": [1, 1],
                "offset": [0, 0],
                "center": [0, 0],
                "rotation": 0,
                "wrap": [1001, 1001],
                "flip_y": False,
            }
        }

        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        atlas, placements = img2blockbench.build_texture(spec)
        left, top, width, height = placements[
            (spec["cubes"][0]["name"], "north")
        ]
        colors = set(
            atlas.crop(
                (left, top, left + width, top + height)
            ).get_flattened_data()
        )
        self.assertGreaterEqual(len(colors), 2)
        self.assertLessEqual(len(set(atlas.get_flattened_data())), 5)

    def test_strict_validation_checks_reference_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            reference = folder / "reference.jpg"
            reference.write_bytes((ROOT / "examples" / "fox" / "reference.jpg").read_bytes())
            spec = copy.deepcopy(img2blockbench.read_json(EXAMPLE))
            spec["reference"]["sha256"] = "0" * 64
            spec_path = folder / "model-spec.json"
            img2blockbench.write_json(spec_path, spec)
            with self.assertRaises(img2blockbench.ModelSpecError):
                img2blockbench.validated_spec(spec_path, strict=True)

    def test_audit_rejects_orphan(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            img2blockbench.build_model(EXAMPLE, output)
            model = json.loads((output / "fox.bbmodel").read_text())
            model["outliner"] = []
            self.assertFalse(img2blockbench.audit_bbmodel(model)["ok"])


if __name__ == "__main__":
    unittest.main()
