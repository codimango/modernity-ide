"""Round 2 texture policy regressions."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CYCLES = ROOT / "benchmarks" / "round2" / "cycles"
EXCLUDED_CYCLES = {"07-centaur-exoskeleton"}
ALLOWED_PATTERNS = {"solid", "gradient", "stripes"}


class RoundTwoTexturePolicyTests(unittest.TestCase):
    """Prevent random procedural speckle from returning to Round 2 assets."""

    def test_non_centaur_specs_use_only_intentional_surface_patterns(self) -> None:
        specs = sorted(CYCLES.glob("*/model-spec.json"))
        specs.extend(sorted(CYCLES.glob("*/build/*.model-spec.json")))
        checked = 0
        for path in specs:
            cycle = path.parents[1].name if path.parent.name == "build" else path.parent.name
            if cycle in EXCLUDED_CYCLES:
                continue
            checked += 1
            spec = json.loads(path.read_text(encoding="utf-8"))
            forbidden = {
                name: material.get("pattern")
                for name, material in spec["materials"].items()
                if material.get("pattern") not in ALLOWED_PATTERNS
            }
            self.assertEqual({}, forbidden, str(path.relative_to(ROOT)))
        self.assertGreaterEqual(checked, 14)

    def test_non_centaur_generators_do_not_author_noise_patterns(self) -> None:
        checked = 0
        for path in sorted(CYCLES.glob("*/prepare-semantic-model.py")):
            if path.parent.name in EXCLUDED_CYCLES:
                continue
            checked += 1
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('"dither"', source, str(path.relative_to(ROOT)))
            self.assertNotIn('"spots"', source, str(path.relative_to(ROOT)))
        self.assertGreaterEqual(checked, 7)


if __name__ == "__main__":
    unittest.main()
