#!/usr/bin/env python3
"""Build a portable Atlus bundle without copying private reference images."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from img2blockbench import (
    build_model,
    deterministic_zip,
    portable_source_filename,
    read_json,
    sha256_file,
    write_json,
)


CYCLE = Path(__file__).resolve().parent
SPEC_PATH = CYCLE / "model-spec.json"
BUILD = CYCLE / "build"


def artifact_record(path: Path) -> dict[str, Any]:
    """Return deterministic integrity metadata for one release artifact."""
    return {
        "path": path.relative_to(BUILD).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> None:
    """Compile Atlus, sanitize private-source metadata, and rebuild its ZIP."""
    source_spec = read_json(SPEC_PATH)
    result = build_model(SPEC_PATH, BUILD)
    model_id = str(source_spec["id"])
    reference_copy = BUILD / f"{model_id}.reference.png"
    reference_copy.unlink(missing_ok=True)

    delivery_spec_path = BUILD / f"{model_id}.model-spec.json"
    delivery_spec = read_json(delivery_spec_path)
    source_reference_path = Path(str(source_spec["reference"]["image"]))
    if not source_reference_path.is_absolute():
        source_reference_path = (SPEC_PATH.parent / source_reference_path).resolve()
    private_reference = {
        "image": portable_source_filename(str(source_spec["reference"]["image"])),
        "sha256": source_spec["reference"]["sha256"],
        "width": source_spec["reference"]["width"],
        "height": source_spec["reference"]["height"],
        "bundled": False,
        "availability": "private-optional",
        "required_for_model_use": False,
    }
    delivery_reference = dict(private_reference)
    delivery_reference["image"] = Path(
        os.path.relpath(source_reference_path, BUILD.resolve())
    ).as_posix()
    delivery_spec["reference"] = delivery_reference
    write_json(delivery_spec_path, delivery_spec)

    manifest_path = BUILD / f"{model_id}.manifest.json"
    manifest = read_json(manifest_path)
    retained_paths = []
    for record in manifest["artifacts"]:
        relative = Path(str(record["path"]))
        if relative.name == reference_copy.name:
            continue
        path = BUILD / relative
        if path.is_file():
            retained_paths.append(path)
    manifest["reference"] = dict(private_reference)
    manifest["private_optional_artifacts"] = [
        {
            "kind": "source_reference",
            "filename": private_reference["image"],
            "sha256": private_reference["sha256"],
            "bundled": False,
            "required_for_model_use": False,
        }
    ]
    manifest["artifacts"] = [artifact_record(path) for path in retained_paths]
    write_json(manifest_path, manifest)

    archive_path = BUILD / f"{model_id}.zip"
    deterministic_zip(archive_path, [*retained_paths, manifest_path], BUILD)
    result["bundle"] = str(archive_path.resolve())
    result["reference"] = private_reference
    result["manifest"] = str(manifest_path.resolve())
    result["private_reference_copied"] = False
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
