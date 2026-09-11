#!/usr/bin/env python3
"""Build a deterministic, media-free img2blockbench platform release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPOSITORY_ROOT / "release" / "manifest.json"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
GIT_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
WINDOWS_USER_PATH_RE = re.compile(r"(?i)(?:^|[^A-Za-z0-9])[A-Z]:\\Users\\")
POSIX_WORKSTATION_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=(])/(?:Users|home|tmp|var/folders)/[^\s\"'`)]*"
)


class ReleaseError(ValueError):
    """Raised when a platform release would be incomplete or non-portable."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"cannot read release policy {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseError("release policy must be a JSON object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _string_list(policy: dict[str, Any], key: str) -> list[str]:
    value = policy.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ReleaseError(f"release policy {key} must be a non-empty string array")
    return value


def _safe_relative_path(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ReleaseError(f"{label} must be a safe relative path: {value}")
    return path


def _load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = _read_json(path)
    if policy.get("schema_version") != 1:
        raise ReleaseError("release policy schema_version must be 1")
    name = policy.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise ReleaseError("release policy name is invalid")
    if policy.get("version_source") != "pyproject.toml":
        raise ReleaseError("release policy version_source must be pyproject.toml")
    for key in (
        "required_files",
        "optional_files",
        "excluded_roots",
        "excluded_suffixes",
        "capabilities",
        "cli_commands",
        "artifact_contract",
        "known_limits",
    ):
        _string_list(policy, key)
    for key in ("platform_status", "supported_python"):
        if not isinstance(policy.get(key), str) or not policy[key]:
            raise ReleaseError(f"release policy {key} must be a non-empty string")
    if policy.get("model_spec_schema") != 1:
        raise ReleaseError("release policy model_spec_schema must be 1")
    research_status = policy.get("research_status")
    if not isinstance(research_status, dict) or not research_status or not all(
        isinstance(key, str)
        and key
        and isinstance(value, str)
        and value
        for key, value in research_status.items()
    ):
        raise ReleaseError(
            "release policy research_status must be a non-empty string map"
        )
    trees = policy.get("required_trees")
    if not isinstance(trees, list) or not trees:
        raise ReleaseError("release policy required_trees must be a non-empty array")
    for index, tree in enumerate(trees):
        if not isinstance(tree, dict):
            raise ReleaseError(f"required_trees[{index}] must be an object")
        _safe_relative_path(str(tree.get("path", "")), f"required_trees[{index}].path")
        suffixes = tree.get("suffixes")
        if not isinstance(suffixes, list) or not suffixes or not all(
            isinstance(suffix, str) and suffix.startswith(".") for suffix in suffixes
        ):
            raise ReleaseError(
                f"required_trees[{index}].suffixes must be a non-empty suffix array"
            )
    return policy


def _project_version(pyproject_path: Path) -> str:
    """Read the static project version without adding a Python 3.10 TOML dependency."""
    in_project = False
    version: str | None = None
    for line in pyproject_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if not in_project:
            continue
        match = re.fullmatch(r'version\s*=\s*["\']([^"\']+)["\']', stripped)
        if match:
            version = match.group(1)
            break
    if version is None or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]*", version):
        raise ReleaseError("pyproject.toml must contain one static [project] version")
    return version


def _runtime_version(module_path: Path) -> str:
    """Read the CLI version and reject drift from packaging metadata."""
    pattern = re.compile(r'^VERSION\s*=\s*["\']([^"\']+)["\']$')
    for line in module_path.read_text(encoding="utf-8").splitlines():
        match = pattern.fullmatch(line.strip())
        if match:
            return match.group(1)
    raise ReleaseError("img2blockbench.py must declare a static VERSION")


def _excluded(relative: Path, policy: dict[str, Any]) -> str | None:
    first = relative.parts[0]
    if first in set(_string_list(policy, "excluded_roots")):
        return f"excluded root {first}"
    if relative.suffix.lower() in {
        suffix.lower() for suffix in _string_list(policy, "excluded_suffixes")
    }:
        return f"excluded suffix {relative.suffix.lower()}"
    return None


def _portable_text(relative: Path, data: bytes, repository_root: Path) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseError(f"release file is not UTF-8 text: {relative.as_posix()}") from exc
    forbidden_literals = {
        repository_root.resolve().as_posix(),
        Path.home().resolve().as_posix(),
        "/private/var/folders/",
        "file://",
    }
    found = next((value for value in sorted(forbidden_literals) if value in text), None)
    if found is not None:
        raise ReleaseError(
            f"release file contains an absolute workstation path: {relative.as_posix()}"
        )
    if POSIX_WORKSTATION_PATH_RE.search(text) or WINDOWS_USER_PATH_RE.search(text):
        raise ReleaseError(
            f"release file contains an absolute workstation path: {relative.as_posix()}"
        )


def collect_release_files(
    repository_root: Path, policy: dict[str, Any]
) -> list[Path]:
    """Return the explicit, validated production allowlist for the release."""
    root = repository_root.resolve()
    relative_paths: set[Path] = set()
    for value in _string_list(policy, "required_files"):
        relative = _safe_relative_path(value, "required file")
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ReleaseError(f"required release file is missing or unsafe: {value}")
        relative_paths.add(relative)

    for index, tree in enumerate(policy["required_trees"]):
        tree_relative = _safe_relative_path(
            str(tree["path"]), f"required_trees[{index}].path"
        )
        tree_path = root / tree_relative
        if not tree_path.is_dir() or tree_path.is_symlink():
            raise ReleaseError(
                f"required release tree is missing or unsafe: {tree_relative.as_posix()}"
            )
        suffixes = {str(suffix).lower() for suffix in tree["suffixes"]}
        matches = [
            path
            for path in tree_path.rglob("*")
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in suffixes
        ]
        if not matches:
            raise ReleaseError(
                f"required release tree has no allowed files: {tree_relative.as_posix()}"
            )
        relative_paths.update(path.relative_to(root) for path in matches)

    for value in _string_list(policy, "optional_files"):
        relative = _safe_relative_path(value, "optional file")
        path = root / relative
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise ReleaseError(f"optional release path is unsafe: {value}")
            relative_paths.add(relative)

    files = sorted(relative_paths, key=lambda path: path.as_posix())
    for relative in files:
        reason = _excluded(relative, policy)
        if reason is not None:
            raise ReleaseError(
                f"release allowlist contains {reason}: {relative.as_posix()}"
            )
        _portable_text(relative, (root / relative).read_bytes(), root)
    return files


def _git_metadata(repository_root: Path) -> tuple[str, bool]:
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseError(f"cannot inspect Git release state: {exc}") from exc
    if Path(top_level).resolve() != repository_root.resolve():
        raise ReleaseError("release builder must run from its own Git worktree")
    if not GIT_COMMIT_RE.fullmatch(commit):
        raise ReleaseError("Git HEAD is not a full lowercase commit hash")
    return commit, bool(status.strip())


def _output_paths(output: Path, name: str, version: str) -> tuple[Path, Path, Path]:
    if output.suffix.lower() == ".zip":
        bundle = output
    else:
        bundle = output / f"{name}-{version}.zip"
    manifest = bundle.with_suffix(".manifest.json")
    checksums = bundle.with_suffix(".sha256")
    if len({bundle.resolve(), manifest.resolve(), checksums.resolve()}) != 3:
        raise ReleaseError("release output paths must be distinct")
    for path in (bundle, manifest, checksums):
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise ReleaseError(f"release output is not a regular file: {path}")
    return bundle, manifest, checksums


def _write_zip(
    destination: Path,
    files: dict[Path, bytes],
    archive_root: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative, data in files.items():
                archive_name = f"{archive_root}/{relative.as_posix()}"
                info = zipfile.ZipInfo(archive_name, ZIP_TIMESTAMP)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        os.replace(temporary_path, destination)
        destination.chmod(0o644)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_release(
    output: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    policy_path: Path = POLICY_PATH,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    """Build a deterministic ZIP and external integrity metadata."""
    repository_root = repository_root.resolve()
    policy = _load_policy(policy_path)
    version = _project_version(repository_root / str(policy["version_source"]))
    runtime_version = _runtime_version(
        repository_root / "skill" / "img2blockbench" / "scripts" / "img2blockbench.py"
    )
    if runtime_version != version:
        raise ReleaseError(
            f"project version {version} does not match CLI version {runtime_version}"
        )
    files = collect_release_files(repository_root, policy)
    commit, dirty = _git_metadata(repository_root)
    if dirty and not allow_dirty:
        raise ReleaseError(
            "repository has tracked or untracked changes; commit them or pass "
            "--allow-dirty for a development-only bundle"
        )
    snapshots = {
        relative: (repository_root / relative).read_bytes() for relative in files
    }
    for relative, data in snapshots.items():
        _portable_text(relative, data, repository_root)

    bundle_path, manifest_path, checksum_path = _output_paths(
        output.resolve(), str(policy["name"]), version
    )
    archive_root = f"{policy['name']}-{version}"
    _write_zip(bundle_path, snapshots, archive_root)
    bundle_sha256 = _sha256_file(bundle_path)
    contents = [
        {
            "path": relative.as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for relative, data in snapshots.items()
    ]
    manifest = {
        "schema_version": 1,
        "name": policy["name"],
        "version": version,
        "source": {"commit": commit, "dirty": dirty},
        "bundle": {
            "path": bundle_path.name,
            "archive_root": archive_root,
            "bytes": bundle_path.stat().st_size,
            "sha256": bundle_sha256,
        },
        "contents": contents,
        "platform_status": policy["platform_status"],
        "model_spec_schema": policy["model_spec_schema"],
        "supported_python": policy["supported_python"],
        "capabilities": policy["capabilities"],
        "cli_commands": policy["cli_commands"],
        "artifact_contract": policy["artifact_contract"],
        "research_status": policy["research_status"],
        "known_limits": policy["known_limits"],
        "excluded_roots": policy["excluded_roots"],
        "excluded_suffixes": policy["excluded_suffixes"],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(manifest_path, manifest)
    manifest_sha256 = _sha256_file(manifest_path)
    checksum_path.write_text(
        f"{bundle_sha256}  {bundle_path.name}\n"
        f"{manifest_sha256}  {manifest_path.name}\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "bundle": str(bundle_path),
        "bundle_sha256": bundle_sha256,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "checksums": str(checksum_path),
        "files": len(files),
        "version": version,
        "source_commit": commit,
        "source_dirty": dirty,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Build the lean, deterministic img2blockbench platform bundle."
    )
    result.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination ZIP path, or a directory for the default versioned filename",
    )
    result.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Permit a development bundle from an uncommitted worktree",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = build_release(args.output, allow_dirty=args.allow_dirty)
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
