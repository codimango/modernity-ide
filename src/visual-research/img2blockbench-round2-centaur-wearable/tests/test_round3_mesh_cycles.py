from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
CYCLE_ROOT = ROOT / "benchmarks" / "round3" / "cycles"
TRUCK = CYCLE_ROOT / "03-off-road-truck"
HOVERCRAFT = CYCLE_ROOT / "04-hovercraft"
REQUIRED_VIEWS = [
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "isometric",
]


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _temporary_cycle(
    temporary_root: Path, source_cycle: Path, source_name: str
) -> tuple[Path, Path]:
    cycle_directory = temporary_root / "benchmarks" / "round3" / "cycles" / source_cycle.name
    cycle_directory.mkdir(parents=True)
    config = _json(source_cycle / "cycle.json")
    config["source"]["relative_path"] = f"round3-inputs/{source_name}"
    config["reconstruction"].update(
        {
            "resolution": 10,
            "max_cuboids": 16,
            "target_size": 16.0,
            "palette_size": 8,
            "min_component_fraction": 0.0,
        }
    )
    contract = _json(source_cycle / "input-contract.json")
    contract["source"]["relative_path"] = config["source"]["relative_path"]
    config_path = cycle_directory / "cycle.json"
    _write_json(config_path, config)
    _write_json(cycle_directory / "input-contract.json", contract)
    return config_path, cycle_directory


