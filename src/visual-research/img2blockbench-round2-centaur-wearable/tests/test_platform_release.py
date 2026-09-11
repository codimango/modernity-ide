"""Tests for the lean, deterministic platform release builder."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import posixpath
import re
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "tools" / "build-platform-release.py"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_platform_release", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load release builder: {BUILDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PlatformReleaseTests(unittest.TestCase):
    """Require a portable production allowlist and byte-stable archive."""

    def test_allowlist_is_lean_complete_and_tolerates_missing_optional_docs(self) -> None:
        policy = BUILDER._load_policy(ROOT / "release" / "manifest.json")
        with_missing_optional = copy.deepcopy(policy)
        with_missing_optional["optional_files"].append(
            "docs/OPTIONAL_FILE_THAT_DOES_NOT_EXIST.md"
        )
        files = BUILDER.collect_release_files(ROOT, with_missing_optional)
        relative = {path.as_posix() for path in files}

        expected_scripts = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "skill" / "img2blockbench" / "scripts").glob("*.py")
        }
        self.assertTrue(expected_scripts)
        self.assertTrue(expected_scripts.issubset(relative))
        self.assertIn("pyproject.toml", relative)
        self.assertIn("LICENSE", relative)
        self.assertIn("THIRD_PARTY_NOTICES.md", relative)
        self.assertIn("skill/img2blockbench/SKILL.md", relative)
        self.assertIn("release/manifest.json", relative)
        self.assertTrue(
            {
                "docs/AUTORESEARCH.md",
                "docs/AUTORESEARCH_CYCLES.md",
                "docs/METRICS_AND_REGRESSIONS.md",
                "docs/PLATFORM.md",
                "docs/TECHNICAL_DESIGN.md",
            }.issubset(relative)
        )

        excluded_roots = set(policy["excluded_roots"])
        excluded_suffixes = {suffix.lower() for suffix in policy["excluded_suffixes"]}
        for path in files:
            self.assertNotIn(path.parts[0], excluded_roots)
            self.assertNotIn(path.suffix.lower(), excluded_suffixes)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)

    def test_package_and_runtime_versions_match(self) -> None:
        project = BUILDER._project_version(ROOT / "pyproject.toml")
        runtime = BUILDER._runtime_version(
            ROOT / "skill" / "img2blockbench" / "scripts" / "img2blockbench.py"
        )
        self.assertEqual("0.3.0", project)
        self.assertEqual(project, runtime)

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for module in (ROOT / "skill" / "img2blockbench" / "scripts").glob(
            "*.py"
        ):
            self.assertIn(f'"{module.stem}"', pyproject, module.name)

    def test_local_links_resolve_inside_compact_release(self) -> None:
        policy = BUILDER._load_policy(ROOT / "release" / "manifest.json")
        files = BUILDER.collect_release_files(ROOT, policy)
        included = {path.as_posix() for path in files}
        link_pattern = re.compile(r"\[[^]]*\]\(([^)]+)\)")
        for relative in files:
            if relative.suffix.lower() != ".md":
                continue
            text = (ROOT / relative).read_text(encoding="utf-8")
            for value in link_pattern.findall(text):
                target = value.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                normalized = posixpath.normpath(
                    (PurePosixPath(relative.parent.as_posix()) / target).as_posix()
                )
                self.assertFalse(normalized.startswith("../"), value)
                self.assertIn(normalized, included, f"{relative}: {value}")

    def test_build_is_deterministic_and_external_manifest_verifies_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            first = BUILDER.build_release(
                output / "first.zip",
                repository_root=ROOT,
                policy_path=ROOT / "release" / "manifest.json",
                allow_dirty=True,
            )
            second = BUILDER.build_release(
                output / "second.zip",
                repository_root=ROOT,
                policy_path=ROOT / "release" / "manifest.json",
                allow_dirty=True,
            )
            default_named = BUILDER.build_release(
                output / "directory-output",
                repository_root=ROOT,
                policy_path=ROOT / "release" / "manifest.json",
                allow_dirty=True,
            )

            first_zip = Path(first["bundle"])
            second_zip = Path(second["bundle"])
            self.assertEqual(first_zip.read_bytes(), second_zip.read_bytes())
            self.assertEqual(0o644, first_zip.stat().st_mode & 0o777)
            self.assertLess(first_zip.stat().st_size, 2 * 1024 * 1024)
            self.assertEqual(first["bundle_sha256"], second["bundle_sha256"])
            self.assertEqual(
                f"img2blockbench-platform-{default_named['version']}.zip",
                Path(default_named["bundle"]).name,
            )

            external_manifest = json.loads(
                Path(first["manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(first["bundle_sha256"], external_manifest["bundle"]["sha256"])
            self.assertEqual(first_zip.stat().st_size, external_manifest["bundle"]["bytes"])
            archive_root = external_manifest["bundle"]["archive_root"]
            expected = {
                f"{archive_root}/{record['path']}": record
                for record in external_manifest["contents"]
            }
            with zipfile.ZipFile(first_zip) as archive:
                self.assertEqual(set(expected), set(archive.namelist()))
                for name, record in expected.items():
                    data = archive.read(name)
                    self.assertEqual(record["bytes"], len(data))
                    self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
                    relative = Path(record["path"])
                    self.assertNotIn(
                        relative.parts[0],
                        {"benchmarks", "demo", "examples", "tests", "tools"},
                    )

            checksum_lines = Path(first["checksums"]).read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(
                [
                    f"{_sha256(first_zip)}  {first_zip.name}",
                    f"{_sha256(Path(first['manifest']))}  {Path(first['manifest']).name}",
                ],
                checksum_lines,
            )

    def test_portability_check_rejects_absolute_workstation_paths(self) -> None:
        for text in (
            "input=/Users/alice/Downloads/source.glb",
            "input=/home/alice/source.glb",
            r"input=C:\Users\alice\source.glb",
            "input=file:///Users/alice/source.glb",
        ):
            with self.subTest(text=text):
                with self.assertRaises(BUILDER.ReleaseError):
                    BUILDER._portable_text(
                        Path("PLATFORM.md"), text.encode("utf-8"), ROOT
                    )

    def test_dirty_worktree_requires_explicit_development_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                BUILDER,
                "_git_metadata",
                return_value=("a" * 40, True),
            ):
                with self.assertRaisesRegex(BUILDER.ReleaseError, "--allow-dirty"):
                    BUILDER.build_release(
                        Path(temporary) / "release.zip",
                        repository_root=ROOT,
                        policy_path=ROOT / "release" / "manifest.json",
                    )


if __name__ == "__main__":
    unittest.main()
