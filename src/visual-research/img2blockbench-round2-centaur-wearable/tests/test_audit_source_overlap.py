"""Tests for the optional source-overlap audit entry point."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import audit_source_overlap


class SourceOverlapAuditTests(unittest.TestCase):
    def test_missing_dependencies_report_the_overlap_extra_without_traceback(self):
        arguments = [
            "img2blockbench-overlap",
            "--source",
            "missing.glb",
            "--spec",
            "missing.json",
            "--bbmodel",
            "missing.bbmodel",
            "--json",
            "result.json",
        ]
        stderr = io.StringIO()
        with mock.patch.object(audit_source_overlap, "np", None), mock.patch.object(
            audit_source_overlap, "trimesh", None
        ), mock.patch.object(
            audit_source_overlap.importlib,
            "import_module",
            side_effect=ModuleNotFoundError("blocked for test"),
        ), mock.patch.object(sys, "argv", arguments), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                audit_source_overlap.main()

        self.assertEqual(2, raised.exception.code)
        self.assertIn("img2blockbench[overlap-audit]", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_blockbench_cube_expands_to_twelve_triangles(self):
        with tempfile.TemporaryDirectory() as temporary:
            model_path = Path(temporary) / "cube.bbmodel"
            model_path.write_text(
                json.dumps(
                    {
                        "elements": [
                            {
                                "type": "cube",
                                "from": [0, 0, 0],
                                "to": [2, 3, 4],
                                "origin": [1, 1.5, 2],
                                "rotation": [0, 0, 0],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            vertices, triangles = audit_source_overlap.load_blockbench_mesh(
                model_path
            )

        self.assertEqual((8, 3), vertices.shape)
        self.assertEqual((12, 3), triangles.shape)


if __name__ == "__main__":
    unittest.main()
