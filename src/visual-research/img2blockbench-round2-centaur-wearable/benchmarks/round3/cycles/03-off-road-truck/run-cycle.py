#!/usr/bin/env python3
"""Run one hash-locked Round 3 mesh reconstruction cycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


RUNNER_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIRECTORY = RUNNER_REPOSITORY_ROOT / "skill" / "img2blockbench" / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import img2blockbench  # noqa: E402
from mesh_reconstruction import (  # noqa: E402
    MeshReconstructionOptions,
    reconstruct_mesh_spec,
)


REQUIRED_VIEWS = (
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "isometric",
)


class CycleBlocker(Exception):
    """Report an expected input blocker without claiming benchmark success."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _resolved_child(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be relative: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes {resolved_root}: {relative}") from exc
    return resolved


def _required_object(owner: dict[str, Any], key: str) -> dict[str, Any]:
    value = owner.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _required_string(owner: dict[str, Any], key: str) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _validate_configuration(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("cycle config schema_version must be 1")
    _required_string(config, "cycle_id")
    model = _required_object(config, "model")
    _required_string(model, "id")
    _required_string(model, "description")
    _required_string(model, "subject_type")
    source = _required_object(config, "source")
    relative_path = _required_string(source, "relative_path")
    if Path(relative_path).suffix.lower() not in {".glb", ".gltf"}:
        raise ValueError("source.relative_path must identify a GLB or GLTF")
    for key in ("provider", "provider_model", "license"):
        _required_string(source, key)
    outputs = _required_object(config, "outputs")
    for key in ("input_contract", "model_spec", "evidence", "build", "results"):
        _required_string(outputs, key)
    review = _required_object(config, "review")
    if tuple(review.get("required_views", ())) != REQUIRED_VIEWS:
        raise ValueError(
            "review.required_views must be front, back, left, right, top, "
            "bottom, isometric"
        )
    options = _required_object(config, "reconstruction")
    for key in (
        "resolution",
        "max_cuboids",
        "target_size",
        "palette_size",
        "fill_mode",
        "surface_thickness",
        "min_component_voxels",
        "min_component_fraction",
        "geometry_precision",
        "texture_density",
    ):
        if key not in options:
            raise ValueError(f"reconstruction.{key} is required")


def _output_paths(config: dict[str, Any], cycle_directory: Path) -> dict[str, Path]:
    outputs = _required_object(config, "outputs")
    return {
        key: _resolved_child(cycle_directory, _required_string(outputs, key), key)
        for key in ("input_contract", "model_spec", "evidence", "build", "results")
    }


def _validate_contract(
    config: dict[str, Any], contract: dict[str, Any], actual_sha256: str, byte_length: int
) -> bool:
    if contract.get("schema_version") != 1:
        raise ValueError("input contract schema_version must be 1")
    if contract.get("cycle_id") != config["cycle_id"]:
        raise ValueError("input contract cycle_id disagrees with cycle config")
    configured_source = _required_object(config, "source")
    contracted_source = _required_object(contract, "source")
    for key in ("relative_path", "provider", "provider_model", "license"):
        if contracted_source.get(key) != configured_source.get(key):
            raise ValueError(f"input contract source.{key} disagrees with config")
    locked_sha256 = contracted_source.get("sha256")
    if locked_sha256 is None:
        return False
    if not isinstance(locked_sha256, str) or len(locked_sha256) != 64:
        raise ValueError("input contract source.sha256 must be null or 64 hex characters")
    if any(character not in "0123456789abcdef" for character in locked_sha256):
        raise ValueError("input contract source.sha256 must be lowercase hexadecimal")
    if actual_sha256 != locked_sha256:
        raise CycleBlocker(
            "SOURCE_HASH_MISMATCH",
            "private source mesh differs from the hash locked by the first "
            f"successful run (expected {locked_sha256}, got {actual_sha256})",
        )
    locked_bytes = contracted_source.get("byte_length")
    if locked_bytes is not None and locked_bytes != byte_length:
        raise CycleBlocker(
            "SOURCE_SIZE_MISMATCH",
            "private source mesh byte length differs from the locked input contract",
        )
    return True


def _lock_contract(
    config: dict[str, Any], contract: dict[str, Any], sha256: str, byte_length: int
) -> dict[str, Any]:
    locked = json.loads(json.dumps(contract))
    locked["status"] = "locked-after-successful-reconstruction"
    locked_source = _required_object(locked, "source")
    locked_source["sha256"] = sha256
    locked_source["byte_length"] = byte_length
    locked_source["format"] = Path(config["source"]["relative_path"]).suffix.lower()[1:]
    return locked


def _options(config: dict[str, Any]) -> MeshReconstructionOptions:
    source = _required_object(config, "source")
    values = _required_object(config, "reconstruction")
    transform = values.get("canonical_transform")
    return MeshReconstructionOptions(
        resolution=int(values["resolution"]),
        max_cuboids=int(values["max_cuboids"]),
        target_size=float(values["target_size"]),
        palette_size=int(values["palette_size"]),
        fill_mode=str(values["fill_mode"]),
        surface_thickness=int(values["surface_thickness"]),
        min_component_voxels=int(values["min_component_voxels"]),
        min_component_fraction=float(values["min_component_fraction"]),
        canonical_transform=(
            tuple(float(value) for value in transform)
            if transform is not None
            else None
        ),
        geometry_precision=int(values["geometry_precision"]),
        texture_density=int(values["texture_density"]),
        provider=str(source["provider"]),
        provider_model=str(source["provider_model"]),
        source_license=str(source["license"]),
    )


def _verify_review(
    evidence: dict[str, Any], model_spec_path: Path, source_sha256: str
) -> Path:
    review = _required_object(evidence, "multi_angle_review")
    if tuple(review.get("required_views", ())) != REQUIRED_VIEWS:
        raise ValueError("mesh evidence does not require all seven review views")
    if tuple(review.get("generated_views", ())) != REQUIRED_VIEWS:
        raise ValueError("mesh evidence did not generate all seven review views")
    if not review.get("complete") or review.get("view_count") != 7:
        raise ValueError("multi-angle review is incomplete")
    overlap = _required_object(evidence, "source_mesh_overlap")
    if not _required_object(overlap, "anti_pancake_gate").get("passed"):
        raise ValueError("source-relative anti-pancake gate failed")
    manifest_path = _resolved_child(
        model_spec_path.parent, _required_string(review, "manifest"), "review manifest"
    )
    if not manifest_path.is_file():
        raise ValueError(f"review manifest was not emitted: {manifest_path}")
    if _sha256(manifest_path) != review.get("manifest_sha256"):
        raise ValueError("review manifest hash disagrees with mesh evidence")
    manifest = _read_json(manifest_path)
    if tuple(manifest.get("required_views", ())) != REQUIRED_VIEWS:
        raise ValueError("review manifest required-view contract changed")
    if tuple(manifest.get("generated_views", ())) != REQUIRED_VIEWS:
        raise ValueError("review manifest is missing a required view")
    if manifest.get("source_mesh", {}).get("sha256") != source_sha256:
        raise ValueError("review manifest is not bound to the current source mesh")
    views = manifest.get("views")
    if not isinstance(views, list) or len(views) != 7:
        raise ValueError("review manifest must contain exactly seven views")
    for view in views:
        image_path = _resolved_child(
            manifest_path.parent,
            _required_string(view, "image"),
            f"{view.get('id', 'unknown')} review image",
        )
        if not image_path.is_file() or _sha256(image_path) != view.get("image_sha256"):
            raise ValueError(f"review image hash failed: {image_path}")
    return manifest_path


def _verify_packaged_review(
    build_result: dict[str, Any], build_directory: Path, model_id: str
) -> Path:
    """Verify the portable build and ZIP contain every hash-bound review image."""
    manifest_value = build_result.get("multi_angle_review_manifest")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise ValueError("native build did not report its packaged review manifest")
    build_root = build_directory.resolve()
    manifest_path = Path(manifest_value).resolve()
    try:
        manifest_path.relative_to(build_root)
    except ValueError as exc:
        raise ValueError("packaged review manifest escapes the build directory") from exc
    if manifest_path != build_root / f"{model_id}.mesh-views.json":
        raise ValueError("packaged review manifest has an unexpected path")
    manifest = _read_json(manifest_path)
    if tuple(manifest.get("generated_views", ())) != REQUIRED_VIEWS:
        raise ValueError("packaged review manifest is missing a required view")
    views = manifest.get("views")
    if not isinstance(views, list) or len(views) != 7:
        raise ValueError("packaged review manifest must contain exactly seven views")

    expected_paths = {f"{model_id}.mesh-views.json"}
    for view in views:
        image_value = _required_string(view, "image")
        image_relative = Path(image_value)
        if image_relative.is_absolute() or ".." in image_relative.parts:
            raise ValueError(f"packaged review image path is unsafe: {image_value}")
        image_path = (build_root / image_relative).resolve()
        try:
            image_path.relative_to(build_root)
        except ValueError as exc:
            raise ValueError(
                f"packaged review image escapes the build directory: {image_value}"
            ) from exc
        if not image_path.is_file() or _sha256(image_path) != view.get("image_sha256"):
            raise ValueError(f"packaged review image hash failed: {image_path}")
        expected_paths.add(image_relative.as_posix())

    build_manifest_path = build_root / f"{model_id}.manifest.json"
    build_manifest = _read_json(build_manifest_path)
    manifest_artifacts = build_manifest.get("artifacts")
    if not isinstance(manifest_artifacts, list):
        raise ValueError("native build manifest artifacts must be an array")
    artifact_by_path = {
        artifact.get("path"): artifact
        for artifact in manifest_artifacts
        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str)
    }
    for relative in artifact_by_path:
        artifact_relative = Path(relative)
        if artifact_relative.is_absolute() or ".." in artifact_relative.parts:
            raise ValueError(f"native build manifest contains an unsafe path: {relative}")
    if not expected_paths.issubset(artifact_by_path):
        missing = sorted(expected_paths - set(artifact_by_path))
        raise ValueError(f"native build manifest omits review artifacts: {missing}")
    for relative in expected_paths:
        artifact_path = build_root / relative
        if artifact_by_path[relative].get("sha256") != _sha256(artifact_path):
            raise ValueError(f"native build manifest hash failed: {relative}")

    delivery_spec = _read_json(build_root / f"{model_id}.model-spec.json")
    delivery_review = _required_object(
        _required_object(delivery_spec, "generation"), "multi_angle_review"
    )
    if delivery_review.get("manifest") != manifest_path.name:
        raise ValueError("delivered model spec does not use the packaged review manifest")
    if delivery_review.get("manifest_sha256") != _sha256(manifest_path):
        raise ValueError("delivered model spec review manifest hash failed")
    packaged_source = _required_object(manifest, "source_mesh")
    delivered_mesh = _required_object(
        _required_object(delivery_spec, "generation"), "mesh"
    )
    for label, source_metadata in (
        ("packaged review", packaged_source),
        ("delivered model spec", delivered_mesh),
    ):
        if "path" in source_metadata:
            raise ValueError(f"{label} leaks a working source path")
        if source_metadata.get("availability") != "external-provenance-only":
            raise ValueError(f"{label} does not disclose external-only source media")
        if source_metadata.get("bundled") is not False:
            raise ValueError(f"{label} incorrectly claims the source mesh is bundled")
    portable_json = json.dumps(
        {"review_manifest": manifest, "model_spec": delivery_spec},
        sort_keys=True,
    )
    for forbidden in ("/Users/", "/home/", ":\\\\Users\\\\", "../"):
        if forbidden in portable_json:
            raise ValueError(f"portable build metadata contains unsafe path text: {forbidden}")

    bundle_path = build_root / f"{model_id}.zip"
    with zipfile.ZipFile(bundle_path) as bundle:
        bundle_names = set(bundle.namelist())
        for relative in bundle_names:
            bundle_relative = Path(relative)
            if bundle_relative.is_absolute() or ".." in bundle_relative.parts:
                raise ValueError(f"native bundle contains an unsafe path: {relative}")
        if not expected_paths.issubset(bundle_names):
            missing = sorted(expected_paths - bundle_names)
            raise ValueError(f"native bundle omits review artifacts: {missing}")
        for relative in expected_paths:
            if hashlib.sha256(bundle.read(relative)).hexdigest() != _sha256(
                build_root / relative
            ):
                raise ValueError(f"native bundle review hash failed: {relative}")
    return manifest_path


