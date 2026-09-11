#!/usr/bin/env python3
"""Canonical model-content provenance shared by reconstruction and builds."""

from __future__ import annotations

import hashlib
import json
from typing import Any


MODEL_CONTENT_HASH_METHOD = "canonical-model-content-v1"


def model_content_sha256(spec: dict[str, Any]) -> str:
    """Hash model content while ignoring build-local provenance paths.

    Delivery builds rewrite reference, review, and mesh locations without
    changing the model. The canonical fingerprint excludes only those
    packaging fields while retaining geometry, materials, texture rules,
    source hashes, semantics, and all other authored content.
    """
    canonical = json.loads(json.dumps(spec))
    reference = canonical.get("reference")
    if isinstance(reference, dict):
        for key in (
            "image",
            "source_file_name",
            "bundled",
            "availability",
            "required_for_model_use",
        ):
            reference.pop(key, None)
    generation = canonical.get("generation")
    if isinstance(generation, dict):
        generation.pop("multi_angle_review", None)
        generation.pop("model_review", None)
        mesh = generation.get("mesh")
        if isinstance(mesh, dict):
            for key in ("path", "source_file_name", "bundled", "availability"):
                mesh.pop(key, None)
        if not generation:
            canonical.pop("generation")
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
