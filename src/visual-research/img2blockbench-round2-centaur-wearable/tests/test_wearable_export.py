"""Tests for deterministic player-wearable shell exports."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import img2blockbench
from wearable_export import make_bedrock_attachable, make_wearable_spec, validate_wearable


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "fox" / "model-spec.json"


def wearable_fox() -> dict:
    """Return a small valid fixture with the head treated as a removable pilot."""
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    spec["wearable"] = {
        "target": "minecraft_player",
        "player_variant": "classic",
        "occupant_mode": "replaceable",
        "occupant_bones": ["head", "ear_left", "ear_right"],
        "shell_root_bone": "body",
        "attachable_identifier": "img2blockbench:test_shell",
        "fit": {
            "scale": 0.5,
            "offset": [0, -4, 0],
            "player_anchor": [0, 8, 0],
            "player_height": 64,
        },
        "collision": {"width": 1.0, "height": 2.5, "eye_height": 1.7},
        "attachment_points": [
            {"name": "body_harness", "bone": "body", "position": [0, 8, 0]}
        ],
    }
    return spec


class WearableExportTests(unittest.TestCase):
    """Keep pilot removal, player fitting, and attachable metadata explicit."""

    def test_wearable_shell_removes_occupant_and_applies_fit_transform(self) -> None:
        """The derived asset is a shell around a replacement player, not a second mob."""
        spec = wearable_fox()
        original_body = next(cube for cube in spec["cubes"] if cube["bone"] == "body")
        shell = make_wearable_spec(spec)
        shell_bones = {bone["name"] for bone in shell["bones"]}
        self.assertFalse({"head", "ear_left", "ear_right"} & shell_bones)
        self.assertFalse(
            any(
                cube["bone"] in {"head", "ear_left", "ear_right"}
                for cube in shell["cubes"]
            )
        )
        shell_body = next(cube for cube in shell["cubes"] if cube["bone"] == "body")
        self.assertEqual(
            [value * 0.5 for value in original_body["size"]],
            shell_body["size"],
        )
        self.assertEqual(
            [
                original_body["center"][0] * 0.5,
                original_body["center"][1] * 0.5 - 4,
                original_body["center"][2] * 0.5,
            ],
            shell_body["center"],
        )
        self.assertNotIn("wearable", shell)
        self.assertEqual("fox_wearable", shell["id"])
        point = shell["generation"]["wearable_export"]["attachment_points"][0]
        self.assertEqual([0, 8, 0], point["authored_position"])
        self.assertEqual([0, 0, 0], point["position"])
        self.assertEqual(
            [0, 0, 0],
            shell["generation"]["wearable_export"]["player_anchor_after_fit"],
        )
        self.assertEqual(
            "replaceable-player-wearable-shell-v1",
            shell["generation"]["algorithm"],
        )

    def test_wearable_validation_rejects_shell_parented_to_occupant(self) -> None:
        """A removable pilot may not own any retained exoskeleton branch."""
        spec = wearable_fox()
        spec["wearable"]["occupant_bones"] = ["body"]
        errors = validate_wearable(spec)
        self.assertTrue(any("cannot be parented" in error for error in errors))

    def test_wearable_validation_rejects_unscaled_player_fit(self) -> None:
        """The authored player anchor and height must map to canonical export units."""
        spec = wearable_fox()
        spec["wearable"]["fit"]["offset"] = [0, 0, 0]
        spec["wearable"]["fit"]["player_height"] = 32
        errors = validate_wearable(spec)
        self.assertTrue(any("player_height * scale" in error for error in errors))
        self.assertTrue(any("map player_anchor" in error for error in errors))

    def test_attachable_uses_wearable_geometry_and_texture_identifiers(self) -> None:
        """The companion descriptor points at the shell-only resources."""
        spec = wearable_fox()
        shell = make_wearable_spec(spec)
        attachable = make_bedrock_attachable(spec, shell)
        description = attachable["minecraft:attachable"]["description"]
        self.assertEqual("img2blockbench:test_shell", description["identifier"])
        self.assertEqual(
            "geometry.fox_wearable", description["geometry"]["default"]
        )
        self.assertEqual(
            "textures/entity/fox_wearable", description["textures"]["default"]
        )

    def test_invalid_contract_does_not_mutate_source(self) -> None:
        """Validation and derivation leave the authored source specification intact."""
        spec = wearable_fox()
        original = copy.deepcopy(spec)
        self.assertEqual([], validate_wearable(spec))
        make_wearable_spec(spec)
        self.assertEqual(original, spec)

    def test_shell_generation_drops_occupant_specific_source_records(self) -> None:
        """A shell keeps provenance without claiming that removed pilot parts remain."""
        spec = wearable_fox()
        spec["generation"] = {
            "lane": "agent-authored",
            "algorithm": "occupied-model-v1",
            "pilot_leg_chains": [{"side": "left"}],
            "declared_attachments": [{"first": "pilot_head", "second": "body"}],
        }
        shell = make_wearable_spec(spec)
        self.assertEqual("occupied-model-v1", shell["generation"]["source_model_algorithm"])
        self.assertNotIn("pilot_leg_chains", shell["generation"])
        self.assertNotIn("declared_attachments", shell["generation"])

    def test_build_emits_audited_shell_and_attachable_bundle(self) -> None:
        """A wearable contract produces usable companion artifacts automatically."""
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source_reference = (EXAMPLE.parent / "reference.jpg").read_bytes()
            reference = folder / "reference.jpg"
            reference.write_bytes(source_reference)
            spec = wearable_fox()
            spec["reference"]["image"] = reference.name
            spec_path = folder / "model-spec.json"
            img2blockbench.write_json(spec_path, spec)

            result = img2blockbench.build_model(spec_path, folder / "build")
            second = img2blockbench.build_model(spec_path, folder / "build-second")

            self.assertTrue(result["audit"]["ok"])
            self.assertTrue(result["wearable"]["audit"]["ok"])
            wearable_id = result["wearable"]["model_id"]
            for suffix in (
                ".model-spec.json",
                ".png",
                ".bbmodel",
                ".geo.json",
                ".attachable.json",
                ".audit.json",
            ):
                self.assertTrue((folder / "build" / f"{wearable_id}{suffix}").is_file())
            manifest = json.loads(
                (folder / "build" / "fox.manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(wearable_id, manifest["wearable"]["model_id"])
            self.assertEqual(
                (folder / "build" / "fox.zip").read_bytes(),
                (folder / "build-second" / "fox.zip").read_bytes(),
            )
            self.assertEqual(
                result["wearable"]["artifacts"],
                second["wearable"]["artifacts"],
            )


if __name__ == "__main__":
    unittest.main()