def _artifact(cycle_directory: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(cycle_directory.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def execute_cycle(config_path: Path, repository_root: Path) -> dict[str, Any]:
    """Execute one configured cycle and return an awaiting-review result."""
    config_path = config_path.resolve()
    cycle_directory = config_path.parent
    config = _read_json(config_path)
    _validate_configuration(config)
    outputs = _output_paths(config, cycle_directory)
    source = _required_object(config, "source")
    source_path = _resolved_child(
        repository_root, _required_string(source, "relative_path"), "source mesh"
    )
    if not source_path.is_file():
        raise CycleBlocker(
            "MISSING_PRIVATE_INPUT",
            "copy the user-supplied GLB to "
            f"{source['relative_path']}; this cycle has not run and has no PASS claim",
        )
    try:
        byte_length = source_path.stat().st_size
        source_sha256 = _sha256(source_path)
    except OSError as exc:
        raise CycleBlocker(
            "UNREADABLE_PRIVATE_INPUT",
            f"cannot read {source['relative_path']}: {exc}",
        ) from exc

    contract = _read_json(outputs["input_contract"])
    already_locked = _validate_contract(config, contract, source_sha256, byte_length)
    model = _required_object(config, "model")
    spec, evidence = reconstruct_mesh_spec(
        source_path,
        outputs["model_spec"],
        _required_string(model, "id"),
        _required_string(model, "description"),
        _required_string(model, "subject_type"),
        _options(config),
    )
    validation_errors = img2blockbench.validate_spec(spec, strict=True)
    if validation_errors:
        raise ValueError(
            "mesh reconstruction produced an invalid model spec: "
            + "; ".join(validation_errors)
        )
    img2blockbench.write_json(outputs["model_spec"], spec)
    img2blockbench.write_json(outputs["evidence"], evidence)
    source_manifest_path = _verify_review(
        evidence, outputs["model_spec"], source_sha256
    )
    build_result = img2blockbench.build_model(outputs["model_spec"], outputs["build"])
    if not build_result.get("ok") or not build_result.get("audit", {}).get("ok"):
        raise ValueError("native Blockbench build audit failed")
    manifest_path = _verify_packaged_review(
        build_result, outputs["build"], _required_string(model, "id")
    )

    if not already_locked:
        _write_json(
            outputs["input_contract"],
            _lock_contract(config, contract, source_sha256, byte_length),
        )

    build_manifest = outputs["build"] / f"{model['id']}.manifest.json"
    bbmodel = outputs["build"] / f"{model['id']}.bbmodel"
    return {
        "schema_version": 1,
        "cycle_id": config["cycle_id"],
        "model_id": model["id"],
        "status": "AWAITING_AGENT_VISUAL_REVIEW",
        "pass_claimed": False,
        "source": {
            "relative_path": source["relative_path"],
            "sha256": source_sha256,
            "byte_length": byte_length,
            "hash_was_already_locked": already_locked,
        },
        "automated_gates": {
            "strict_model_spec_valid": True,
            "native_build_audit_ok": True,
            "source_relative_anti_pancake_gate": True,
            "all_seven_review_views_emitted_and_hash_bound": True,
        },
        "visual_review": {
            "required": True,
            "status": "pending",
            "required_views": list(REQUIRED_VIEWS),
            "approval_rule": (
                "A separate read-only agent must inspect every view; automated "
                "geometry evidence alone cannot pass the asset."
            ),
        },
        "artifacts": {
            "model_spec": _artifact(cycle_directory, outputs["model_spec"]),
            "mesh_evidence": _artifact(cycle_directory, outputs["evidence"]),
            "source_review_manifest": _artifact(
                cycle_directory, source_manifest_path
            ),
            "review_manifest": _artifact(cycle_directory, manifest_path),
            "build_manifest": _artifact(cycle_directory, build_manifest),
            "bbmodel": _artifact(cycle_directory, bbmodel),
            "bundle": _artifact(
                cycle_directory, outputs["build"] / f"{model['id']}.zip"
            ),
        },
    }


def run_cycle(config_path: Path, repository_root: Path) -> tuple[int, dict[str, Any]]:
    """Run a cycle and always persist an honest machine-readable status."""
    config = _read_json(config_path)
    _validate_configuration(config)
    outputs = _output_paths(config, config_path.resolve().parent)
    try:
        result = execute_cycle(config_path, repository_root)
        exit_code = 0
    except CycleBlocker as exc:
        result = {
            "schema_version": 1,
            "cycle_id": config["cycle_id"],
            "status": "BLOCKED",
            "pass_claimed": False,
            "blocker": {"code": exc.code, "message": str(exc)},
            "visual_review": {
                "required": True,
                "status": "not-started",
                "required_views": list(REQUIRED_VIEWS),
            },
            "outputs_generated_this_run": False,
        }
        exit_code = 2
    except Exception as exc:
        result = {
            "schema_version": 1,
            "cycle_id": config["cycle_id"],
            "status": "FAILED",
            "pass_claimed": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "visual_review": {
                "required": True,
                "status": "not-started",
                "required_views": list(REQUIRED_VIEWS),
            },
        }
        exit_code = 1
    _write_json(outputs["results"], result)
    return exit_code, result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("cycle.json"),
        help="Cycle configuration JSON (default: cycle.json beside this runner)",
    )
    root.add_argument(
        "--repository-root",
        type=Path,
        default=RUNNER_REPOSITORY_ROOT,
        help="Repository root used to resolve the ignored source path",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    exit_code, result = run_cycle(args.config, args.repository_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
