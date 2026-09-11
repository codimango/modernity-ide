#!/usr/bin/env python3
"""Deterministic compiler for agent-authored Minecraft model specifications."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import os
import re
import sys
import uuid
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from mesh_reconstruction import MeshReconstructionOptions, reconstruct_mesh_spec
from model_provenance import MODEL_CONTENT_HASH_METHOD, model_content_sha256
from photo_reconstruction import (
    PhotoReconstructionOptions,
    reconstruct_photo_spec,
    render_relief_evidence,
    segment_foreground,
    write_segmentation_diagnostics,
)
from view_reconstruction import (
    ViewReconstructionOptions,
    extract_clip_view_manifest,
    reconstruct_view_spec,
)
from wearable_export import (
    make_bedrock_attachable,
    make_wearable_spec,
    validate_wearable,
)


VERSION = "0.3.0"
SCHEMA_VERSION = 1
FACES = ("north", "east", "south", "west", "up", "down")
FACE_AXES = {
    "east": (0, 2, 1, 1),
    "west": (0, 2, 1, -1),
    "up": (1, 0, 2, 1),
    "down": (1, 0, 2, -1),
    "south": (2, 0, 1, 1),
    "north": (2, 0, 1, -1),
}
PATTERNS = {"solid", "dither", "stripes", "spots", "gradient"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NAMESPACE = uuid.UUID("ea6903e8-4e53-4fc1-9713-a6f1937a9c03")
MAX_CUBOIDS = 192


class ModelSpecError(ValueError):
    """Raised when a model specification or generated model is invalid."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelSpecError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelSpecError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "/".join(parts)))


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def valid_vector(
    value: Any,
    length: int,
    label: str,
    errors: list[str],
    *,
    positive: bool = False,
) -> bool:
    if not isinstance(value, list) or len(value) != length:
        errors.append(f"{label} must be a {length}-number array")
        return False
    if not all(finite_number(item) for item in value):
        errors.append(f"{label} must contain finite numbers")
        return False
    if positive and not all(float(item) > 0 for item in value):
        errors.append(f"{label} values must be positive")
        return False
    return True