class Round3MeshCycleConfigurationTests(unittest.TestCase):
    def test_private_mesh_cycles_are_honestly_blocked_and_unlocked(self):
        expected = {
            TRUCK: "round3-inputs/Minecraft-style off-road truck.glb",
            HOVERCRAFT: (
                "round3-inputs/"
                "Meshy_AI_minecraft_hovercraft_0907011803_image-to-3d-texture.glb"
            ),
        }
        for cycle, source_path in expected.items():
            with self.subTest(cycle=cycle.name):
                config = _json(cycle / "cycle.json")
                contract = _json(cycle / "input-contract.json")
                result = _json(cycle / "results.json")
                self.assertEqual(source_path, config["source"]["relative_path"])
                self.assertEqual(REQUIRED_VIEWS, config["review"]["required_views"])
                self.assertTrue(config["review"]["separate_agent_required"])
                self.assertIsNone(contract["source"]["sha256"])
                self.assertIsNone(contract["source"]["byte_length"])
                self.assertEqual(source_path, contract["source"]["relative_path"])
                self.assertEqual("BLOCKED", result["status"])
                self.assertFalse(result["pass_claimed"])
                self.assertEqual(
                    "MISSING_PRIVATE_INPUT", result["blocker"]["code"]
                )

    def test_missing_input_returns_blocker_without_artifacts_or_pass(self):
        runner = _load_module(TRUCK / "run-cycle.py", "round3_truck_runner_missing")
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            config_path, cycle_directory = _temporary_cycle(
                repository_root, HOVERCRAFT, "missing.glb"
            )

            exit_code, result = runner.run_cycle(config_path, repository_root)

            self.assertEqual(2, exit_code)
            self.assertEqual("BLOCKED", result["status"])
            self.assertFalse(result["pass_claimed"])
            self.assertEqual("MISSING_PRIVATE_INPUT", result["blocker"]["code"])
            self.assertFalse((cycle_directory / "model-spec.json").exists())
            self.assertFalse((cycle_directory / "mesh-evidence.json").exists())
            self.assertFalse((cycle_directory / "build").exists())
            self.assertEqual(result, _json(cycle_directory / "results.json"))

    def test_hovercraft_wrapper_preserves_explicit_arguments(self):
        wrapper = _load_module(HOVERCRAFT / "run-cycle.py", "round3_hover_wrapper")
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            config_path, _ = _temporary_cycle(
                repository_root, HOVERCRAFT, "still-missing.glb"
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = wrapper.main(
                    [
                        "--config",
                        str(config_path),
                        "--repository-root",
                        str(repository_root),
                    ]
                )

            self.assertEqual(2, exit_code)
            self.assertEqual("BLOCKED", json.loads(output.getvalue())["status"])


class Round3MeshCycleExecutionTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("numpy") and importlib.util.find_spec("trimesh"),
        "install img2blockbench[mesh-reconstruction] for the mesh-cycle test",
    )
    def test_first_success_locks_hash_emits_seven_views_and_rejects_replacement(self):
        import numpy as np
        import trimesh

        runner = _load_module(TRUCK / "run-cycle.py", "round3_truck_runner_success")
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            config_path, cycle_directory = _temporary_cycle(
                repository_root, TRUCK, "synthetic-truck.glb"
            )
            source_path = repository_root / "round3-inputs" / "synthetic-truck.glb"
            source_path.parent.mkdir(parents=True)
            mesh = trimesh.creation.box(extents=(5.0, 2.5, 8.0))
            mesh.visual.vertex_colors = np.tile(
                np.asarray((76, 118, 73, 255), dtype=np.uint8),
                (len(mesh.vertices), 1),
            )
            mesh.export(source_path)
            original_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()

            exit_code, result = runner.run_cycle(config_path, repository_root)

            self.assertEqual(0, exit_code)
            self.assertEqual("AWAITING_AGENT_VISUAL_REVIEW", result["status"])
            self.assertFalse(result["pass_claimed"])
            self.assertTrue(
                result["automated_gates"][
                    "all_seven_review_views_emitted_and_hash_bound"
                ]
            )
            contract = _json(cycle_directory / "input-contract.json")
            self.assertEqual(original_sha256, contract["source"]["sha256"])
            self.assertEqual(source_path.stat().st_size, contract["source"]["byte_length"])
            self.assertEqual(
                "locked-after-successful-reconstruction", contract["status"]
            )
            manifest_path = cycle_directory / result["artifacts"]["review_manifest"]["path"]
            manifest = _json(manifest_path)
            self.assertEqual(REQUIRED_VIEWS, manifest["generated_views"])
            self.assertTrue(manifest["complete"])
            self.assertNotIn("path", manifest["source_mesh"])
            self.assertEqual(
                "external-provenance-only",
                manifest["source_mesh"]["availability"],
            )
            self.assertEqual("pending", manifest["review_contract"]["agent_visual_review_status"])
            for view in manifest["views"]:
                image_path = manifest_path.parent / view["image"]
                self.assertTrue(image_path.is_file())
                self.assertEqual(
                    view["image_sha256"],
                    hashlib.sha256(image_path.read_bytes()).hexdigest(),
                )
            build_manifest_path = (
                cycle_directory / result["artifacts"]["build_manifest"]["path"]
            )
            build_manifest = _json(build_manifest_path)
            build_artifact_paths = {
                artifact["path"] for artifact in build_manifest["artifacts"]
            }
            packaged_review_paths = {
                "minecraft_off_road_truck_mesh.mesh-views.json",
                *{
                    f"minecraft_off_road_truck_mesh.mesh-views/{view}.png"
                    for view in REQUIRED_VIEWS
                },
            }
            self.assertTrue(packaged_review_paths.issubset(build_artifact_paths))
            delivery_spec = _json(
                cycle_directory
                / "build"
                / "minecraft_off_road_truck_mesh.model-spec.json"
            )
            self.assertNotIn("path", delivery_spec["generation"]["mesh"])
            self.assertNotIn("../", json.dumps(delivery_spec, sort_keys=True))
            bundle_path = cycle_directory / result["artifacts"]["bundle"]["path"]
            with zipfile.ZipFile(bundle_path) as bundle:
                self.assertTrue(
                    packaged_review_paths.issubset(set(bundle.namelist()))
                )
            self.assertTrue(
                (cycle_directory / result["artifacts"]["bbmodel"]["path"]).is_file()
            )

            first_artifact_hashes = {
                name: artifact["sha256"]
                for name, artifact in result["artifacts"].items()
            }
            repeat_exit_code, repeat_result = runner.run_cycle(
                config_path, repository_root
            )
            self.assertEqual(0, repeat_exit_code)
            self.assertTrue(repeat_result["source"]["hash_was_already_locked"])
            self.assertEqual(
                first_artifact_hashes,
                {
                    name: artifact["sha256"]
                    for name, artifact in repeat_result["artifacts"].items()
                },
            )

            with source_path.open("ab") as source:
                source.write(b"replacement")
            second_exit_code, second_result = runner.run_cycle(
                config_path, repository_root
            )

            self.assertEqual(2, second_exit_code)
            self.assertEqual("BLOCKED", second_result["status"])
            self.assertEqual(
                "SOURCE_HASH_MISMATCH", second_result["blocker"]["code"]
            )
            self.assertFalse(second_result["pass_claimed"])
            self.assertEqual(
                original_sha256,
                _json(cycle_directory / "input-contract.json")["source"]["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
