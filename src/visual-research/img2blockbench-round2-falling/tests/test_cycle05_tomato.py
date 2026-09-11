import json
import unittest
from pathlib import Path

import img2blockbench
import semantic_geometry


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "benchmarks" / "cycles" / "05-tomato-devil" / "model-spec.json"


class CycleFiveTomatoTests(unittest.TestCase):
    def test_tomato_is_native_volumetric_and_semantically_complete(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        names = [cube["name"] for cube in spec["cubes"]]
        self.assertEqual([], img2blockbench.validate_spec(spec, strict=True))
        self.assertEqual(192, len(spec["cubes"]))
        self.assertEqual(61, sum(name.startswith("body_volume_") for name in names))
        self.assertEqual(1416, spec["generation"]["ellipsoid"]["occupied_voxels"])
        self.assertEqual(10, sum(name.startswith("eye_bulb_") for name in names))
        self.assertEqual(10, sum(name.startswith("iris_") for name in names))
        self.assertEqual(
            24,
            sum(
                name.startswith("arm_")
                and "_finger_" not in name
                and name.rsplit("_", 1)[-1] in {"1", "2", "3"}
                for name in names
            ),
        )
        self.assertEqual(8, sum(name.endswith("_palm") for name in names))
        self.assertEqual(32, sum("_finger_" in name for name in names))
        self.assertEqual(14, sum(name.startswith("eye_band_") for name in names))
        self.assertEqual(12, sum(name.startswith("stem_leaf_") for name in names))
        self.assertEqual(5, sum(name.startswith("tooth_") for name in names))
        self.assertEqual(0, spec["generation"]["source_skin_cuboids"])
        self.assertFalse(
            any(
                "source_region" in override
                for cube in spec["cubes"]
                for override in cube.get("faces", {}).values()
            )
        )
        links = [
            (record["first"], record["second"], record["joint"])
            for record in spec["generation"]["declared_attachments"]
        ]
        self.assertEqual(121, len(links))
        report = semantic_geometry.audit_attachments(spec, links)
        self.assertTrue(report["all_connected"])
        self.assertGreater(report["minimum_margin"], 0)

        too_many = json.loads(json.dumps(spec))
        for index in range(1):
            extra = dict(too_many["cubes"][-1])
            extra["name"] = f"over_complex_limit_{index}"
            too_many["cubes"].append(extra)
        self.assertIn(
            "cubes must contain 1..192 cuboids",
            img2blockbench.validate_spec(too_many, strict=True),
        )


if __name__ == "__main__":
    unittest.main()
