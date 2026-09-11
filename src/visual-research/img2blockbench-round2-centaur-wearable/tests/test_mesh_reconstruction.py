import importlib.util
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image

import img2blockbench
import mesh_reconstruction


ROOT = Path(__file__).resolve().parents[1]
HAS_MESH_DEPENDENCIES = bool(
    importlib.util.find_spec("numpy") and importlib.util.find_spec("trimesh")
)


@unittest.skipUnless(
    HAS_MESH_DEPENDENCIES,
    "install img2blockbench[mesh-reconstruction] to run mesh route tests",
)
class MeshReconstructionTests(unittest.TestCase):
    def _textured_box(self, path: Path) -> None:
        import numpy as np
        import trimesh

        mesh = trimesh.creation.box(extents=(2.0, 3.0, 4.0))
        uv = np.column_stack(
            (
                (mesh.vertices[:, 0] + 1.0) / 2.0,
                (mesh.vertices[:, 1] + 1.5) / 3.0,
            )
        )
        texture = Image.new("RGB", (8, 8))
        texture.putdata(
            [
                (238, 58, 42) if y < 4 else (31, 92, 214)
                for y in range(8)
                for _ in range(8)
            ]
        )
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=texture,
            baseColorFactor=(255, 255, 255, 255),
        )
        mesh.visual = trimesh.visual.texture.TextureVisuals(
            uv=uv,
            material=material,
        )
        mesh.export(path)

    def test_portable_source_filename_redacts_posix_and_windows_paths(self):
        self.assertEqual(
            "source.glb",
            img2blockbench.portable_source_filename("/Users/person/input/source.glb"),
        )
        self.assertEqual(
            "source.glb",
            img2blockbench.portable_source_filename(
                "C:\\Users\\person\\input\\source.glb"
            ),
        )

    def test_six_connected_components_do_not_join_diagonal_voxels(self):
        import numpy as np

        occupancy = np.zeros((3, 3, 3), dtype=bool)
        occupancy[0, 0, 0] = True
        occupancy[1, 1, 0] = True
        occupancy[2, 1, 0] = True

        components = mesh_reconstruction._components(occupancy)

        self.assertEqual([2, 1], [len(component) for component in components])
        self.assertEqual((1, 1, 0), min(components[0]))

    def test_signed_cameras_select_opposing_surfaces(self):
        import numpy as np

        occupancy = np.zeros((3, 2, 4), dtype=bool)
        colors = np.zeros((3, 2, 4, 3), dtype=np.uint8)
        occupancy[0, 0, 0] = True
        colors[0, 0, 0] = (220, 30, 30)
        occupancy[0, 0, 3] = True
        colors[0, 0, 3] = (20, 60, 230)
        cameras = {view.name: view for view in mesh_reconstruction._CANONICAL_VIEWS}

        front_mask, front_colors = mesh_reconstruction._project_cardinal(
            occupancy, colors, cameras["front"]
        )
        back_mask, back_colors = mesh_reconstruction._project_cardinal(
            occupancy, colors, cameras["back"]
        )

        self.assertTrue(front_mask[1, 0])
        self.assertEqual((20, 60, 230), tuple(front_colors[1, 0]))
        self.assertTrue(back_mask[1, 2])
        self.assertEqual((220, 30, 30), tuple(back_colors[1, 2]))

    def test_axis_metrics_detect_model_depth_collapse(self):
        import numpy as np

        source = np.ones((4, 4, 4), dtype=bool)
        flattened = np.zeros_like(source)
        flattened[:, :, 0] = True

        metrics = mesh_reconstruction._axis_fit_metrics(source, flattened, 2)

        self.assertEqual(0.25, metrics["axis_span_preservation"])
        self.assertEqual(0.25, metrics["source_depth_envelope_coverage"])
        self.assertEqual(16, metrics["collapsed_source_rays"])

    def test_anti_pancake_gate_rejects_extreme_bbox_overfill(self):
        import numpy as np

        occupancy = np.zeros((12, 12, 12), dtype=bool)
        occupancy[:, 0, 0] = True
        occupancy[11, 1:, 0] = True
        occupancy[11, 11, 1:] = True
        component_labels = np.full(occupancy.shape, -1, dtype=np.int32)
        component_labels[occupancy] = 0
        material_labels = np.full(occupancy.shape, -1, dtype=np.int16)
        material_labels[occupancy] = 0
        voxels = mesh_reconstruction._VoxelData(
            occupancy=occupancy,
            raw_surface=occupancy.copy(),
            colors=np.zeros(occupancy.shape + (3,), dtype=np.uint8),
            component_labels=component_labels,
            lower=np.zeros(3),
            pitch=1.0,
            report={},
        )

        _, report, _ = mesh_reconstruction._adaptive_cuboids(
            voxels, material_labels, 1
        )

        self.assertEqual(34, report["source_voxels"])
        self.assertEqual(1728, report["cuboid_voxels"])
        gate = report["anti_pancake_gate"]
        self.assertFalse(gate["passed"])
        self.assertLess(gate["model_voxel_precision"], 0.02)
        self.assertIn("model_voxel_precision_bounded", gate["failed_checks"])
        self.assertIn(
            "axis_depth_inflation_bounded", gate["failed_checks"]
        )

    def test_component_gate_detects_bbox_merge_in_fitted_occupancy(self):
        import numpy as np

        occupancy = np.zeros((5, 5, 5), dtype=bool)
        grid = np.indices(occupancy.shape)
        shell = (
            (grid[0] == 0)
            | (grid[0] == 4)
            | (grid[1] == 0)
            | (grid[1] == 4)
            | (grid[2] == 0)
            | (grid[2] == 4)
        )
        occupancy[shell] = True
        occupancy[2, 2, 2] = True
        components = mesh_reconstruction._components(occupancy)
        self.assertEqual([98, 1], [len(component) for component in components])
        component_labels = np.full(occupancy.shape, -1, dtype=np.int32)
        for component_index, component in enumerate(components):
            for point in component:
                component_labels[point] = component_index
        material_labels = np.full(occupancy.shape, -1, dtype=np.int16)
        material_labels[occupancy] = 0
        voxels = mesh_reconstruction._VoxelData(
            occupancy=occupancy,
            raw_surface=occupancy.copy(),
            colors=np.zeros(occupancy.shape + (3,), dtype=np.uint8),
            component_labels=component_labels,
            lower=np.zeros(3),
            pitch=1.0,
            report={},
        )

        _, report, _ = mesh_reconstruction._adaptive_cuboids(
            voxels, material_labels, 2
        )

        preservation = report["component_preservation"]
        self.assertEqual(2, preservation["source_components"])
        self.assertEqual(1, preservation["fitted_components"])
        self.assertEqual([[1, 2]], preservation["merged_source_component_groups"])
        self.assertFalse(preservation["one_to_one_fitted_connectivity"])
        gate = report["anti_pancake_gate"]
        self.assertFalse(gate["passed"])
        self.assertIn(
            "fitted_components_preserved_one_to_one", gate["failed_checks"]
        )

    def test_textured_closed_mesh_is_deterministic_buildable_and_colored(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            mesh_path = folder / "textured-box.glb"
            output = folder / "model-spec.json"
            self._textured_box(mesh_path)
            options = mesh_reconstruction.MeshReconstructionOptions(
                resolution=12,
                max_cuboids=20,
                palette_size=8,
            )

            first, first_report = mesh_reconstruction.reconstruct_mesh_spec(
                mesh_path,
                output,
                "textured_box",
                "A synthetic textured box",
                "object",
                options,
            )
            first_reference = (folder / "textured_box.mesh-reference.png").read_bytes()
            first_manifest = json.loads(
                (folder / "textured_box.mesh-views.json").read_text(encoding="utf-8")
            )
            first_previews = {
                view["id"]: (folder / view["image"]).read_bytes()
                for view in first_manifest["views"]
            }
            second, second_report = mesh_reconstruction.reconstruct_mesh_spec(
                mesh_path,
                output,
                "textured_box",
                "A synthetic textured box",
                "object",
                options,
            )

            self.assertEqual(first, second)
            self.assertEqual(first_report, second_report)
            self.assertEqual(
                first_reference,
                (folder / "textured_box.mesh-reference.png").read_bytes(),
            )
            self.assertEqual(
                first_manifest,
                json.loads(
                    (folder / "textured_box.mesh-views.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            self.assertEqual(
                first_previews,
                {
                    view["id"]: (folder / view["image"]).read_bytes()
                    for view in first_manifest["views"]
                },
            )
            self.assertEqual([], img2blockbench.validate_spec(first, strict=True))
            self.assertEqual(["uv-texture"], first_report["color_transfer"]["sources"])
            self.assertGreaterEqual(first_report["color_transfer"]["palette_entries"], 2)
            self.assertEqual(
                "solid",
                first_report["voxelization"]["fill_mode_resolved"],
            )
            self.assertEqual(
                1.0,
                first_report["source_mesh_overlap"]["source_coverage"],
            )
            self.assertLessEqual(len(first["cubes"]), options.max_cuboids)
            ray_evidence = first_report["voxelization"]["ray_evidence"]
            self.assertEqual(
                {"front", "back", "left", "right", "top", "bottom"},
                set(ray_evidence["directions"]),
            )
            self.assertEqual({"x", "y", "z"}, set(ray_evidence["axes"]))
            overlap = first_report["source_mesh_overlap"]
            self.assertTrue(overlap["anti_pancake_gate"]["passed"])
            self.assertEqual(
                {"x", "y", "z"}, set(overlap["axis_volume_metrics"])
            )
            self.assertTrue(
                overlap["component_preservation"][
                    "all_retained_components_represented"
                ]
            )
            review = first_report["multi_angle_review"]
            self.assertTrue(review["complete"])
            self.assertEqual(7, review["view_count"])
            self.assertTrue(review["agent_visual_review_required"])
            self.assertEqual("pending", review["agent_visual_review_status"])
            manifest_path = folder / review["manifest"]
            self.assertEqual(
                review["manifest_sha256"],
                hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                [
                    "front",
                    "back",
                    "left",
                    "right",
                    "top",
                    "bottom",
                    "isometric",
                ],
                review["required_views"],
            )
            for view in first_manifest["views"]:
                preview_path = folder / view["image"]
                self.assertTrue(preview_path.is_file())
                self.assertEqual(
                    view["image_sha256"],
                    hashlib.sha256(preview_path.read_bytes()).hexdigest(),
                )
            self.assertTrue(
                first_manifest["review_contract"]["agent_visual_review_required"]
            )

            img2blockbench.write_json(output, first)
            first_build = folder / "build-first"
            second_build = folder / "build-second"
            result = img2blockbench.build_model(output, first_build)
            img2blockbench.build_model(output, second_build)
            self.assertTrue(result["audit"]["ok"])
            delivery_spec = img2blockbench.read_json(
                first_build / "textured_box.model-spec.json"
            )
            delivery_mesh = delivery_spec["generation"]["mesh"]
            self.assertNotIn("path", delivery_mesh)
            self.assertEqual(
                "textured-box.glb", delivery_mesh["source_file_name"]
            )
            self.assertFalse(delivery_mesh["bundled"])
            delivery_review = delivery_spec["generation"]["multi_angle_review"]
            packaged_manifest = first_build / delivery_review["manifest"]
            self.assertTrue(packaged_manifest.is_file())
            self.assertEqual(
                delivery_review["manifest_sha256"],
                hashlib.sha256(packaged_manifest.read_bytes()).hexdigest(),
            )
            packaged_review = img2blockbench.read_json(packaged_manifest)
            self.assertNotIn("path", packaged_review["source_mesh"])
            self.assertEqual(
                "textured-box.glb",
                packaged_review["source_mesh"]["source_file_name"],
            )
            portable_json = json.dumps(
                {"spec": delivery_spec, "review": packaged_review}
            )
            self.assertNotIn("../", portable_json)
            self.assertNotIn("/Users/", portable_json)
            for view in packaged_review["views"]:
                packaged_image = first_build / view["image"]
                self.assertTrue(packaged_image.is_file())
                self.assertEqual(
                    view["image_sha256"],
                    hashlib.sha256(packaged_image.read_bytes()).hexdigest(),
                )
            build_manifest = img2blockbench.read_json(
                first_build / "textured_box.manifest.json"
            )
            packaged_paths = {
                artifact["path"] for artifact in build_manifest["artifacts"]
            }
            for artifact in build_manifest["artifacts"]:
                artifact_path = first_build / artifact["path"]
                self.assertTrue(artifact_path.is_file())
                self.assertEqual(
                    artifact["sha256"],
                    hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                )
            self.assertIn("textured_box.mesh-views.json", packaged_paths)
            self.assertIn("textured_box.mesh-views/front.png", packaged_paths)
            self.assertIn("textured_box.mesh-views/isometric.png", packaged_paths)
            with zipfile.ZipFile(first_build / "textured_box.zip") as archive:
                archive_paths = set(archive.namelist())
            self.assertIn("textured_box.mesh-views.json", archive_paths)
            self.assertIn("textured_box.mesh-views/front.png", archive_paths)
            self.assertIn("textured_box.mesh-views/isometric.png", archive_paths)
            self.assertEqual(
                (first_build / "textured_box.zip").read_bytes(),
                (second_build / "textured_box.zip").read_bytes(),
            )
            rebuilt_directory = folder / "build-from-delivery"
            img2blockbench.build_model(
                first_build / "textured_box.model-spec.json",
                rebuilt_directory,
            )
            self.assertEqual(
                packaged_manifest.read_bytes(),
                (rebuilt_directory / "textured_box.mesh-views.json").read_bytes(),
            )
            self.assertEqual(
                (first_build / "textured_box.zip").read_bytes(),
                (rebuilt_directory / "textured_box.zip").read_bytes(),
            )

    def test_build_rejects_tampered_mesh_review_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            mesh_path = folder / "textured-box.glb"
            output = folder / "model-spec.json"
            self._textured_box(mesh_path)
            spec, _ = mesh_reconstruction.reconstruct_mesh_spec(
                mesh_path,
                output,
                "tamper_probe",
                "A mesh review integrity probe",
                "object",
                mesh_reconstruction.MeshReconstructionOptions(
                    resolution=10,
                    max_cuboids=16,
                    palette_size=8,
                ),
            )
            img2blockbench.write_json(output, spec)

            stale_spec = json.loads(json.dumps(spec))
            first_material = sorted(stale_spec["materials"])[0]
            stale_spec["materials"][first_material]["base"] = "#010203"
            stale_path = folder / "stale-model-spec.json"
            img2blockbench.write_json(stale_path, stale_spec)
            with self.assertRaisesRegex(
                img2blockbench.ModelSpecError,
                "content SHA-256 does not match",
            ):
                img2blockbench.build_model(stale_path, folder / "stale-build")

            preview = folder / "tamper_probe.mesh-views" / "front.png"
            preview.write_bytes(preview.read_bytes() + b"tampered")

            with self.assertRaisesRegex(
                img2blockbench.ModelSpecError,
                "mesh review image SHA-256 does not match for front",
            ):
                img2blockbench.build_model(output, folder / "build")

    def test_open_mesh_uses_surface_hits_and_retains_connected_shape(self):
        import numpy as np
        import trimesh

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            vertices = np.asarray(
                [
                    (0, 0, 0),
                    (4, 0, 0),
                    (4, 3, 0),
                    (0, 3, 0),
                    (4, 1, 0),
                    (6, 1, 0),
                    (6, 2, 0),
                    (4, 2, 0),
                ],
                dtype=float,
            )
            faces = np.asarray(
                [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)],
                dtype=int,
            )
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            mesh.visual.vertex_colors = np.tile((232, 171, 45, 255), (len(vertices), 1))
            mesh_path = folder / "open.glb"
            mesh.export(mesh_path)

            _, report = mesh_reconstruction.reconstruct_mesh_spec(
                mesh_path,
                folder / "open.json",
                "open_mesh",
                "An open connected panel with an appendage",
                "object",
                mesh_reconstruction.MeshReconstructionOptions(
                    resolution=20,
                    max_cuboids=30,
                    surface_thickness=1,
                    min_component_voxels=1,
                ),
            )

            self.assertFalse(report["source"]["watertight"])
            self.assertEqual(
                "surface", report["voxelization"]["fill_mode_resolved"]
            )
            self.assertEqual(
                6, report["voxelization"]["components"]["connectivity"]
            )
            self.assertEqual(
                1, report["voxelization"]["components"]["after_cleanup"]
            )
            self.assertGreater(
                report["voxelization"]["ray_evidence"]["surface_voxels"], 20
            )

    def test_multipart_scene_preserves_separate_components_and_transforms(self):
        import numpy as np
        import trimesh

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            scene = trimesh.Scene()
            scene.add_geometry(
                trimesh.creation.box(extents=(1, 1, 1)),
                node_name="part_a",
                geom_name="part_a_geometry",
            )
            transform = np.eye(4)
            transform[0, 3] = 4.0
            scene.add_geometry(
                trimesh.creation.box(extents=(1, 2, 1)),
                node_name="part_b",
                geom_name="part_b_geometry",
                transform=transform,
            )
            mesh_path = folder / "multipart.glb"
            scene.export(mesh_path)

            spec, report = mesh_reconstruction.reconstruct_mesh_spec(
                mesh_path,
                folder / "multipart.json",
                "multipart",
                "Two transformed mesh parts",
                "object",
                mesh_reconstruction.MeshReconstructionOptions(
                    resolution=24,
                    max_cuboids=12,
                    min_component_voxels=1,
                ),
            )

            self.assertEqual(2, report["source"]["geometries"])
            self.assertEqual(
                2, report["voxelization"]["components"]["after_cleanup"]
            )
            self.assertEqual(
                {"source mesh component 1", "source mesh component 2"},
                {cube["role"] for cube in spec["cubes"]},
            )
            centers = [cube["center"][0] for cube in spec["cubes"]]
            self.assertLess(min(centers), 0)
            self.assertGreater(max(centers), 0)
            self.assertTrue(
                report["source_mesh_overlap"]["component_preservation"][
                    "all_retained_components_represented"
                ]
            )

    def test_component_budget_fails_instead_of_dropping_source_parts(self):
        import numpy as np
        import trimesh

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            scene = trimesh.Scene()
            scene.add_geometry(trimesh.creation.box(), node_name="first")
            transform = np.eye(4)
            transform[0, 3] = 5.0
            scene.add_geometry(
                trimesh.creation.box(), node_name="second", transform=transform
            )
            mesh_path = folder / "two-parts.glb"
            scene.export(mesh_path)

            with self.assertRaisesRegex(
                ValueError, "increase --max-cuboids rather than dropping source parts"
            ):
                mesh_reconstruction.reconstruct_mesh_spec(
                    mesh_path,
                    folder / "two-parts.json",
                    "two_parts",
                    "Two disconnected source parts",
                    "object",
                    mesh_reconstruction.MeshReconstructionOptions(
                        resolution=16,
                        max_cuboids=1,
                        min_component_voxels=1,
                    ),
                )

    def test_source_relative_gate_allows_intentionally_thin_mesh(self):
        import trimesh

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            mesh_path = folder / "thin.glb"
            trimesh.creation.box(extents=(4.0, 3.0, 0.001)).export(mesh_path)

            _, report = mesh_reconstruction.reconstruct_mesh_spec(
                mesh_path,
                folder / "thin.json",
                "thin_source",
                "An intentionally thin source plate",
                "object",
                mesh_reconstruction.MeshReconstructionOptions(
                    resolution=20,
                    max_cuboids=8,
                ),
            )

            gate = report["source_mesh_overlap"]["anti_pancake_gate"]
            self.assertTrue(gate["relative_to_source_mesh"])
            self.assertTrue(gate["passed"])
            self.assertIn("z", gate["intrinsically_thin_source_axes"])

    def test_existing_open_textured_glb_produces_overlap_evidence(self):
        mesh_path = ROOT / "examples" / "chimpanzee" / "lane2" / "source.glb"
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            spec, report = mesh_reconstruction.reconstruct_mesh_spec(
                mesh_path,
                folder / "chimpanzee.json",
                "chimpanzee_mesh_probe",
                "A ray-voxel reconstruction of the bundled chimpanzee mesh",
                "mob",
                mesh_reconstruction.MeshReconstructionOptions(
                    resolution=14,
                    max_cuboids=32,
                    palette_size=12,
                    fill_mode="surface",
                    min_component_voxels=2,
                ),
            )

            self.assertFalse(report["source"]["watertight"])
            self.assertIn("uv-texture", report["color_transfer"]["sources"])
            self.assertGreater(report["source"]["triangles"], 1_000)
            self.assertGreater(
                report["source_mesh_overlap"]["mean_silhouette_iou"], 0.8
            )
            self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))

    def test_from_mesh_cli_writes_spec_evidence_and_build(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            mesh_path = folder / "box.glb"
            output = folder / "box.json"
            evidence = folder / "evidence.json"
            build = folder / "build"
            self._textured_box(mesh_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = img2blockbench.main(
                    [
                        "from-mesh",
                        str(mesh_path),
                        "--id",
                        "cli_mesh",
                        "--description",
                        "A CLI mesh reconstruction",
                        "--output",
                        str(output),
                        "--evidence",
                        str(evidence),
                        "--build-output",
                        str(build),
                        "--resolution",
                        "10",
                        "--max-cuboids",
                        "16",
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())
            self.assertTrue(evidence.is_file())
            self.assertTrue((build / "cli_mesh.bbmodel").is_file())
            self.assertEqual(
                "orthographic-six-view-ray-voxel-adaptive-cuboids-v2",
                img2blockbench.read_json(evidence)["algorithm"],
            )
            result = json.loads(stdout.getvalue())
            manifest_path = folder / "cli_mesh.mesh-views.json"
            self.assertTrue(manifest_path.is_file())
            self.assertEqual(
                str(manifest_path.resolve()), result["multi_angle_review_manifest"]
            )


if __name__ == "__main__":
    unittest.main()