def validate_spec(spec: Any, *, strict: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["model specification must be a JSON object"]

    require(spec.get("schema_version") == SCHEMA_VERSION, "schema_version must be 1", errors)
    model_id = spec.get("id")
    require(isinstance(model_id, str) and bool(ID_RE.fullmatch(model_id)), "id is invalid", errors)

    reference = spec.get("reference")
    if not isinstance(reference, dict):
        errors.append("reference must be an object")
    else:
        require(isinstance(reference.get("image"), str) and bool(reference["image"]), "reference.image is required", errors)
        require(isinstance(reference.get("sha256"), str) and bool(SHA_RE.fullmatch(reference["sha256"])), "reference.sha256 must be lowercase SHA-256", errors)
        require(isinstance(reference.get("width"), int) and reference["width"] > 0, "reference.width must be a positive integer", errors)
        require(isinstance(reference.get("height"), int) and reference["height"] > 0, "reference.height must be a positive integer", errors)

    subject = spec.get("subject")
    if not isinstance(subject, dict):
        errors.append("subject must be an object")
    else:
        require(isinstance(subject.get("type"), str) and bool(subject["type"]), "subject.type is required", errors)
        require(isinstance(subject.get("description"), str) and bool(subject["description"]), "subject.description is required", errors)
        require(subject.get("symmetry") in {"bilateral", "radial", "asymmetric", "none"}, "subject.symmetry is invalid", errors)
        uncertainties = subject.get("uncertainties")
        require(isinstance(uncertainties, list) and all(isinstance(item, str) and item for item in uncertainties), "subject.uncertainties must be a string array", errors)
        if strict:
            require(bool(uncertainties), "strict: record at least one uncertainty or 'none identified'", errors)

    quality = spec.get("quality_contract")
    target_min = target_max = None
    if not isinstance(quality, dict):
        errors.append("quality_contract must be an object")
    else:
        require(quality.get("complexity") in {"simple", "moderate", "complex"}, "quality_contract.complexity is invalid", errors)
        target = quality.get("target_cuboids")
        if (
            isinstance(target, list)
            and len(target) == 2
            and all(isinstance(item, int) and not isinstance(item, bool) for item in target)
            and 1 <= target[0] <= target[1] <= MAX_CUBOIDS
        ):
            target_min, target_max = target
        else:
            errors.append(
                f"quality_contract.target_cuboids must be [min, max] within 1..{MAX_CUBOIDS}"
            )
        for key in ("identity_features", "required_views", "review_targets"):
            value = quality.get(key)
            require(isinstance(value, list) and all(isinstance(item, str) and item for item in value), f"quality_contract.{key} must be a string array", errors)
            if strict:
                require(bool(value), f"strict: quality_contract.{key} cannot be empty", errors)

    texture = spec.get("texture")
    if not isinstance(texture, dict):
        errors.append("texture must be an object")
    else:
        require(texture.get("density") in {1, 2, 4}, "texture.density must be 1, 2, or 4", errors)
        require(isinstance(texture.get("palette_size"), int) and 4 <= texture["palette_size"] <= 64, "texture.palette_size must be 4..64", errors)
        require(isinstance(texture.get("gutter"), int) and 1 <= texture["gutter"] <= 4, "texture.gutter must be 1..4", errors)
        require(
            texture.get("atlas_size")
            in {16, 32, 64, 128, 256, 512, 1024, 2048},
            "texture.atlas_size must be a power of two from 16..2048",
            errors,
        )
        require(
            "quantize_source" not in texture
            or isinstance(texture["quantize_source"], bool),
            "texture.quantize_source must be boolean",
            errors,
        )

    geometry = spec.get("geometry")
    if geometry is not None:
        if not isinstance(geometry, dict):
            errors.append("geometry must be an object")
        else:
            precision = geometry.get("precision")
            require(
                isinstance(precision, int)
                and not isinstance(precision, bool)
                and 1 <= precision <= 256,
                "geometry.precision must be an integer within 1..256",
                errors,
            )

    materials = spec.get("materials")
    material_names: set[str] = set()
    if not isinstance(materials, dict) or not materials:
        errors.append("materials must be a non-empty object")
    else:
        material_names = set(materials)
        for name, material in materials.items():
            label = f"materials.{name}"
            require(isinstance(name, str) and bool(ID_RE.fullmatch(name)), f"{label} name is invalid", errors)
            if not isinstance(material, dict):
                errors.append(f"{label} must be an object")
                continue
            for color_key in ("base", "shade", "highlight"):
                color = material.get(color_key)
                require(isinstance(color, str) and bool(HEX_RE.fullmatch(color)), f"{label}.{color_key} must be #RRGGBB", errors)
            require(material.get("pattern") in PATTERNS, f"{label}.pattern is invalid", errors)
            require(isinstance(material.get("pattern_scale"), int) and 1 <= material["pattern_scale"] <= 16, f"{label}.pattern_scale must be 1..16", errors)
            source_texture = material.get("source_texture")
            if source_texture is not None:
                if not isinstance(source_texture, dict):
                    errors.append(f"{label}.source_texture must be an object")
                else:
                    data_uri = source_texture.get("data_uri")
                    require(
                        isinstance(data_uri, str)
                        and data_uri.startswith("data:image/png;base64,"),
                        f"{label}.source_texture.data_uri must be an embedded PNG",
                        errors,
                    )
                    valid_vector(
                        source_texture.get("repeat"),
                        2,
                        f"{label}.source_texture.repeat",
                        errors,
                        positive=True,
                    )
                    valid_vector(
                        source_texture.get("offset"),
                        2,
                        f"{label}.source_texture.offset",
                        errors,
                    )
                    valid_vector(
                        source_texture.get("center"),
                        2,
                        f"{label}.source_texture.center",
                        errors,
                    )
                    require(
                        finite_number(source_texture.get("rotation")),
                        f"{label}.source_texture.rotation must be finite",
                        errors,
                    )
                    wrap = source_texture.get("wrap")
                    require(
                        isinstance(wrap, list)
                        and len(wrap) == 2
                        and all(value in {1000, 1001, 1002} for value in wrap),
                        f"{label}.source_texture.wrap is invalid",
                        errors,
                    )
                    require(
                        isinstance(source_texture.get("flip_y"), bool),
                        f"{label}.source_texture.flip_y must be boolean",
                        errors,
                    )

    bones = spec.get("bones")
    bone_names: set[str] = set()
    parent_by_bone: dict[str, str | None] = {}
    if not isinstance(bones, list) or not bones:
        errors.append("bones must be a non-empty array")
    else:
        for index, bone in enumerate(bones):
            label = f"bones[{index}]"
            if not isinstance(bone, dict):
                errors.append(f"{label} must be an object")
                continue
            name = bone.get("name")
            require(isinstance(name, str) and bool(ID_RE.fullmatch(name)), f"{label}.name is invalid", errors)
            if isinstance(name, str):
                require(name not in bone_names, f"duplicate bone name: {name}", errors)
                bone_names.add(name)
                parent_by_bone[name] = bone.get("parent")
            require(bone.get("parent") is None or isinstance(bone.get("parent"), str), f"{label}.parent must be a bone name or null", errors)
            valid_vector(bone.get("pivot"), 3, f"{label}.pivot", errors)
        roots = [name for name, parent in parent_by_bone.items() if parent is None]
        require(len(roots) == 1, "bones must contain exactly one root", errors)
        for name, parent in parent_by_bone.items():
            require(parent is None or parent in bone_names, f"bone {name} references missing parent {parent}", errors)
        for name in bone_names:
            seen: set[str] = set()
            current: str | None = name
            while current is not None and current in parent_by_bone:
                if current in seen:
                    errors.append(f"bone cycle detected at {current}")
                    break
                seen.add(current)
                current = parent_by_bone[current]

    cubes = spec.get("cubes")
    cube_names: set[str] = set()
    if not isinstance(cubes, list) or not 1 <= len(cubes) <= MAX_CUBOIDS:
        errors.append(f"cubes must contain 1..{MAX_CUBOIDS} cuboids")
        cubes = [] if not isinstance(cubes, list) else cubes
    for index, cube in enumerate(cubes):
        label = f"cubes[{index}]"
        if not isinstance(cube, dict):
            errors.append(f"{label} must be an object")
            continue
        name = cube.get("name")
        require(isinstance(name, str) and bool(ID_RE.fullmatch(name)), f"{label}.name is invalid", errors)
        if isinstance(name, str):
            require(name not in cube_names, f"duplicate cube name: {name}", errors)
            cube_names.add(name)
        require(cube.get("bone") in bone_names, f"{label}.bone references a missing bone", errors)
        valid_vector(cube.get("center"), 3, f"{label}.center", errors)
        valid_vector(cube.get("size"), 3, f"{label}.size", errors, positive=True)
        valid_vector(cube.get("rotation"), 3, f"{label}.rotation", errors)
        valid_vector(cube.get("origin"), 3, f"{label}.origin", errors)
        require(isinstance(cube.get("role"), str) and bool(cube["role"]), f"{label}.role is required", errors)
        require(cube.get("material") in material_names, f"{label}.material references a missing material", errors)
        overrides = cube.get("faces", {})
        if not isinstance(overrides, dict):
            errors.append(f"{label}.faces must be an object")
        else:
            for face, override in overrides.items():
                require(face in FACES, f"{label}.faces contains invalid face {face}", errors)
                if not isinstance(override, dict):
                    errors.append(f"{label}.faces.{face} must be an object")
                    continue
                require(override.get("material", cube.get("material")) in material_names, f"{label}.faces.{face}.material is missing", errors)
                for flip in ("flip_x", "flip_y"):
                    require(flip not in override or isinstance(override[flip], bool), f"{label}.faces.{face}.{flip} must be boolean", errors)
                source_texture = override.get("source_texture")
                if source_texture is not None:
                    if not isinstance(source_texture, dict):
                        errors.append(
                            f"{label}.faces.{face}.source_texture must be an object"
                        )
                    else:
                        data_uri = source_texture.get("data_uri")
                        require(
                            isinstance(data_uri, str)
                            and data_uri.startswith("data:image/png;base64,"),
                            f"{label}.faces.{face}.source_texture.data_uri must be an embedded PNG",
                            errors,
                        )
                        valid_vector(
                            source_texture.get("repeat"),
                            2,
                            f"{label}.faces.{face}.source_texture.repeat",
                            errors,
                            positive=True,
                        )
                        valid_vector(
                            source_texture.get("offset"),
                            2,
                            f"{label}.faces.{face}.source_texture.offset",
                            errors,
                        )
                        valid_vector(
                            source_texture.get("center"),
                            2,
                            f"{label}.faces.{face}.source_texture.center",
                            errors,
                        )
                        require(
                            finite_number(source_texture.get("rotation")),
                            f"{label}.faces.{face}.source_texture.rotation must be finite",
                            errors,
                        )
                        wrap = source_texture.get("wrap")
                        require(
                            isinstance(wrap, list)
                            and len(wrap) == 2
                            and all(
                                value in {1000, 1001, 1002}
                                for value in wrap
                            ),
                            f"{label}.faces.{face}.source_texture.wrap is invalid",
                            errors,
                        )
                        require(
                            isinstance(source_texture.get("flip_y"), bool),
                            f"{label}.faces.{face}.source_texture.flip_y must be boolean",
                            errors,
                        )
                source_region = override.get("source_region")
                if source_region is not None:
                    if valid_vector(
                        source_region,
                        4,
                        f"{label}.faces.{face}.source_region",
                        errors,
                    ):
                        require(
                            all(0 <= float(value) <= 1 for value in source_region),
                            f"{label}.faces.{face}.source_region must be within 0..1",
                            errors,
                        )
                        require(
                            float(source_region[0]) < float(source_region[2])
                            and float(source_region[1]) < float(source_region[3]),
                            f"{label}.faces.{face}.source_region must be [left, top, right, bottom]",
                            errors,
                        )
                    effective_material = materials.get(
                        override.get("material", cube.get("material")), {}
                    )
                    require(
                        isinstance(source_texture, dict)
                        or (
                            isinstance(effective_material, dict)
                            and isinstance(
                                effective_material.get("source_texture"), dict
                            )
                        ),
                        f"{label}.faces.{face}.source_region requires an effective source_texture",
                        errors,
                    )

    landmarks = spec.get("landmarks")
    if not isinstance(landmarks, list):
        errors.append("landmarks must be an array")
        landmarks = []
    landmark_names: set[str] = set()
    for index, landmark in enumerate(landmarks):
        label = f"landmarks[{index}]"
        if not isinstance(landmark, dict):
            errors.append(f"{label} must be an object")
            continue
        name = landmark.get("name")
        require(isinstance(name, str) and bool(ID_RE.fullmatch(name)), f"{label}.name is invalid", errors)
        if isinstance(name, str):
            require(name not in landmark_names, f"duplicate landmark name: {name}", errors)
            landmark_names.add(name)
        require(landmark.get("cube") in cube_names, f"{label}.cube references a missing cube", errors)
        require(landmark.get("face") in FACES, f"{label}.face is invalid", errors)
        if valid_vector(landmark.get("center_uv"), 2, f"{label}.center_uv", errors):
            require(all(0 <= float(item) <= 1 for item in landmark["center_uv"]), f"{label}.center_uv must be within 0..1", errors)
        if valid_vector(landmark.get("size"), 2, f"{label}.size", errors, positive=True):
            require(all(float(item).is_integer() for item in landmark["size"]), f"{label}.size values must be integers", errors)
        for color_key in ("color", "center_color"):
            color = landmark.get(color_key)
            require(isinstance(color, str) and bool(HEX_RE.fullmatch(color)), f"{label}.{color_key} must be #RRGGBB", errors)

    collision = spec.get("collision")
    if not isinstance(collision, dict):
        errors.append("collision must be an object")
    else:
        for key in ("width", "height", "eye_height"):
            value = collision.get(key)
            require(finite_number(value) and float(value) > 0, f"collision.{key} must be positive", errors)
        if finite_number(collision.get("height")) and finite_number(collision.get("eye_height")):
            require(float(collision["eye_height"]) <= float(collision["height"]), "collision.eye_height cannot exceed height", errors)

    errors.extend(validate_wearable(spec))

    if strict and target_min is not None and target_max is not None:
        require(target_min <= len(cubes) <= target_max, f"strict: cuboid count {len(cubes)} is outside target {target_min}..{target_max}", errors)
    return errors


def validated_spec(path: Path, *, strict: bool) -> dict[str, Any]:
    spec = read_json(path)
    errors = validate_spec(spec, strict=strict)
    if strict and not errors:
        reference_path = resolve_reference_path(path, spec)
        if not reference_path.is_file():
            errors.append(f"strict: reference image not found: {reference_path}")
        else:
            probe = image_probe(reference_path)
            reference = spec["reference"]
            if probe["sha256"] != reference["sha256"]:
                errors.append("strict: reference image SHA-256 does not match the specification")
            if [probe["width"], probe["height"]] != [reference["width"], reference["height"]]:
                errors.append("strict: reference image dimensions do not match the specification")
    if errors:
        raise ModelSpecError("\n".join(f"- {error}" for error in errors))
    return spec


def resolve_reference_path(spec_path: Path, spec: dict[str, Any]) -> Path:
    reference_path = Path(spec["reference"]["image"])
    if reference_path.is_absolute():
        return reference_path
    return (spec_path.parent / reference_path).resolve()


def image_probe(image_path: Path) -> dict[str, Any]:
    try:
        with Image.open(image_path) as source:
            image = source.convert("RGBA")
            width, height = image.size
            has_alpha = image.getextrema()[3][0] < 255
            thumbnail = image.convert("RGB")
            thumbnail.thumbnail((128, 128), Image.Resampling.LANCZOS)
            palette = thumbnail.quantize(
                colors=8,
                method=Image.Quantize.MAXCOVERAGE,
                dither=Image.Dither.NONE,
            ).convert("RGB")
            palette_data = (
                palette.get_flattened_data()
                if hasattr(palette, "get_flattened_data")
                else palette.getdata()
            )
            common = Counter(palette_data).most_common(8)
    except (FileNotFoundError, OSError) as exc:
        raise ModelSpecError(f"cannot read image {image_path}: {exc}") from exc
    return {
        "path": str(image_path.resolve()),
        "sha256": sha256_file(image_path),
        "width": width,
        "height": height,
        "mode": image.mode,
        "has_alpha": has_alpha,
        "aspect_ratio": round(width / height, 6),
        "dominant_colors": [
            {"hex": "#{:02x}{:02x}{:02x}".format(*rgb), "pixels": count}
            for rgb, count in common
        ],
    }


def starter_spec(image_path: Path, output_path: Path, model_id: str, description: str, complexity: str) -> dict[str, Any]:
    probe = image_probe(image_path)
    dominant = [item["hex"] for item in probe["dominant_colors"]]
    base = dominant[0] if dominant else "#a06b45"
    shade = dominant[1] if len(dominant) > 1 else "#60402a"
    highlight = dominant[2] if len(dominant) > 2 else "#d6a274"
    target = {"simple": [6, 15], "moderate": [15, 35], "complex": [25, 60]}[complexity]
    try:
        reference_image = Path(
            os.path.relpath(image_path.resolve(), output_path.parent.resolve())
        ).as_posix()
    except ValueError:
        reference_image = image_path.resolve().as_posix()
    return {
        "schema_version": SCHEMA_VERSION,
        "id": model_id,
        "reference": {
            "image": reference_image,
            "sha256": probe["sha256"],
            "width": probe["width"],
            "height": probe["height"],
        },
        "subject": {
            "type": "mob",
            "description": description,
            "symmetry": "bilateral",
            "uncertainties": ["Agent must inspect hidden-side geometry"],
        },
        "quality_contract": {
            "complexity": complexity,
            "target_cuboids": target,
            "identity_features": [],
            "required_views": [
                "front",
                "back",
                "left",
                "right",
                "top",
                "bottom",
                "isometric",
            ],
            "review_targets": ["silhouette", "face", "joints", "texture"],
        },
        "texture": {
            "density": 2,
            "palette_size": 24,
            "gutter": 2,
            "atlas_size": 128,
        },
        "materials": {
            "primary": {
                "base": base,
                "shade": shade,
                "highlight": highlight,
                "pattern": "solid",
                "pattern_scale": 1,
            }
        },
        "bones": [
            {"name": "root", "parent": None, "pivot": [0, 0, 0]},
            {"name": "body", "parent": "root", "pivot": [0, 7, 0]},
            {"name": "head", "parent": "body", "pivot": [0, 10, 3]},
        ],
        "cubes": [
            {
                "name": "body",
                "bone": "body",
                "center": [0, 7, 0],
                "size": [6, 6, 10],
                "rotation": [0, 0, 0],
                "origin": [0, 7, 0],
                "role": "body",
                "material": "primary",
                "faces": {},
            },
            {
                "name": "head",
                "bone": "head",
                "center": [0, 11, 4],
                "size": [6, 6, 6],
                "rotation": [0, 0, 0],
                "origin": [0, 10, 3],
                "role": "head",
                "material": "primary",
                "faces": {},
            },
            {
                "name": "snout",
                "bone": "head",
                "center": [0, 10, 8],
                "size": [3, 2.5, 3],
                "rotation": [0, 0, 0],
                "origin": [0, 10, 3],
                "role": "snout",
                "material": "primary",
                "faces": {},
            },
        ],
        "landmarks": [],
        "collision": {"width": 0.8, "height": 1.2, "eye_height": 1.0},
    }


def safe_id(value: str, fallback: str) -> str:
    result = re.sub(r"[^a-z0-9_-]+", "_", value.strip().lower()).strip("_-")
    if not result or not result[0].isalnum():
        result = fallback
    return result[:64]


def adjusted_hex(color: str, factor: float) -> str:
    red, green, blue = hex_rgb(color)
    channels = [max(0, min(255, round(channel * factor))) for channel in (red, green, blue)]
    return "#{:02x}{:02x}{:02x}".format(*channels)


def three_matrix_components(
    matrix: Any,
    label: str,
) -> tuple[list[float], list[float], list[float]]:
    if not (
        isinstance(matrix, list)
        and len(matrix) == 16
        and all(finite_number(value) for value in matrix)
    ):
        raise ModelSpecError(f"{label}.matrix must contain 16 finite numbers")
    values = [float(value) for value in matrix]
    scales = [
        math.sqrt(sum(values[index + offset] ** 2 for offset in range(3)))
        for index in (0, 4, 8)
    ]
    if any(scale <= 1e-8 for scale in scales):
        raise ModelSpecError(f"{label} uses a zero matrix scale")

    m11, m12, m13 = (
        values[0] / scales[0],
        values[4] / scales[1],
        values[8] / scales[2],
    )
    m21, m22, m23 = (
        values[1] / scales[0],
        values[5] / scales[1],
        values[9] / scales[2],
    )
    m31, m32, m33 = (
        values[2] / scales[0],
        values[6] / scales[1],
        values[10] / scales[2],
    )
    y = math.asin(-max(-1.0, min(1.0, m31)))
    if abs(m31) < 0.9999999:
        x = math.atan2(m32, m33)
        z = math.atan2(m21, m11)
    else:
        x = 0.0
        z = math.atan2(-m12, m22)
    rotation = [math.degrees(value) for value in (x, y, z)]
    translation = [values[12], values[13], values[14]]
    return translation, rotation, scales


def make_material_name(name: str, index: int, used: set[str]) -> str:
    candidate = safe_id(name, f"material_{index + 1}")
    base = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{base[:60]}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def import_threejs_scene(
    scene_path: Path,
    reference_path: Path,
    output_path: Path,
    model_id: str,
    description: str,
) -> dict[str, Any]:
    """Convert a constrained Object3D.toJSON scene into a native model spec."""
    scene = read_json(scene_path)
    if not isinstance(scene, dict) or not isinstance(scene.get("object"), dict):
        raise ModelSpecError("Three.js scene must be Object3D.toJSON output")
    geometries = {
        item["uuid"]: item
        for item in scene.get("geometries", [])
        if isinstance(item, dict) and isinstance(item.get("uuid"), str)
    }
    source_materials = [
        item
        for item in scene.get("materials", [])
        if isinstance(item, dict) and isinstance(item.get("uuid"), str)
    ]
    source_textures = {
        item["uuid"]: item
        for item in scene.get("textures", [])
        if isinstance(item, dict) and isinstance(item.get("uuid"), str)
    }
    source_images = {
        item["uuid"]: item
        for item in scene.get("images", [])
        if isinstance(item, dict) and isinstance(item.get("uuid"), str)
    }
    material_names: dict[str, str] = {}
    materials: dict[str, Any] = {}
    used_material_names: set[str] = set()
    for index, material in enumerate(source_materials):
        if material.get("type") not in {
            "MeshBasicMaterial",
            "MeshLambertMaterial",
            "MeshPhongMaterial",
            "MeshStandardMaterial",
            "MeshPhysicalMaterial",
        }:
            raise ModelSpecError(
                f"unsupported Three.js material type: {material.get('type')}"
            )
        sculpt_material = (
            material.get("userData", {}).get("sculptMaterial", {})
            if isinstance(material.get("userData"), dict)
            else {}
        )
        sculpt_color = (
            sculpt_material.get("baseColor", sculpt_material.get("color"))
            if isinstance(sculpt_material, dict)
            else None
        )
        if isinstance(sculpt_color, str) and re.fullmatch(
            r"#[0-9A-Fa-f]{6}", sculpt_color
        ):
            base = sculpt_color.lower()
        else:
            color_number = material.get("color", 0xA06B45)
            if not isinstance(color_number, int) or isinstance(color_number, bool):
                raise ModelSpecError("Three.js material color must be an integer")
            base = f"#{color_number & 0xFFFFFF:06x}"
        name = make_material_name(material.get("name", ""), index, used_material_names)
        material_names[material["uuid"]] = name
        imported_material = {
            "base": base,
            "shade": adjusted_hex(base, 0.62),
            "highlight": adjusted_hex(base, 1.28),
            "pattern": "solid",
            "pattern_scale": 1,
        }
        if isinstance(sculpt_material, dict):
            source_material_id = sculpt_material.get("id")
            if isinstance(source_material_id, str) and source_material_id:
                imported_material["source_material_id"] = source_material_id
                if "strip" in source_material_id.lower():
                    imported_material["pattern"] = "stripes"
            color_variation = sculpt_material.get("colorVariation")
            source_palette = (
                color_variation.get("palette")
                if isinstance(color_variation, dict)
                else None
            )
            if isinstance(source_palette, list):
                reference_palette = [
                    color.lower()
                    for color in source_palette
                    if isinstance(color, str)
                    and re.fullmatch(r"#[0-9A-Fa-f]{6}", color)
                ]
                if reference_palette:
                    imported_material["reference_palette"] = reference_palette
        texture_uuid = material.get("map")
        texture = source_textures.get(texture_uuid)
        if texture is not None:
            image = source_images.get(texture.get("image"))
            data_uri = image.get("url") if isinstance(image, dict) else None
            if not isinstance(data_uri, str) or not data_uri.startswith(
                "data:image/png;base64,"
            ):
                raise ModelSpecError(
                    f"Three.js material {name} map must reference an embedded PNG"
                )
            imported_material["source_texture"] = {
                "data_uri": data_uri,
                "repeat": texture.get("repeat", [1, 1]),
                "offset": texture.get("offset", [0, 0]),
                "center": texture.get("center", [0, 0]),
                "rotation": texture.get("rotation", 0),
                "wrap": texture.get("wrap", [1001, 1001]),
                "flip_y": texture.get("flipY", True),
            }
        materials[name] = imported_material
    if not materials:
        raise ModelSpecError("Three.js scene contains no supported materials")

    cubes: list[dict[str, Any]] = []
    bone_records: dict[str, dict[str, Any]] = {}
    used_cube_names: set[str] = set()

    def unique_cube_name(value: str, fallback: str) -> str:
        candidate = safe_id(value, fallback)
        base = candidate
        suffix = 2
        while candidate in used_cube_names:
            candidate = f"{base[:60]}_{suffix}"
            suffix += 1
        used_cube_names.add(candidate)
        return candidate

    def visit(node: dict[str, Any], parent_pivot: dict[str, Any] | None = None) -> None:
        node_type = node.get("type")
        user_data = node.get("userData")
        blockbench = (
            user_data.get("img2blockbench", {})
            if isinstance(user_data, dict)
            else {}
        )
        if not isinstance(blockbench, dict):
            blockbench = {}
        if blockbench.get("exclude") is True:
            return

        pivot = parent_pivot
        if node_type in {"Group", "Object3D", "Bone"} and node is not scene["object"]:
            if parent_pivot is not None:
                raise ModelSpecError(
                    "nested Three.js pivot transforms are unsupported; flatten pivots under the root"
                )
            origin, rotation, pivot_scale = three_matrix_components(
                node.get("matrix"), f"object {node.get('name', '<unnamed>')}"
            )
            bone_name = safe_id(
                str(blockbench.get("bone") or node.get("name", "")).removesuffix(
                    "_pivot"
                ),
                f"bone_{len(bone_records) + 1}",
            )
            parent_name = safe_id(
                str(blockbench.get("parent", "root")), "root"
            )
            if parent_name == bone_name:
                parent_name = "root"
            pivot = {
                "origin": origin,
                "rotation": rotation,
                "scale": pivot_scale,
                "bone": bone_name,
                "parent": parent_name,
                "role": str(blockbench.get("role") or node.get("name") or bone_name),
            }
            bone_records.setdefault(
                bone_name,
                {"name": bone_name, "parent": parent_name, "pivot": origin},
            )

        if node_type == "Mesh":
            if pivot is None:
                raise ModelSpecError("every Three.js Mesh must be inside a pivot Group")
            geometry = geometries.get(node.get("geometry"))
            if not geometry or geometry.get("type") != "BoxGeometry":
                raise ModelSpecError(
                    f"mesh {node.get('name', '<unnamed>')} must use BoxGeometry"
                )
            geometry_size = [
                float(geometry.get("width", 1)),
                float(geometry.get("height", 1)),
                float(geometry.get("depth", 1)),
            ]
            if any(value <= 0 for value in geometry_size):
                raise ModelSpecError("BoxGeometry dimensions must be positive")
            local, local_rotation, local_scale = three_matrix_components(
                node.get("matrix"), f"mesh {node.get('name', '<unnamed>')}"
            )
            if any(abs(value) > 1e-5 for value in local_rotation):
                raise ModelSpecError(
                    f"mesh {node.get('name', '<unnamed>')} rotates outside its pivot"
                )
            size = [
                geometry_size[axis] * pivot["scale"][axis] * local_scale[axis]
                for axis in range(3)
            ]
            material_ids = node.get("material")
            if isinstance(material_ids, str):
                material_ids = [material_ids] * 6
            if not isinstance(material_ids, list) or not material_ids:
                raise ModelSpecError("Three.js Mesh must reference material UUIDs")
            if len(material_ids) == 1:
                material_ids *= 6
            if len(material_ids) != 6:
                raise ModelSpecError(
                    "BoxGeometry material arrays must follow east, west, up, down, south, north"
                )
            try:
                face_materials = [material_names[uuid_value] for uuid_value in material_ids]
            except KeyError as exc:
                raise ModelSpecError(
                    f"mesh references missing material UUID: {exc.args[0]}"
                ) from exc
            primary = Counter(face_materials).most_common(1)[0][0]
            # Three BoxGeometry order: east, west, up, down, south, north.
            faces = {
                face: {"material": material}
                for face, material in zip(
                    ("east", "west", "up", "down", "south", "north"),
                    face_materials,
                )
                if material != primary
            }
            cube_name = unique_cube_name(
                str(node.get("name", "")), f"cube_{len(cubes) + 1}"
            )
            cube_metadata = blockbench
            cubes.append(
                {
                    "name": cube_name,
                    "bone": pivot["bone"],
                    "center": [
                        normalize_number(pivot["origin"][axis] + local[axis])
                        for axis in range(3)
                    ],
                    "size": [normalize_number(value) for value in size],
                    "rotation": [
                        normalize_number(value) for value in pivot["rotation"]
                    ],
                    "origin": [
                        normalize_number(value) for value in pivot["origin"]
                    ],
                    "role": str(cube_metadata.get("role") or pivot["role"]),
                    "material": primary,
                    "faces": faces,
                }
            )

        children = node.get("children", [])
        if not isinstance(children, list):
            raise ModelSpecError("Three.js object children must be an array")
        for child in children:
            if not isinstance(child, dict):
                raise ModelSpecError("Three.js child must be an object")
            visit(child, pivot)

    root_object = scene["object"]
    for child in root_object.get("children", []):
        visit(child)
    if not cubes:
        raise ModelSpecError("Three.js scene contains no importable BoxGeometry meshes")
    if len(cubes) > MAX_CUBOIDS:
        raise ModelSpecError(
            f"Three.js scene exceeds the {MAX_CUBOIDS}-cuboid limit"
        )

    existing_bones = set(bone_records)
    for bone in bone_records.values():
        if bone["parent"] not in existing_bones and bone["parent"] != "root":
            bone["parent"] = "root"
    bones = [{"name": "root", "parent": None, "pivot": [0, 0, 0]}]
    bones.extend(bone_records.values())

    spec = starter_spec(
        reference_path, output_path, model_id, description, "moderate"
    )
    spec["subject"]["uncertainties"] = [
        "Hidden surfaces are inferred from the single reference image",
        "Procedural Three.js geometry is limited to Minecraft-compatible boxes",
    ]
    spec["quality_contract"]["identity_features"] = [description]
    spec["quality_contract"]["target_cuboids"] = [
        max(1, len(cubes) - 6),
        min(MAX_CUBOIDS, len(cubes) + 8),
    ]
    spec["materials"] = materials
    spec["bones"] = bones
    spec["cubes"] = cubes
    spec["generation"] = {
        "lane": "threejs",
        "intermediate": "Object3D.toJSON",
    }
    root_user_data = root_object.get("userData", {})
    root_metadata = (
        root_user_data.get("img2blockbench", {})
        if isinstance(root_user_data, dict)
        else {}
    )
    landmarks = root_metadata.get("landmarks", [])
    spec["landmarks"] = landmarks if isinstance(landmarks, list) else []

    lower = [
        min(float(cube["center"][axis]) - float(cube["size"][axis]) / 2 for cube in cubes)
        for axis in range(3)
    ]
    upper = [
        max(float(cube["center"][axis]) + float(cube["size"][axis]) / 2 for cube in cubes)
        for axis in range(3)
    ]
    width = (upper[0] - lower[0]) / 16
    height = (upper[1] - min(0.0, lower[1])) / 16
    spec["collision"] = {
        "width": round(max(0.25, width), 3),
        "height": round(max(0.25, height), 3),
        "eye_height": round(max(0.2, height * 0.78), 3),
    }
    errors = validate_spec(spec, strict=True)
    if errors:
        raise ModelSpecError(
            "imported Three.js scene is invalid:\n"
            + "\n".join(f"- {error}" for error in errors)
        )
    return spec


def hex_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def snap(value: float, density: int) -> float:
    return round(float(value) * density) / density


def geometry_precision(spec: dict[str, Any]) -> int:
    """Return geometry subdivisions independently from texture texel density."""
    geometry = spec.get("geometry")
    if isinstance(geometry, dict) and isinstance(geometry.get("precision"), int):
        return geometry["precision"]
    return spec["texture"]["density"]


def exported_cube_bounds(
    spec: dict[str, Any],
    cube: dict[str, Any],
) -> tuple[list[float], list[float]]:
    """Resolve compiler bounds while preserving legacy density snapping."""
    geometry = spec.get("geometry")
    if not isinstance(geometry, dict):
        density = spec["texture"]["density"]
        center = [snap(item, density) for item in cube["center"]]
        size = [snap(item, density) for item in cube["size"]]
        return (
            [center[index] - size[index] / 2 for index in range(3)],
            [center[index] + size[index] / 2 for index in range(3)],
        )

    precision = geometry_precision(spec)
    minimum = []
    maximum = []
    for center, size in zip(cube["center"], cube["size"]):
        lower = snap(float(center) - float(size) / 2, precision)
        upper = snap(float(center) + float(size) / 2, precision)
        if upper <= lower:
            upper = lower + 1 / precision
        minimum.append(lower)
        maximum.append(upper)
    return minimum, maximum


def face_dimensions(
    spec: dict[str, Any],
    cube: dict[str, Any],
    face: str,
) -> tuple[int, int]:
    _, u_axis, v_axis, _ = FACE_AXES[face]
    density = spec["texture"]["density"]
    if isinstance(spec.get("geometry"), dict):
        minimum, maximum = exported_cube_bounds(spec, cube)
        size = [maximum[index] - minimum[index] for index in range(3)]
    else:
        size = [snap(item, density) for item in cube["size"]]
    return (
        max(1, math.ceil(float(size[u_axis]) * density)),
        max(1, math.ceil(float(size[v_axis]) * density)),
    )


def pack_faces(spec: dict[str, Any]) -> tuple[int, dict[tuple[str, str], tuple[int, int, int, int]]]:
    texture = spec["texture"]
    gutter = texture["gutter"]
    entries: list[tuple[str, str, int, int]] = []
    for cube in spec["cubes"]:
        for face in FACES:
            width, height = face_dimensions(spec, cube, face)
            entries.append((cube["name"], face, width, height))
    entries.sort(
        key=lambda entry: (
            -entry[3],
            -entry[2],
            entry[0],
            FACES.index(entry[1]),
        )
    )

    size = texture["atlas_size"]
    while size <= 2048:
        placements: dict[tuple[str, str], tuple[int, int, int, int]] = {}
        x = gutter
        y = gutter
        row_height = 0
        fits = True
        for cube_name, face, width, height in entries:
            outer_width = width + gutter * 2
            outer_height = height + gutter * 2
            if x + outer_width > size:
                x = gutter
                y += row_height
                row_height = 0
            if y + outer_height > size:
                fits = False
                break
            placements[(cube_name, face)] = (x + gutter, y + gutter, width, height)
            x += outer_width
            row_height = max(row_height, outer_height)
        if fits:
            return size, placements
        size *= 2
    raise ModelSpecError("texture faces do not fit in a 2048x2048 atlas")


def material_for_face(spec: dict[str, Any], cube: dict[str, Any], face: str) -> dict[str, Any]:
    override = cube.get("faces", {}).get(face, {})
    return spec["materials"][override.get("material", cube["material"])]


def decode_source_texture(material: dict[str, Any]) -> Image.Image | None:
    source_texture = material.get("source_texture")
    if not isinstance(source_texture, dict):
        return None
    data_uri = source_texture.get("data_uri")
    prefix = "data:image/png;base64,"
    if not isinstance(data_uri, str) or not data_uri.startswith(prefix):
        raise ModelSpecError("source texture must be an embedded PNG")
    try:
        raw = base64.b64decode(data_uri[len(prefix) :], validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            return image.convert("RGBA")
    except (ValueError, OSError) as exc:
        raise ModelSpecError(f"source texture is not a valid PNG: {exc}") from exc


def wrap_texture_coordinate(value: float, mode: int) -> float:
    if mode == 1000:
        return value - math.floor(value)
    if mode == 1002:
        whole = math.floor(value)
        fraction = value - whole
        return fraction if whole % 2 == 0 else 1.0 - fraction
    return min(1.0, max(0.0, value))


def source_texture_pixel(
    material: dict[str, Any],
    image: Image.Image,
    x: int,
    y: int,
    width: int,
    height: int,
    source_region: list[float] | None = None,
) -> tuple[int, int, int, int]:
    if source_region is not None:
        left, top, right, bottom = (float(value) for value in source_region)
        u = (x + 0.5) / width
        v = (y + 0.5) / height
        source_x = min(
            image.width - 1,
            max(0, int((left + u * (right - left)) * image.width)),
        )
        source_y = min(
            image.height - 1,
            max(0, int((top + v * (bottom - top)) * image.height)),
        )
        return image.getpixel((source_x, source_y))

    source = material["source_texture"]
    repeat_x, repeat_y = (float(value) for value in source["repeat"])
    offset_x, offset_y = (float(value) for value in source["offset"])
    center_x, center_y = (float(value) for value in source["center"])
    rotation = float(source["rotation"])

    u = (x + 0.5) / width
    v = 1.0 - (y + 0.5) / height
    centered_u = u - center_x
    centered_v = v - center_y
    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    transformed_u = (
        repeat_x * (cosine * centered_u + sine * centered_v)
        + center_x
        + offset_x
    )
    transformed_v = (
        repeat_y * (-sine * centered_u + cosine * centered_v)
        + center_y
        + offset_y
    )
    transformed_u = wrap_texture_coordinate(transformed_u, source["wrap"][0])
    transformed_v = wrap_texture_coordinate(transformed_v, source["wrap"][1])

    source_x = min(image.width - 1, int(transformed_u * image.width))
    image_v = 1.0 - transformed_v if source["flip_y"] else transformed_v
    source_y = min(image.height - 1, int(image_v * image.height))
    return image.getpixel((source_x, source_y))


def pattern_pixel(
    material: dict[str, Any],
    x: int,
    y: int,
    width: int,
    height: int,
    seed: int,
) -> tuple[int, int, int, int]:
    base = hex_rgb(material["base"])
    shade = hex_rgb(material["shade"])
    highlight = hex_rgb(material["highlight"])
    scale = material["pattern_scale"]
    pattern = material["pattern"]
    value = ((x * 73_856_093) ^ (y * 19_349_663) ^ seed) & 0xFF
    if pattern == "solid":
        color = base
    elif pattern == "dither":
        threshold = max(3, 14 - scale)
        color = shade if value < threshold else highlight if value > 255 - threshold else base
    elif pattern == "stripes":
        color = shade if ((x + seed) // scale) % 4 == 0 else base
    elif pattern == "spots":
        color = shade if ((x // scale) * 11 + (y // scale) * 7 + seed) % 13 < 2 else base
    else:
        ratio = y / max(1, height - 1)
        target = highlight if ratio < 0.35 else shade if ratio > 0.72 else base
        color = tuple(round(base[index] * 0.65 + target[index] * 0.35) for index in range(3))
    return (*color, 255)


def landmark_rect(
    landmark: dict[str, Any],
    placement: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    px, py, width, height = placement
    mark_width = max(1, int(landmark["size"][0]))
    mark_height = max(1, int(landmark["size"][1]))
    center_x = px + round(float(landmark["center_uv"][0]) * max(0, width - 1))
    center_y = py + round(float(landmark["center_uv"][1]) * max(0, height - 1))
    left = max(px, center_x - mark_width // 2)
    top = max(py, center_y - mark_height // 2)
    right = min(px + width, left + mark_width)
    bottom = min(py + height, top + mark_height)
    return left, top, right, bottom


def apply_landmarks(
    atlas: Image.Image,
    spec: dict[str, Any],
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
) -> None:
    pixels = atlas.load()
    for landmark in spec["landmarks"]:
        rect = landmark_rect(landmark, placements[(landmark["cube"], landmark["face"])])
        color = (*hex_rgb(landmark["color"]), 255)
        center_color = (*hex_rgb(landmark["center_color"]), 255)
        for y in range(rect[1], rect[3]):
            for x in range(rect[0], rect[2]):
                pixels[x, y] = color
        center_x = (rect[0] + rect[2] - 1) // 2
        center_y = (rect[1] + rect[3] - 1) // 2
        pixels[center_x, center_y] = center_color


def build_texture(
    spec: dict[str, Any],
) -> tuple[Image.Image, dict[tuple[str, str], tuple[int, int, int, int]]]:
    atlas_size, placements = pack_faces(spec)
    atlas = Image.new("RGBA", (atlas_size, atlas_size), (0, 0, 0, 0))
    pixels = atlas.load()
    cube_by_name = {cube["name"]: cube for cube in spec["cubes"]}
    source_images = {
        name: decode_source_texture(material)
        for name, material in spec["materials"].items()
    }
    used_source_texture = False
    for (cube_name, face), (left, top, width, height) in placements.items():
        cube = cube_by_name[cube_name]
        material = material_for_face(spec, cube, face)
        face_override = cube.get("faces", {}).get(face, {})
        face_source = (
            face_override.get("source_texture")
            if isinstance(face_override, dict)
            else None
        )
        if isinstance(face_source, dict):
            material = {**material, "source_texture": face_source}
            source_image = decode_source_texture(material)
        else:
            source_image = source_images[
                face_override.get("material", cube["material"])
            ]
        seed = int(hashlib.sha256(f"{cube_name}/{face}/{cube['material']}".encode()).hexdigest()[:8], 16)
        for y in range(height):
            for x in range(width):
                if source_image is not None:
                    pixels[left + x, top + y] = source_texture_pixel(
                        material,
                        source_image,
                        x,
                        y,
                        width,
                        height,
                        face_override.get("source_region"),
                    )
                    used_source_texture = True
                else:
                    pixels[left + x, top + y] = pattern_pixel(
                        material, x, y, width, height, seed
                    )

    apply_landmarks(atlas, spec, placements)

    if used_source_texture and not spec["texture"].get("quantize_source", False):
        quantized = atlas
    else:
        alpha = atlas.getchannel("A")
        quantized = atlas.convert("RGB").quantize(
            colors=spec["texture"]["palette_size"],
            method=Image.Quantize.MAXCOVERAGE,
            dither=Image.Dither.NONE,
        ).convert("RGBA")
        quantized.putalpha(alpha)
        apply_landmarks(quantized, spec, placements)

    pixels = quantized.load()
    gutter = spec["texture"]["gutter"]
    for left, top, width, height in placements.values():
        for y in range(top - gutter, top + height + gutter):
            for x in range(left - gutter, left + width + gutter):
                source_x = min(max(x, left), left + width - 1)
                source_y = min(max(y, top), top + height - 1)
                pixels[x, y] = pixels[source_x, source_y]
    return quantized, placements


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def face_uv(
    cube: dict[str, Any],
    face: str,
    placement: tuple[int, int, int, int],
) -> list[int]:
    left, top, width, height = placement
    override = cube.get("faces", {}).get(face, {})
    flip_x = (face in {"east", "north"}) ^ bool(override.get("flip_x", False))
    flip_y = bool(override.get("flip_y", False))
    x1, x2 = (left + width, left) if flip_x else (left, left + width)
    y1, y2 = (top + height, top) if flip_y else (top, top + height)
    return [x1, y1, x2, y2]


def normalize_number(value: float) -> int | float:
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded


def make_bbmodel(
    spec: dict[str, Any],
    texture_bytes: bytes,
    atlas_size: int,
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
) -> dict[str, Any]:
    model_id = spec["id"]
    element_by_name: dict[str, dict[str, Any]] = {}
    for cube in spec["cubes"]:
        minimum, maximum = exported_cube_bounds(spec, cube)
        origin = [normalize_number(item) for item in cube["origin"]]
        element_uuid = stable_uuid(model_id, "cube", cube["name"])
        element_by_name[cube["name"]] = {
            "name": cube["name"],
            "box_uv": False,
            "rescale": False,
            "locked": False,
            "render_order": "default",
            "allow_mirror_modeling": True,
            "from": [normalize_number(value) for value in minimum],
            "to": [normalize_number(value) for value in maximum],
            "autouv": 0,
            "color": 0,
            "origin": origin,
            "rotation": [normalize_number(item) for item in cube["rotation"]],
            "faces": {
                face: {
                    "uv": face_uv(cube, face, placements[(cube["name"], face)]),
                    "texture": 0,
                }
                for face in FACES
            },
            "type": "cube",
            "uuid": element_uuid,
        }

    bones = spec["bones"]
    bone_by_name = {bone["name"]: bone for bone in bones}
    cube_names_by_bone: dict[str, list[str]] = {name: [] for name in bone_by_name}
    for cube in spec["cubes"]:
        cube_names_by_bone[cube["bone"]].append(cube["name"])

    def group_for(name: str) -> dict[str, Any]:
        bone = bone_by_name[name]
        child_groups = [
            group_for(child["name"])
            for child in bones
            if child.get("parent") == name
        ]
        element_uuids = [
            element_by_name[cube_name]["uuid"]
            for cube_name in cube_names_by_bone[name]
        ]
        return {
            "name": name,
            "origin": [normalize_number(item) for item in bone["pivot"]],
            "color": 0,
            "uuid": stable_uuid(model_id, "bone", name),
            "export": True,
            "isOpen": True,
            "locked": False,
            "visibility": True,
            "autouv": 0,
            "children": element_uuids + child_groups,
        }

    roots = [bone["name"] for bone in bones if bone.get("parent") is None]
    data_uri = "data:image/png;base64," + base64.b64encode(texture_bytes).decode("ascii")
    return {
        "meta": {
            "format_version": "5.0",
            "creation_time": 0,
            "model_format": "free",
            "box_uv": False,
        },
        "img2blockbench": {
            "front_axis": "positive_z",
            "texture_density": spec["texture"]["density"],
            **(
                {"geometry_precision": geometry_precision(spec)}
                if isinstance(spec.get("geometry"), dict)
                else {}
            ),
        },
        "name": model_id,
        "model_identifier": "",
        "visible_box": [1, 1, 0],
        "variable_placeholders": "",
        "variable_placeholder_buttons": [],
        "resolution": {"width": atlas_size, "height": atlas_size},
        "elements": [element_by_name[cube["name"]] for cube in spec["cubes"]],
        "outliner": [group_for(name) for name in roots],
        "textures": [
            {
                "path": f"{model_id}.png",
                "name": f"{model_id}.png",
                "folder": "",
                "namespace": "",
                "id": "0",
                "particle": False,
                "render_mode": "default",
                "render_sides": "auto",
                "frame_time": 1,
                "frame_order_type": "loop",
                "frame_order": "",
                "frame_interpolate": False,
                "visible": True,
                "internal": True,
                "saved": True,
                "uuid": stable_uuid(model_id, "texture"),
                "source": data_uri,
            }
        ],
    }


def make_bedrock_geometry(
    spec: dict[str, Any],
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
    atlas_size: int,
) -> dict[str, Any]:
    cubes_by_bone: dict[str, list[dict[str, Any]]] = {
        bone["name"]: [] for bone in spec["bones"]
    }
    for cube in spec["cubes"]:
        minimum, maximum = exported_cube_bounds(spec, cube)
        size = [maximum[index] - minimum[index] for index in range(3)]
        faces = {}
        for face in FACES:
            left, top, width, height = placements[(cube["name"], face)]
            faces[face] = {"uv": [left, top], "uv_size": [width, height]}
        cubes_by_bone[cube["bone"]].append(
            {
                "origin": [
                    normalize_number(value) for value in minimum
                ],
                "size": [normalize_number(item) for item in size],
                "pivot": [normalize_number(item) for item in cube["origin"]],
                "rotation": [normalize_number(-item) for item in cube["rotation"]],
                "uv": faces,
            }
        )
    bones = []
    for bone in spec["bones"]:
        output = {
            "name": bone["name"],
            "pivot": [normalize_number(item) for item in bone["pivot"]],
        }
        if bone["parent"] is not None:
            output["parent"] = bone["parent"]
        if cubes_by_bone[bone["name"]]:
            output["cubes"] = cubes_by_bone[bone["name"]]
        bones.append(output)
    collision = spec["collision"]
    return {
        "format_version": "1.12.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier": f"geometry.{spec['id']}",
                    "texture_width": atlas_size,
                    "texture_height": atlas_size,
                    "visible_bounds_width": normalize_number(collision["width"] * 16),
                    "visible_bounds_height": normalize_number(collision["height"] * 16),
                    "visible_bounds_offset": [0, normalize_number(collision["height"] * 8), 0],
                },
                "bones": bones,
            }
        ],
    }


def audit_bbmodel(data: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return {"ok": False, "errors": ["bbmodel must be a JSON object"], "warnings": []}
    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("missing meta object")
    resolution = data.get("resolution")
    if not isinstance(resolution, dict):
        errors.append("missing resolution object")
        width = height = 0
    else:
        width = resolution.get("width", 0)
        height = resolution.get("height", 0)
        if not (isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0):
            errors.append("invalid texture resolution")
            width = height = 0

    elements = data.get("elements")
    if not isinstance(elements, list) or not elements:
        errors.append("elements must be a non-empty array")
        elements = []
    element_ids: set[str] = set()
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            errors.append(f"elements[{index}] must be an object")
            continue
        element_uuid = element.get("uuid")
        if not isinstance(element_uuid, str):
            errors.append(f"elements[{index}] has no UUID")
        elif element_uuid in element_ids:
            errors.append(f"duplicate UUID: {element_uuid}")
        else:
            element_ids.add(element_uuid)
        from_pos = element.get("from")
        to_pos = element.get("to")
        if not (
            isinstance(from_pos, list)
            and isinstance(to_pos, list)
            and len(from_pos) == len(to_pos) == 3
            and all(finite_number(item) for item in from_pos + to_pos)
            and all(float(to_pos[axis]) > float(from_pos[axis]) for axis in range(3))
        ):
            errors.append(f"elements[{index}] has invalid bounds")
        faces = element.get("faces")
        if not isinstance(faces, dict) or set(faces) != set(FACES):
            errors.append(f"elements[{index}] must contain six faces")
        else:
            for face, face_data in faces.items():
                uv = face_data.get("uv") if isinstance(face_data, dict) else None
                if not (
                    isinstance(uv, list)
                    and len(uv) == 4
                    and all(finite_number(item) for item in uv)
                    and all(0 <= float(uv[item]) <= width for item in (0, 2))
                    and all(0 <= float(uv[item]) <= height for item in (1, 3))
                ):
                    errors.append(f"elements[{index}].faces.{face} has invalid UV")

    textures = data.get("textures")
    embedded = []
    if isinstance(textures, list):
        embedded = [
            texture for texture in textures
            if isinstance(texture, dict)
            and isinstance(texture.get("source"), str)
            and texture["source"].startswith("data:image/png;base64,")
        ]
    if len(embedded) != 1:
        errors.append("expected exactly one embedded PNG texture")
    elif width and height:
        try:
            raw = base64.b64decode(embedded[0]["source"].split(",", 1)[1], validate=True)
            with Image.open(io.BytesIO(raw)) as texture:
                if texture.size != (width, height):
                    errors.append("embedded texture dimensions do not match resolution")
        except (ValueError, OSError) as exc:
            errors.append(f"embedded texture is invalid: {exc}")

    group_ids: set[str] = set()
    referenced_elements: set[str] = set()

    def visit_group(group: Any, path: str) -> None:
        if not isinstance(group, dict):
            errors.append(f"{path} must be a group object")
            return
        group_uuid = group.get("uuid")
        if not isinstance(group_uuid, str):
            errors.append(f"{path} has no UUID")
        elif group_uuid in group_ids or group_uuid in element_ids:
            errors.append(f"duplicate UUID: {group_uuid}")
        else:
            group_ids.add(group_uuid)
        children = group.get("children")
        if not isinstance(children, list):
            errors.append(f"{path}.children must be an array")
            return
        for index, child in enumerate(children):
            if isinstance(child, str):
                if child not in element_ids:
                    errors.append(f"{path}.children[{index}] references missing element")
                referenced_elements.add(child)
            else:
                visit_group(child, f"{path}.children[{index}]")

    outliner = data.get("outliner")
    if not isinstance(outliner, list) or not outliner:
        errors.append("outliner must contain at least one group")
    else:
        for index, group in enumerate(outliner):
            visit_group(group, f"outliner[{index}]")
    orphans = element_ids - referenced_elements
    if orphans:
        errors.append(f"{len(orphans)} element(s) are orphaned from the outliner")

    if len(elements) > 128:
        warnings.append(
            "very high cuboid count is intended for reviewed high-detail models only"
        )
    elif len(elements) > 60:
        warnings.append("high cuboid count may be expensive in Minecraft")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "cuboids": len(elements),
        "bones": len(group_ids),
        "texture_size": [width, height],
        "estimated_triangles": len(elements) * 12,
    }


def deterministic_zip(path: Path, files: list[Path], base_dir: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in sorted(
            files, key=lambda item: item.relative_to(base_dir).as_posix()
        ):
            info = zipfile.ZipInfo(file_path.relative_to(base_dir).as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, file_path.read_bytes())


def portable_source_filename(path_value: str) -> str:
    """Return only a final filename for either POSIX or Windows source paths."""
    return path_value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def localize_review_artifacts(
    spec_path: Path,
    delivery_spec: dict[str, Any],
    output_dir: Path,
    review_key: str = "multi_angle_review",
) -> list[Path]:
    """Copy and hash seven-angle review evidence into a portable build."""
    generation = delivery_spec.get("generation")
    if not isinstance(generation, dict):
        return []
    review = generation.get(review_key)
    if review is None:
        return []
    if not isinstance(review, dict):
        raise ModelSpecError(f"generation.{review_key} must be an object")
    manifest_value = review.get("manifest")
    expected_manifest_hash = review.get("manifest_sha256")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise ModelSpecError("review manifest path is missing")
    if not isinstance(expected_manifest_hash, str) or not SHA_RE.fullmatch(
        expected_manifest_hash
    ):
        raise ModelSpecError("review manifest SHA-256 is invalid")
    manifest_input = Path(manifest_value)
    if not manifest_input.is_absolute():
        manifest_input = spec_path.parent / manifest_input
    manifest_input = manifest_input.resolve()
    if not manifest_input.is_file():
        raise ModelSpecError(f"review manifest not found: {manifest_input}")
    if sha256_file(manifest_input) != expected_manifest_hash:
        raise ModelSpecError("review manifest SHA-256 does not match")
    source_manifest = read_json(manifest_input)
    if not isinstance(source_manifest, dict):
        raise ModelSpecError("review manifest must be an object")
    if source_manifest.get("model_id") != delivery_spec["id"]:
        raise ModelSpecError("review manifest model_id does not match the model spec")
    is_model_review = review_key == "model_review"
    is_mesh_review = (
        review_key == "multi_angle_review"
        and isinstance(source_manifest.get("source_mesh"), dict)
    )
    manifest_spec = source_manifest.get("model_spec")
    if (is_model_review or is_mesh_review) and manifest_spec is None:
        label = "model" if is_model_review else "mesh"
        raise ModelSpecError(f"{label} review manifest must bind model content")
    if manifest_spec is not None:
        if not isinstance(manifest_spec, dict):
            raise ModelSpecError("review manifest model_spec must be an object")
        expected_spec_hash = manifest_spec.get("sha256")
        if expected_spec_hash is not None and (
            not isinstance(expected_spec_hash, str)
            or not SHA_RE.fullmatch(expected_spec_hash)
        ):
            raise ModelSpecError("review manifest model_spec SHA-256 is invalid")
        if is_model_review and expected_spec_hash is None:
            raise ModelSpecError("model review manifest model_spec SHA-256 is missing")
        exact_spec_match = (
            expected_spec_hash is not None
            and expected_spec_hash == sha256_file(spec_path)
        )
        expected_content_hash = manifest_spec.get("content_sha256")
        content_hash_method = manifest_spec.get("content_hash_method")
        has_content_binding = (
            isinstance(expected_content_hash, str)
            and bool(SHA_RE.fullmatch(expected_content_hash))
            and content_hash_method == MODEL_CONTENT_HASH_METHOD
        )
        if (
            expected_content_hash is not None
            or content_hash_method is not None
        ) and not has_content_binding:
            raise ModelSpecError(
                "review manifest model_spec content binding is invalid"
            )
        content_matches = (
            has_content_binding
            and expected_content_hash == model_content_sha256(delivery_spec)
        )
        if has_content_binding and not content_matches:
            raise ModelSpecError(
                "review manifest model_spec content SHA-256 does not match the model"
            )
        if is_mesh_review and not has_content_binding:
            raise ModelSpecError(
                "mesh review manifest must bind canonical model content"
            )
        if is_model_review:
            localized_delivery_binding = (
                manifest_spec.get("bundled") is False
                and manifest_spec.get("availability") == "source-provenance-only"
                and manifest_spec.get("delivery_file_name")
                == f"{delivery_spec['id']}.model-spec.json"
            )
            if not exact_spec_match and not (
                localized_delivery_binding and content_matches
            ):
                raise ModelSpecError(
                    "review manifest model_spec SHA-256 does not match the model spec"
                )
        elif (
            not is_mesh_review
            and expected_spec_hash is not None
            and not exact_spec_match
        ):
            raise ModelSpecError(
                "review manifest model_spec SHA-256 does not match the model spec"
            )
    if is_model_review:
        required_contract = {
            "method": "semantic-model-only-all-angle-review-v1",
            "model_only": True,
            "source_imagery_included": False,
            "resemblance_claimed": False,
            "agent_visual_review_required": True,
        }
        for key, expected in required_contract.items():
            if source_manifest.get(key) != expected:
                raise ModelSpecError(
                    f"model review manifest {key} must be {expected!r}"
                )
        if source_manifest.get("approval_status") not in {
            "pending_agent_visual_review",
            "passed_agent_visual_review",
        }:
            raise ModelSpecError("model review manifest approval_status is invalid")
        if not isinstance(source_manifest.get("all_angle_sheet"), dict):
            raise ModelSpecError("model review manifest requires an all-angle sheet")
    views = source_manifest.get("views")
    required_views = [
        "front",
        "back",
        "left",
        "right",
        "top",
        "bottom",
        "isometric",
    ]
    if not isinstance(views, list):
        raise ModelSpecError("review manifest views must be an array")
    view_by_id: dict[str, dict[str, Any]] = {}
    for index, view in enumerate(views):
        if not isinstance(view, dict):
            raise ModelSpecError(f"review view {index} must be an object")
        view_id = view.get("id")
        if not isinstance(view_id, str) or view_id not in required_views:
            raise ModelSpecError(f"review view {index} has an invalid id")
        if view_id in view_by_id:
            raise ModelSpecError(f"review view id is duplicated: {view_id}")
        view_by_id[view_id] = view
    if list(view_by_id) != required_views:
        raise ModelSpecError(
            "review manifest must contain ordered front, back, left, right, "
            "top, bottom, and isometric views"
        )
    if (
        source_manifest.get("required_views") != required_views
        or source_manifest.get("generated_views") != required_views
        or not source_manifest.get("complete")
    ):
        raise ModelSpecError("review manifest is incomplete")

    model_id = delivery_spec["id"]
    review_label = (
        "mesh review"
        if is_mesh_review
        else "model review" if is_model_review else "review"
    )
    review_suffix = "mesh-views" if is_mesh_review else "model-review"
    destination_directory = output_dir / f"{model_id}.{review_suffix}"
    destination_directory.mkdir(parents=True, exist_ok=True)
    localized_views: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []
    for view_id in required_views:
        view = view_by_id[view_id]
        image_value = view.get("image")
        expected_image_hash = view.get("image_sha256")
        if not isinstance(image_value, str) or not image_value:
            raise ModelSpecError(f"review image path is missing for {view_id}")
        if not isinstance(expected_image_hash, str) or not SHA_RE.fullmatch(
            expected_image_hash
        ):
            raise ModelSpecError(f"review image SHA-256 is invalid for {view_id}")
        image_input = Path(image_value)
        if is_model_review and (
            image_input.is_absolute()
            or ".." in image_input.parts
            or "\\" in image_value
        ):
            raise ModelSpecError(
                f"model review image path must be portable for {view_id}"
            )
        if not image_input.is_absolute():
            image_input = manifest_input.parent / image_input
        image_input = image_input.resolve()
        if is_model_review:
            try:
                image_input.relative_to(manifest_input.parent.resolve())
            except ValueError as exc:
                raise ModelSpecError(
                    f"model review image escapes its directory for {view_id}"
                ) from exc
        if not image_input.is_file():
            raise ModelSpecError(f"review image not found: {image_input}")
        image_bytes = image_input.read_bytes()
        if sha256_bytes(image_bytes) != expected_image_hash:
            raise ModelSpecError(
                f"{review_label} image SHA-256 does not match for {view_id}"
            )
        try:
            with Image.open(io.BytesIO(image_bytes)) as opened:
                if opened.format != "PNG":
                    raise ModelSpecError(
                        f"review image must be PNG for {view_id}"
                    )
                image_size = list(opened.size)
        except OSError as exc:
            raise ModelSpecError(
                f"cannot read review image for {view_id}: {exc}"
            ) from exc
        if view.get("image_size") != image_size:
            raise ModelSpecError(
                f"review image dimensions do not match for {view_id}"
            )
        image_output = destination_directory / f"{view_id}.png"
        image_output.write_bytes(image_bytes)
        localized_view = json.loads(json.dumps(view))
        localized_view["image"] = image_output.relative_to(output_dir).as_posix()
        localized_views.append(localized_view)
        artifact_paths.append(image_output)

    localized_manifest = json.loads(json.dumps(source_manifest))
    localized_manifest["views"] = localized_views
    sheet = localized_manifest.get("all_angle_sheet")
    if sheet is not None:
        if not isinstance(sheet, dict):
            raise ModelSpecError("review all_angle_sheet must be an object")
        sheet_value = sheet.get("image")
        expected_sheet_hash = sheet.get("image_sha256")
        if not isinstance(sheet_value, str) or not sheet_value:
            raise ModelSpecError("review all-angle sheet path is missing")
        if not isinstance(expected_sheet_hash, str) or not SHA_RE.fullmatch(
            expected_sheet_hash
        ):
            raise ModelSpecError("review all-angle sheet SHA-256 is invalid")
        sheet_input = Path(sheet_value)
        if is_model_review and (
            sheet_input.is_absolute()
            or ".." in sheet_input.parts
            or "\\" in sheet_value
        ):
            raise ModelSpecError("model review all-angle sheet path must be portable")
        if not sheet_input.is_absolute():
            sheet_input = manifest_input.parent / sheet_input
        sheet_input = sheet_input.resolve()
        if is_model_review:
            try:
                sheet_input.relative_to(manifest_input.parent.resolve())
            except ValueError as exc:
                raise ModelSpecError(
                    "model review all-angle sheet escapes its directory"
                ) from exc
        if not sheet_input.is_file():
            raise ModelSpecError(f"review all-angle sheet not found: {sheet_input}")
        sheet_bytes = sheet_input.read_bytes()
        if sha256_bytes(sheet_bytes) != expected_sheet_hash:
            raise ModelSpecError("review all-angle sheet SHA-256 does not match")
        try:
            with Image.open(io.BytesIO(sheet_bytes)) as opened:
                if opened.format != "PNG":
                    raise ModelSpecError("review all-angle sheet must be PNG")
        except OSError as exc:
            raise ModelSpecError(
                f"cannot read review all-angle sheet: {exc}"
            ) from exc
        sheet_output = destination_directory / "all-angle-sheet.png"
        sheet_output.write_bytes(sheet_bytes)
        sheet["image"] = sheet_output.relative_to(output_dir).as_posix()
        artifact_paths.append(sheet_output)
    if is_model_review:
        localized_spec = localized_manifest["model_spec"]
        localized_spec["content_hash_method"] = MODEL_CONTENT_HASH_METHOD
        localized_spec["content_sha256"] = model_content_sha256(delivery_spec)
        source_file_value = localized_spec.pop(
            "file_name",
            localized_spec.get("source_file_name", spec_path.name),
        )
        localized_spec["source_file_name"] = portable_source_filename(
            str(source_file_value)
        )
        localized_spec["bundled"] = False
        localized_spec["availability"] = "source-provenance-only"
        localized_spec["delivery_file_name"] = f"{model_id}.model-spec.json"
        localized_spec["delivery_binding"] = (
            "content_sha256 binds semantic model content while excluding only "
            "build-local reference, review, and mesh provenance paths"
        )
    manifest_mesh = localized_manifest.get("source_mesh")
    if isinstance(manifest_mesh, dict):
        source_path_value = manifest_mesh.pop("path", None)
        if isinstance(source_path_value, str) and source_path_value:
            manifest_mesh["source_file_name"] = portable_source_filename(
                source_path_value
            )
        manifest_mesh["bundled"] = False
        manifest_mesh["availability"] = "external-provenance-only"
    manifest_output = output_dir / f"{model_id}.{review_suffix}.json"
    write_json(manifest_output, localized_manifest)
    localized_hash = sha256_file(manifest_output)
    review["manifest"] = manifest_output.name
    review["manifest_sha256"] = localized_hash
    review["directory"] = destination_directory.name
    review["required_views"] = required_views
    review["generated_views"] = required_views
    review["view_count"] = len(required_views)
    review["complete"] = True
    review["views"] = {}
    for view in localized_views:
        summary = {
            "image": view["image"],
            "image_sha256": view["image_sha256"],
        }
        for key in ("silhouette_iou", "metrics"):
            if key in view:
                summary[key] = view[key]
        review["views"][view["id"]] = summary
    delivery_mesh = generation.get("mesh")
    if isinstance(delivery_mesh, dict):
        source_path_value = delivery_mesh.pop("path", None)
        if isinstance(source_path_value, str) and source_path_value:
            delivery_mesh["source_file_name"] = portable_source_filename(
                source_path_value
            )
        delivery_mesh["bundled"] = False
        delivery_mesh["availability"] = "external-provenance-only"
    return [manifest_output, *artifact_paths]


localize_mesh_review_artifacts = localize_review_artifacts


def typescript_identifier(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    identifier = "".join(word[:1].upper() + word[1:] for word in words)
    if not identifier:
        identifier = "Model"
    if identifier[0].isdigit():
        identifier = f"Model{identifier}"
    return identifier


def make_threejs_factory(spec: dict[str, Any]) -> str:
    """Emit a constrained Three.js preview from the same cuboid specification."""
    errors = validate_spec(spec, strict=True)
    if errors:
        raise ModelSpecError(
            "cannot export invalid specification:\n"
            + "\n".join(f"- {error}" for error in errors)
        )

    function_name = f"create{typescript_identifier(spec['id'])}Model"
    material_names = list(spec["materials"])
    material_indexes = {name: index for index, name in enumerate(material_names)}
    lines = [
        'import * as THREE from "three";',
        "",
        "/**",
        " * Generated by img2blockbench from its Minecraft cuboid scene spec.",
        " * Edit the JSON specification, not this generated file.",
        " */",
        f"export function {function_name}(): THREE.Group {{",
        "  const root = new THREE.Group();",
        f'  root.name = {json.dumps(spec["id"])};',
        "  const materials = [",
    ]
    for name in material_names:
        color = spec["materials"][name]["base"]
        lines.append(
            "    new THREE.MeshBasicMaterial({ "
            f"name: {json.dumps(name)}, color: {json.dumps(color)}, toneMapped: false "
            "}),"
        )
    lines.extend(["  ];", ""])

    for cube in spec["cubes"]:
        override_faces = cube.get("faces", {})
        face_materials = []
        for face in ("east", "west", "up", "down", "south", "north"):
            material_name = override_faces.get(face, {}).get(
                "material", cube["material"]
            )
            face_materials.append(f"materials[{material_indexes[material_name]}]")
        if isinstance(spec.get("geometry"), dict):
            minimum, maximum = exported_cube_bounds(spec, cube)
            center = [
                (minimum[index] + maximum[index]) / 2 for index in range(3)
            ]
            size = [maximum[index] - minimum[index] for index in range(3)]
        else:
            center = [float(value) for value in cube["center"]]
            size = [float(value) for value in cube["size"]]
        origin = [float(value) for value in cube["origin"]]
        rotation = [math.radians(float(value)) for value in cube["rotation"]]
        local = [center[index] - origin[index] for index in range(3)]
        safe_name = json.dumps(cube["name"])
        lines.extend(
            [
                "  {",
                "    const mesh = new THREE.Mesh(",
                f"      new THREE.BoxGeometry({size[0]:g}, {size[1]:g}, {size[2]:g}),",
                f"      [{', '.join(face_materials)}],",
                "    );",
                f"    mesh.name = {safe_name};",
                f"    mesh.position.set({local[0]:g}, {local[1]:g}, {local[2]:g});",
                "    const pivot = new THREE.Group();",
                f"    pivot.name = {json.dumps(cube['name'] + '_pivot')};",
                f"    pivot.position.set({origin[0]:g}, {origin[1]:g}, {origin[2]:g});",
                '    pivot.rotation.order = "ZYX";',
                f"    pivot.rotation.set({rotation[0]:.12g}, {rotation[1]:.12g}, {rotation[2]:.12g});",
                "    pivot.add(mesh);",
                "    root.add(pivot);",
                "  }",
                "",
            ]
        )

    lines.extend(
        [
            "  root.userData.img2blockbench = {",
            '    representation: "minecraft-cuboids",',
            f"    componentCount: {len(spec['cubes'])},",
            '    source: "agent-authored-image-reconstruction",',
            "  };",
            "  return root;",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def build_model(
    spec_path: Path,
    output_dir: Path,
    *,
    reference_policy: str = "bundle",
    review_manifest: Path | None = None,
) -> dict[str, Any]:
    """Compile a model and optionally keep its source reference external."""
    if reference_policy not in {"bundle", "external"}:
        raise ModelSpecError("reference_policy must be bundle or external")
    spec = validated_spec(spec_path, strict=True)
    reference_input = resolve_reference_path(spec_path, spec)
    model_id = spec["id"]
    spec_output = output_dir / f"{model_id}.model-spec.json"
    texture_output = output_dir / f"{model_id}.png"
    bbmodel_output = output_dir / f"{model_id}.bbmodel"
    geometry_output = output_dir / f"{model_id}.geo.json"
    audit_output = output_dir / f"{model_id}.audit.json"
    manifest_output = output_dir / f"{model_id}.manifest.json"
    bundle_output = output_dir / f"{model_id}.zip"
    reference_suffix = reference_input.suffix.lower() or ".img"
    reference_output = output_dir / f"{model_id}.reference{reference_suffix}"

    protected_inputs = {
        "model specification": spec_path.resolve(),
        "source reference": reference_input.resolve(),
    }
    generation = spec.get("generation")
    review_keys: set[str] = set()
    if isinstance(generation, dict):
        for review_key in ("multi_angle_review", "model_review"):
            review = generation.get(review_key)
            if not isinstance(review, dict):
                continue
            review_keys.add(review_key)
            manifest_value = review.get("manifest")
            if isinstance(manifest_value, str) and manifest_value:
                manifest_input = Path(manifest_value)
                if not manifest_input.is_absolute():
                    manifest_input = spec_path.parent / manifest_input
                protected_inputs[f"{review_key} manifest"] = manifest_input.resolve()
    if review_manifest is not None:
        review_keys.add("model_review")
        protected_inputs["model_review manifest"] = review_manifest.resolve()

    planned_outputs = {
        "delivery model specification": spec_output,
        "texture atlas": texture_output,
        "Blockbench model": bbmodel_output,
        "Bedrock geometry": geometry_output,
        "audit": audit_output,
        "artifact manifest": manifest_output,
        "bundle": bundle_output,
    }
    if reference_policy == "bundle":
        planned_outputs["bundled reference"] = reference_output
    if "wearable" in spec:
        wearable_id = f"{model_id[:55]}_wearable"
        for suffix in (
            "model-spec.json",
            "png",
            "bbmodel",
            "geo.json",
            "attachable.json",
            "audit.json",
        ):
            planned_outputs[f"wearable {suffix}"] = (
                output_dir / f"{wearable_id}.{suffix}"
            )
    for review_key in review_keys:
        suffixes = (
            ("mesh-views", "model-review")
            if review_key == "multi_angle_review"
            else ("model-review",)
        )
        for review_suffix in suffixes:
            planned_outputs[f"{review_suffix} manifest"] = (
                output_dir / f"{model_id}.{review_suffix}.json"
            )
            review_directory = output_dir / f"{model_id}.{review_suffix}"
            for view_id in (
                "front",
                "back",
                "left",
                "right",
                "top",
                "bottom",
                "isometric",
            ):
                planned_outputs[f"{review_suffix} {view_id}"] = (
                    review_directory / f"{view_id}.png"
                )
            planned_outputs[f"{review_suffix} sheet"] = (
                review_directory / "all-angle-sheet.png"
            )
    resolved_output_root = output_dir.resolve()
    resolved_outputs: dict[Path, str] = {}
    for output_label, output_path in planned_outputs.items():
        if output_path.is_symlink() or (
            output_path.exists() and not output_path.is_file()
        ):
            raise ModelSpecError(f"build {output_label} path is unsafe: {output_path}")
        resolved_output = output_path.resolve()
        try:
            resolved_output.relative_to(resolved_output_root)
        except ValueError as exc:
            raise ModelSpecError(
                f"build {output_label} escapes the output directory: {output_path}"
            ) from exc
        prior_label = resolved_outputs.get(resolved_output)
        if prior_label is not None:
            raise ModelSpecError(
                f"build outputs collide: {prior_label} and {output_label}"
            )
        resolved_outputs[resolved_output] = output_label
        for input_label, input_path in protected_inputs.items():
            if resolved_output == input_path:
                raise ModelSpecError(
                    f"build {output_label} would overwrite {input_label}: "
                    f"{output_path}"
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    texture, placements = build_texture(spec)
    texture_raw = png_bytes(texture)
    bbmodel = make_bbmodel(spec, texture_raw, texture.width, placements)
    audit = audit_bbmodel(bbmodel)
    if not audit["ok"]:
        raise ModelSpecError(
            "generated bbmodel failed audit:\n"
            + "\n".join(f"- {error}" for error in audit["errors"])
        )

    delivery_spec = json.loads(json.dumps(spec))
    if reference_policy == "bundle":
        delivery_spec["reference"]["image"] = reference_output.name
    else:
        source_file_name = portable_source_filename(spec["reference"]["image"])
        if source_file_name in {"", ".", ".."}:
            raise ModelSpecError("reference image filename is not portable")
        delivery_spec["reference"].update(
            {
                "image": f"external-reference/{source_file_name}",
                "source_file_name": source_file_name,
                "bundled": False,
                "availability": "external-provenance-only",
                "required_for_model_use": False,
            }
        )
    if review_manifest is not None:
        review_input = review_manifest.resolve()
        if not review_input.is_file():
            raise ModelSpecError(f"review manifest not found: {review_input}")
        generation = delivery_spec.setdefault("generation", {})
        if not isinstance(generation, dict):
            raise ModelSpecError("generation must be an object")
        if "model_review" in generation:
            raise ModelSpecError(
                "generation.model_review already exists; omit --review-manifest "
                "or remove the stale review declaration"
            )
        generation["model_review"] = {
            "manifest": str(review_input),
            "manifest_sha256": sha256_file(review_input),
        }
    review_paths: list[Path] = []
    for review_key in ("multi_angle_review", "model_review"):
        review_paths.extend(
            localize_review_artifacts(
                spec_path,
                delivery_spec,
                output_dir,
                review_key,
            )
        )
    write_json(spec_output, delivery_spec)
    if reference_policy == "bundle":
        reference_output.write_bytes(reference_input.read_bytes())
    texture_output.write_bytes(texture_raw)
    write_json(bbmodel_output, bbmodel)
    write_json(geometry_output, make_bedrock_geometry(spec, placements, texture.width))
    write_json(audit_output, audit)

    artifact_paths = [
        spec_output,
        texture_output,
        bbmodel_output,
        geometry_output,
        audit_output,
    ]
    if reference_policy == "bundle":
        artifact_paths.append(reference_output)
    artifact_paths.extend(review_paths)
    wearable_result = None
    if "wearable" in spec:
        wearable_spec = make_wearable_spec(spec)
        wearable_spec["reference"] = json.loads(
            json.dumps(delivery_spec["reference"])
        )
        wearable_errors = validate_spec(wearable_spec, strict=True)
        if wearable_errors:
            raise ModelSpecError(
                "generated wearable specification failed validation:\n"
                + "\n".join(f"- {error}" for error in wearable_errors)
            )
        wearable_texture, wearable_placements = build_texture(wearable_spec)
        wearable_texture_raw = png_bytes(wearable_texture)
        wearable_bbmodel = make_bbmodel(
            wearable_spec,
            wearable_texture_raw,
            wearable_texture.width,
            wearable_placements,
        )
        wearable_bbmodel["img2blockbench"]["wearable"] = wearable_spec[
            "generation"
        ]["wearable_export"]
        wearable_audit = audit_bbmodel(wearable_bbmodel)
        if not wearable_audit["ok"]:
            raise ModelSpecError(
                "generated wearable bbmodel failed audit:\n"
                + "\n".join(f"- {error}" for error in wearable_audit["errors"])
            )

        wearable_id = wearable_spec["id"]
        wearable_spec_output = output_dir / f"{wearable_id}.model-spec.json"
        wearable_texture_output = output_dir / f"{wearable_id}.png"
        wearable_bbmodel_output = output_dir / f"{wearable_id}.bbmodel"
        wearable_geometry_output = output_dir / f"{wearable_id}.geo.json"
        wearable_attachable_output = output_dir / f"{wearable_id}.attachable.json"
        wearable_audit_output = output_dir / f"{wearable_id}.audit.json"
        write_json(wearable_spec_output, wearable_spec)
        wearable_texture_output.write_bytes(wearable_texture_raw)
        write_json(wearable_bbmodel_output, wearable_bbmodel)
        write_json(
            wearable_geometry_output,
            make_bedrock_geometry(
                wearable_spec,
                wearable_placements,
                wearable_texture.width,
            ),
        )
        write_json(
            wearable_attachable_output,
            make_bedrock_attachable(spec, wearable_spec),
        )
        write_json(wearable_audit_output, wearable_audit)
        wearable_paths = [
            wearable_spec_output,
            wearable_texture_output,
            wearable_bbmodel_output,
            wearable_geometry_output,
            wearable_attachable_output,
            wearable_audit_output,
        ]
        artifact_paths.extend(wearable_paths)
        wearable_result = {
            "model_id": wearable_id,
            "artifacts": [path.name for path in wearable_paths],
            "audit": wearable_audit,
        }
    generation = spec.get("generation", {})
    manifest_lane = (
        generation.get("lane", "direct")
        if isinstance(generation, dict)
        else "direct"
    )
    manifest = {
        "schema_version": 1,
        "generator": {
            "name": "img2blockbench",
            "version": VERSION,
            "lane": manifest_lane,
        },
        "model_id": model_id,
        "reference": delivery_spec["reference"],
        "reference_policy": reference_policy,
        **(
            {
                "external_artifacts": [
                    {
                        "kind": "source_reference",
                        "filename": portable_source_filename(
                            spec["reference"]["image"]
                        ),
                        "sha256": spec["reference"]["sha256"],
                        "bundled": False,
                        "required_for_model_use": False,
                    }
                ]
            }
            if reference_policy == "external"
            else {}
        ),
        "collision": spec["collision"],
        **({"wearable": wearable_result} if wearable_result is not None else {}),
        "artifacts": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in artifact_paths
        ],
    }
    write_json(manifest_output, manifest)
    deterministic_zip(
        bundle_output,
        artifact_paths + [manifest_output],
        output_dir,
    )
    result = {
        "ok": True,
        "model_id": model_id,
        "output": str(output_dir.resolve()),
        "bundle": str(bundle_output.resolve()),
        "audit": audit,
        "reference_policy": reference_policy,
    }
    if wearable_result is not None:
        result["wearable"] = wearable_result
    if review_paths:
        generation = delivery_spec["generation"]
        if "multi_angle_review" in generation:
            mesh_review = (output_dir / generation["multi_angle_review"]["manifest"]).resolve()
            result["multi_angle_review_manifest"] = str(mesh_review)
            result["review_manifest"] = str(mesh_review)
        if "model_review" in generation:
            model_review = (output_dir / generation["model_review"]["manifest"]).resolve()
            result["model_review_manifest"] = str(model_review)
            result["review_manifest"] = str(model_review)
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="img2blockbench",
        description="Compile agent-authored image reconstructions into Minecraft models.",
    )
    root.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = root.add_subparsers(dest="command", required=True)

    probe = commands.add_parser("probe", help="Inspect reference image metadata and palette")
    probe.add_argument("image", type=Path)
    probe.add_argument("--output", type=Path)

    new = commands.add_parser("new", help="Create an agent-editable starter model specification")
    new.add_argument("image", type=Path)
    new.add_argument("--id", required=True)
    new.add_argument("--output", required=True, type=Path)
    new.add_argument("--description", default="Agent-authored Minecraft reconstruction")
    new.add_argument("--complexity", choices=("simple", "moderate", "complex"), default="moderate")

    validate = commands.add_parser("validate", help="Validate a model specification")
    validate.add_argument("spec", type=Path)
    validate.add_argument("--strict", action="store_true")

    review = commands.add_parser(
        "review",
        aliases=["render-review"],
        help="Render hash-bound model-only evidence from seven directions",
    )
    review.add_argument("spec", type=Path)
    review.add_argument("--output", required=True, type=Path)
    review.add_argument(
        "--image-size",
        type=int,
        nargs=2,
        default=(640, 640),
        metavar=("WIDTH", "HEIGHT"),
    )
    review.add_argument(
        "--build-output",
        type=Path,
        help="Optionally compile and package the generated review with the model",
    )
    review.add_argument(
        "--reference-policy",
        choices=("bundle", "external"),
        default="bundle",
        help="With --build-output, bundle the source or keep only hash provenance",
    )

    build = commands.add_parser("build", help="Compile a strict model specification")
    build.add_argument("spec", type=Path)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument(
        "--reference-policy",
        choices=("bundle", "external"),
        default="bundle",
        help="Bundle the source image or retain only portable hash provenance",
    )
    build.add_argument(
        "--review-manifest",
        type=Path,
        help="Package a hash-bound seven-angle review manifest and its PNGs",
    )

    bake_reference = commands.add_parser(
        "bake-reference-textures",
        help="Bake calibrated, visible reference pixels into cuboid face textures",
    )
    bake_reference.add_argument("spec", type=Path)
    bake_reference.add_argument("--views", required=True, type=Path)
    bake_reference.add_argument("--output", required=True, type=Path)
    bake_reference.add_argument("--audit", type=Path)
    bake_reference.add_argument("--texture-density", type=int, choices=(1, 2, 4))
    bake_reference.add_argument(
        "--atlas-size",
        type=int,
        choices=(16, 32, 64, 128, 256, 512, 1024, 2048),
    )
    bake_reference.add_argument("--mask-threshold", type=int, default=128)
    bake_reference.add_argument(
        "--style",
        choices=("minecraft", "source"),
        default="minecraft",
        help="Use bounded Minecraft pixel art or verbatim source pixels",
    )
    bake_reference.add_argument(
        "--palette-size",
        type=int,
        default=24,
        help="Global source-derived palette colors for Minecraft style (4..64)",
    )
    bake_reference.add_argument(
        "--colors-per-material",
        type=int,
        default=4,
        help="Maximum source-derived colors retained per material (1..8)",
    )

    threejs = commands.add_parser(
        "preview-threejs",
        aliases=["threejs"],
        help="Export the same strict cuboid specification as a Three.js Group factory",
    )
    threejs.add_argument("spec", type=Path)
    threejs.add_argument("--output", required=True, type=Path)

    from_threejs = commands.add_parser(
        "from-threejs",
        help="Convert constrained Three.js Object3D.toJSON output into a model spec",
    )
    from_threejs.add_argument("scene", type=Path)
    from_threejs.add_argument("--reference", required=True, type=Path)
    from_threejs.add_argument("--id", required=True)
    from_threejs.add_argument("--description", required=True)
    from_threejs.add_argument("--output", required=True, type=Path)
    from_threejs.add_argument(
        "--build-output",
        type=Path,
        help="Optionally compile the emitted spec into a native Blockbench bundle",
    )
    from_threejs.add_argument(
        "--reference-policy",
        choices=("bundle", "external"),
        default="bundle",
        help="With --build-output, bundle the source or keep only hash provenance",
    )

    from_image = commands.add_parser(
        "from-image",
        help="Reconstruct an arbitrary image as a segmented native cuboid relief",
    )
    from_image.add_argument("image", type=Path)
    from_image.add_argument("--id", required=True)
    from_image.add_argument("--description", required=True)
    from_image.add_argument("--subject-type", default="object")
    from_image.add_argument("--output", required=True, type=Path)
    from_image.add_argument(
        "--build-output",
        type=Path,
        help="Optionally compile the emitted spec into a native Blockbench bundle",
    )
    from_image.add_argument(
        "--reference-policy",
        choices=("bundle", "external"),
        default="bundle",
        help="With --build-output, bundle the source or keep only hash provenance",
    )
    from_image.add_argument("--diagnostics", type=Path)
    from_image.add_argument("--analysis-size", type=int, default=96)
    from_image.add_argument("--grid-size", type=int, default=64)
    from_image.add_argument("--max-cuboids", type=int, default=70)
    from_image.add_argument("--target-size", type=float, default=32.0)
    from_image.add_argument("--target-depth", type=float, default=7.0)
    from_image.add_argument("--relief-layers", type=int, default=3)
    from_image.add_argument(
        "--geometry-precision",
        type=int,
        help="Geometry subdivisions per model unit, independent of texture density",
    )
    from_image.add_argument(
        "--texture-density",
        type=int,
        choices=(1, 2, 4),
        help="Atlas texels per model unit; defaults by depth mode",
    )
    from_image.add_argument(
        "--foreground-mask",
        type=Path,
        help="Full-resolution binary/alpha mask supplied by an external segmenter",
    )
    from_image.add_argument(
        "--subject-bbox",
        "--foreground-bbox",
        type=int,
        nargs=4,
        metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
        help="Pixel-space subject bounds; clips a mask or limits auto segmentation",
    )
    from_image.add_argument(
        "--depth-map",
        type=Path,
        help="Full-resolution grayscale thickness map, such as a mesh ray-hit pass",
    )
    from_image.add_argument(
        "--depth-mode",
        choices=("one-sided", "symmetric"),
        default="one-sided",
        help="Build a rearward relief or a bilateral volume around its center plane",
    )
    from_image.add_argument(
        "--decomposition",
        choices=("scanline", "adaptive", "oriented"),
        default="scanline",
        help=(
            "Convert each depth shell into runs, large cuboids, or principal-axis "
            "oriented cuboids"
        ),
    )
    from_image.add_argument(
        "--orientation-degrees",
        type=float,
        help="Override the image-space principal-axis angle used by oriented mode",
    )
    from_image.add_argument(
        "--mask-coverage",
        type=float,
        default=0.08,
        help="Minimum fractional cell coverage retained by oriented resampling",
    )
    from_image.add_argument(
        "--background",
        choices=("auto", "alpha", "none"),
        default="auto",
    )

    from_mesh = commands.add_parser(
        "from-mesh",
        help=(
            "Reconstruct a textured triangle mesh with six-view ray-derived "
            "native cuboids"
        ),
    )
    from_mesh.add_argument("mesh", type=Path)
    from_mesh.add_argument("--reference", type=Path)
    from_mesh.add_argument("--id", required=True)
    from_mesh.add_argument("--description", required=True)
    from_mesh.add_argument("--subject-type", default="object")
    from_mesh.add_argument("--output", required=True, type=Path)
    from_mesh.add_argument(
        "--evidence",
        type=Path,
        help=(
            "Mesh ray, component, thickness, color-transfer, overlap, and "
            "multi-angle review evidence JSON"
        ),
    )
    from_mesh.add_argument(
        "--build-output",
        type=Path,
        help="Optionally compile the emitted spec into a native Blockbench bundle",
    )
    from_mesh.add_argument(
        "--reference-policy",
        choices=("bundle", "external"),
        default="bundle",
        help="With --build-output, bundle the source or keep only hash provenance",
    )
    from_mesh.add_argument("--resolution", type=int, default=28)
    from_mesh.add_argument("--max-cuboids", type=int, default=72)
    from_mesh.add_argument("--target-size", type=float, default=32.0)
    from_mesh.add_argument("--palette-size", type=int, default=16)
    from_mesh.add_argument(
        "--fill-mode", choices=("auto", "surface", "solid"), default="auto"
    )
    from_mesh.add_argument("--surface-thickness", type=int, default=1)
    from_mesh.add_argument("--min-component-voxels", type=int, default=2)
    from_mesh.add_argument("--min-component-fraction", type=float, default=0.001)
    from_mesh.add_argument("--geometry-precision", type=int, default=64)
    from_mesh.add_argument("--texture-density", type=int, choices=(1, 2, 4), default=1)
    from_mesh.add_argument("--provider", default="user-supplied")
    from_mesh.add_argument("--provider-model", default="unrecorded")
    from_mesh.add_argument("--source-license", default="unrecorded")
    from_mesh.add_argument(
        "--canonical-transform",
        type=float,
        nargs=16,
        metavar=(
            "M00", "M01", "M02", "M03",
            "M10", "M11", "M12", "M13",
            "M20", "M21", "M22", "M23",
            "M30", "M31", "M32", "M33",
        ),
        help="Row-major 4x4 transform applied after scene node transforms",
    )

    from_views = commands.add_parser(
        "from-views",
        help="Carve calibrated orthographic-yaw masks into a native cuboid visual hull",
    )
    from_views.add_argument("manifest", type=Path)
    from_views.add_argument("--id", required=True)
    from_views.add_argument("--description", required=True)
    from_views.add_argument("--subject-type", default="object")
    from_views.add_argument("--output", required=True, type=Path)
    from_views.add_argument(
        "--evidence",
        type=Path,
        help="Calibration, carving, fit, color-fusion, and silhouette evidence JSON",
    )
    from_views.add_argument(
        "--build-output",
        type=Path,
        help="Optionally compile the emitted spec into a native Blockbench bundle",
    )
    from_views.add_argument(
        "--reference-policy",
        choices=("bundle", "external"),
        default="bundle",
        help="With --build-output, bundle the source or keep only hash provenance",
    )
    from_views.add_argument("--resolution", type=int, default=32)
    from_views.add_argument("--max-cuboids", type=int, default=72)
    from_views.add_argument("--target-size", type=float, default=32.0)
    from_views.add_argument("--palette-size", type=int, default=16)
    from_views.add_argument("--mask-threshold", type=int, default=128)
    from_views.add_argument("--min-component-voxels", type=int, default=2)
    from_views.add_argument("--min-component-fraction", type=float, default=0.001)
    from_views.add_argument("--geometry-precision", type=int, default=64)
    from_views.add_argument("--texture-density", type=int, choices=(1, 2, 4), default=1)

    extract_clip = commands.add_parser(
        "extract-clip-views",
        help="Extract caller-timestamped frames and preserve explicit yaw calibration",
    )
    extract_clip.add_argument("clip", type=Path)
    extract_clip.add_argument("--samples", required=True, type=Path)
    extract_clip.add_argument("--output", required=True, type=Path)
    extract_clip.add_argument("--frames-dir", required=True, type=Path)
    extract_clip.add_argument("--ffmpeg", default="ffmpeg")

    render_relief = commands.add_parser(
        "render-relief",
        help="Render deterministic front/isometric evidence for a photo relief",
    )
    render_relief.add_argument("spec", type=Path)
    render_relief.add_argument("--output", required=True, type=Path)

    audit = commands.add_parser("audit", help="Audit a generated Blockbench model")
    audit.add_argument("bbmodel", type=Path)
    audit.add_argument("--output", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if (
            args.command
            in {
                "review",
                "render-review",
                "from-threejs",
                "from-image",
                "from-mesh",
                "from-views",
            }
            and args.reference_policy != "bundle"
            and args.build_output is None
        ):
            raise ModelSpecError(
                "--reference-policy only affects --build-output; add a build "
                "destination or omit the policy"
            )
        if args.command == "probe":
            result = image_probe(args.image)
            if args.output:
                write_json(args.output, result)
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "new":
            if not ID_RE.fullmatch(args.id):
                raise ModelSpecError("id must match [a-z0-9][a-z0-9_-]{0,63}")
            result = starter_spec(
                args.image,
                args.output,
                args.id,
                args.description,
                args.complexity,
            )
            write_json(args.output, result)
            errors = validate_spec(result)
            if errors:
                raise ModelSpecError("starter generation failed:\n" + "\n".join(f"- {item}" for item in errors))
            print(json.dumps({"ok": True, "spec": str(args.output.resolve())}, indent=2))
        elif args.command == "validate":
            validated_spec(args.spec, strict=args.strict)
            print(json.dumps({"ok": True, "strict": args.strict, "spec": str(args.spec.resolve())}, indent=2))
        elif args.command in {"review", "render-review"}:
            try:
                from model_review import MANIFEST_NAME, render_model_review

                manifest = render_model_review(
                    args.spec,
                    args.output,
                    image_size=tuple(args.image_size),
                )
            except (OSError, ValueError, ModuleNotFoundError) as exc:
                raise ModelSpecError(f"model review failed: {exc}") from exc
            result: dict[str, Any] = {
                "ok": manifest["complete"],
                "manifest": str((args.output / MANIFEST_NAME).resolve()),
                "all_angle_sheet": str(
                    (args.output / manifest["all_angle_sheet"]["image"]).resolve()
                ),
                "generated_views": manifest["generated_views"],
                "agent_visual_review_required": True,
            }
            if args.build_output:
                result["build"] = build_model(
                    args.spec,
                    args.build_output,
                    reference_policy=args.reference_policy,
                    review_manifest=args.output / MANIFEST_NAME,
                )
            print(json.dumps(result, indent=2, sort_keys=True))
            if not manifest["complete"]:
                return 1
        elif args.command == "build":
            print(
                json.dumps(
                    build_model(
                        args.spec,
                        args.output,
                        reference_policy=args.reference_policy,
                        review_manifest=args.review_manifest,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "bake-reference-textures":
            source_spec = validated_spec(args.spec, strict=True)
            reference_input = resolve_reference_path(args.spec, source_spec)
            try:
                from reference_texture import (
                    ReferenceTextureBakeOptions,
                    bake_reference_textures,
                )

                result, evidence = bake_reference_textures(
                    source_spec,
                    args.views,
                    ReferenceTextureBakeOptions(
                        texture_density=args.texture_density,
                        atlas_size=args.atlas_size,
                        mask_threshold=args.mask_threshold,
                        style=args.style,
                        palette_size=args.palette_size,
                        colors_per_material=args.colors_per_material,
                    ),
                )
                result["reference"]["image"] = Path(
                    os.path.relpath(
                        reference_input.resolve(),
                        args.output.parent.resolve(),
                    )
                ).as_posix()
                errors = validate_spec(result, strict=True)
                if errors:
                    raise ValueError(
                        "texture bake produced an invalid specification:\n"
                        + "\n".join(f"- {error}" for error in errors)
                    )
                pack_faces(result)
            except (OSError, ValueError, ModuleNotFoundError) as exc:
                raise ModelSpecError(f"reference texture bake failed: {exc}") from exc
            write_json(args.output, result)
            evidence_path = args.audit or args.output.with_suffix(
                ".texture-evidence.json"
            )
            write_json(evidence_path, evidence)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "spec": str(args.output.resolve()),
                        "audit": str(evidence_path.resolve()),
                        "coverage": evidence["coverage"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command in {"preview-threejs", "threejs"}:
            spec = validated_spec(args.spec, strict=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(make_threejs_factory(spec), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "threejs": str(args.output.resolve()),
                        "cuboids": len(spec["cubes"]),
                    },
                    indent=2,
                )
            )
        elif args.command == "from-threejs":
            if not ID_RE.fullmatch(args.id):
                raise ModelSpecError("id must match [a-z0-9][a-z0-9_-]{0,63}")
            spec = import_threejs_scene(
                args.scene,
                args.reference,
                args.output,
                args.id,
                args.description,
            )
            write_json(args.output, spec)
            result: dict[str, Any] = {
                "ok": True,
                "spec": str(args.output.resolve()),
                "cuboids": len(spec["cubes"]),
            }
            if args.build_output:
                result["build"] = build_model(
                    args.output,
                    args.build_output,
                    reference_policy=args.reference_policy,
                )
            print(
                json.dumps(
                    result,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.command == "from-mesh":
            if not ID_RE.fullmatch(args.id):
                raise ModelSpecError("id must match [a-z0-9][a-z0-9_-]{0,63}")
            options = MeshReconstructionOptions(
                resolution=args.resolution,
                max_cuboids=args.max_cuboids,
                target_size=args.target_size,
                palette_size=args.palette_size,
                fill_mode=args.fill_mode,
                surface_thickness=args.surface_thickness,
                min_component_voxels=args.min_component_voxels,
                min_component_fraction=args.min_component_fraction,
                canonical_transform=(
                    tuple(args.canonical_transform)
                    if args.canonical_transform is not None
                    else None
                ),
                geometry_precision=args.geometry_precision,
                texture_density=args.texture_density,
                provider=args.provider,
                provider_model=args.provider_model,
                source_license=args.source_license,
            )
            try:
                spec, evidence = reconstruct_mesh_spec(
                    args.mesh,
                    args.output,
                    args.id,
                    args.description,
                    args.subject_type,
                    options,
                    args.reference,
                )
            except (OSError, ValueError) as exc:
                raise ModelSpecError(f"mesh reconstruction failed: {exc}") from exc
            errors = validate_spec(spec, strict=True)
            if errors:
                raise ModelSpecError(
                    "mesh reconstruction produced an invalid specification:\n"
                    + "\n".join(f"- {error}" for error in errors)
                )
            write_json(args.output, spec)
            evidence_path = args.evidence or args.output.with_suffix(
                ".mesh-evidence.json"
            )
            write_json(evidence_path, evidence)
            result: dict[str, Any] = {
                "ok": True,
                "spec": str(args.output.resolve()),
                "evidence": str(evidence_path.resolve()),
                "cuboids": len(spec["cubes"]),
                "source_mesh_overlap": evidence["source_mesh_overlap"],
                "multi_angle_review_manifest": str(
                    (
                        args.output.parent
                        / evidence["multi_angle_review"]["manifest"]
                    ).resolve()
                ),
            }
            if args.build_output:
                result["build"] = build_model(
                    args.output,
                    args.build_output,
                    reference_policy=args.reference_policy,
                )
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "from-views":
            if not ID_RE.fullmatch(args.id):
                raise ModelSpecError("id must match [a-z0-9][a-z0-9_-]{0,63}")
            options = ViewReconstructionOptions(
                resolution=args.resolution,
                max_cuboids=args.max_cuboids,
                target_size=args.target_size,
                palette_size=args.palette_size,
                mask_threshold=args.mask_threshold,
                min_component_voxels=args.min_component_voxels,
                min_component_fraction=args.min_component_fraction,
                geometry_precision=args.geometry_precision,
                texture_density=args.texture_density,
            )
            try:
                spec, evidence = reconstruct_view_spec(
                    args.manifest,
                    args.output,
                    args.id,
                    args.description,
                    args.subject_type,
                    options,
                )
            except (OSError, ValueError) as exc:
                raise ModelSpecError(f"multi-view reconstruction failed: {exc}") from exc
            errors = validate_spec(spec, strict=True)
            if errors:
                raise ModelSpecError(
                    "multi-view reconstruction produced an invalid specification:\n"
                    + "\n".join(f"- {error}" for error in errors)
                )
            write_json(args.output, spec)
            evidence_path = args.evidence or args.output.with_suffix(
                ".view-evidence.json"
            )
            write_json(evidence_path, evidence)
            result: dict[str, Any] = {
                "ok": True,
                "spec": str(args.output.resolve()),
                "evidence": str(evidence_path.resolve()),
                "cuboids": len(spec["cubes"]),
                "per_view_silhouette": evidence["per_view_silhouette"],
            }
            if args.build_output:
                result["build"] = build_model(
                    args.output,
                    args.build_output,
                    reference_policy=args.reference_policy,
                )
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "extract-clip-views":
            try:
                result = extract_clip_view_manifest(
                    args.clip,
                    args.samples,
                    args.output,
                    args.frames_dir,
                    args.ffmpeg,
                )
            except (OSError, ValueError) as exc:
                raise ModelSpecError(f"clip view extraction failed: {exc}") from exc
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "from-image":
            if not ID_RE.fullmatch(args.id):
                raise ModelSpecError("id must match [a-z0-9][a-z0-9_-]{0,63}")
            if not 16 <= args.analysis_size <= 512:
                raise ModelSpecError("analysis-size must be within 16..512")
            if not 12 <= args.grid_size <= 256:
                raise ModelSpecError("grid-size must be within 12..256")
            if not 1 <= args.max_cuboids <= 96:
                raise ModelSpecError("max-cuboids must be within 1..96")
            if args.target_size <= 0 or args.target_depth <= 0:
                raise ModelSpecError("target-size and target-depth must be positive")
            if not 1 <= args.relief_layers <= 6:
                raise ModelSpecError("relief-layers must be within 1..6")
            if args.geometry_precision is not None and not (
                1 <= args.geometry_precision <= 256
            ):
                raise ModelSpecError("geometry-precision must be within 1..256")
            if args.orientation_degrees is not None and not math.isfinite(
                args.orientation_degrees
            ):
                raise ModelSpecError("orientation-degrees must be finite")
            if not 0 < args.mask_coverage <= 1:
                raise ModelSpecError("mask-coverage must be within (0, 1]")
            options = PhotoReconstructionOptions(
                analysis_size=args.analysis_size,
                grid_size=args.grid_size,
                max_cuboids=args.max_cuboids,
                target_size=args.target_size,
                target_depth=args.target_depth,
                relief_layers=args.relief_layers,
                geometry_precision=args.geometry_precision,
                texture_density=args.texture_density,
                background_mode=args.background,
                foreground_mask=args.foreground_mask,
                subject_bbox=(
                    tuple(args.subject_bbox) if args.subject_bbox is not None else None
                ),
                depth_map=args.depth_map,
                depth_mode=args.depth_mode,
                decomposition=args.decomposition,
                orientation_degrees=args.orientation_degrees,
                mask_coverage=args.mask_coverage,
            )
            try:
                spec, segmentation = reconstruct_photo_spec(
                    args.image,
                    args.output,
                    args.id,
                    args.description,
                    args.subject_type,
                    options,
                )
            except (OSError, ValueError) as exc:
                raise ModelSpecError(f"image reconstruction failed: {exc}") from exc
            errors = validate_spec(spec, strict=True)
            if errors:
                raise ModelSpecError(
                    "image reconstruction produced an invalid specification:\n"
                    + "\n".join(f"- {error}" for error in errors)
                )
            write_json(args.output, spec)
            diagnostics = None
            if args.diagnostics:
                diagnostics = write_segmentation_diagnostics(
                    args.image,
                    segmentation,
                    args.diagnostics,
                )
            result: dict[str, Any] = {
                "ok": True,
                "spec": str(args.output.resolve()),
                "cuboids": len(spec["cubes"]),
                "segmentation": diagnostics,
            }
            if args.build_output:
                result["build"] = build_model(
                    args.output,
                    args.build_output,
                    reference_policy=args.reference_policy,
                )
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "render-relief":
            spec = validated_spec(args.spec, strict=True)
            reference = resolve_reference_path(args.spec, spec)
            texture, placements = build_texture(spec)
            try:
                result = render_relief_evidence(
                    spec,
                    reference,
                    texture,
                    placements,
                    args.output,
                )
            except ValueError as exc:
                raise ModelSpecError(f"relief rendering failed: {exc}") from exc
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "audit":
            report = audit_bbmodel(read_json(args.bbmodel))
            if args.output:
                write_json(args.output, report)
            print(json.dumps(report, indent=2, sort_keys=True))
            if not report["ok"]:
                return 1
        return 0
    except ModelSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
