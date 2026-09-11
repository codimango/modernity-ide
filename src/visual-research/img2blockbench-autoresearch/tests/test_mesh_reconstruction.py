import importlib.util
import io
import tempfile
import unittest
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

    def test_six_connected_components_do_not_join_diagonal_voxels(self):
        import numpy as np

        occupancy = np.zeros((3, 3, 3), dtype=bool)
        occupancy[0, 0, 0] = True
        occupancy[1, 1, 0] = True
        occupancy[2, 1, 0] = True

        components = mesh_reconstruction._components(occupancy)

        self.assertEqual([2, 1], [len(component) for component in components])
        self.assertEqual((1, 1, 0), min(components[0]))

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

            img2blockbench.write_json(output, first)
            first_build = folder / "build-first"
            second_build = folder / "build-second"
            result = img2blockbench.build_model(output, first_build)
            img2blockbench.build_model(output, second_build)
            self.assertTrue(result["audit"]["ok"])
            self.assertEqual(
                (first_build / "textured_box.zip").read_bytes(),
                (second_build / "textured_box.zip").read_bytes(),
            )

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

            with redirect_stdout(io.StringIO()):
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
                "orthographic-ray-voxel-adaptive-cuboids-v1",
                img2blockbench.read_json(evidence)["algorithm"],
            )


if __name__ == "__main__":
    unittest.main()
