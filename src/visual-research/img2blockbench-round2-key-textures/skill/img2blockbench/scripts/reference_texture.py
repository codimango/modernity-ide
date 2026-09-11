"""Deterministically bake calibrated reference views onto native cuboid faces."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    raise ModuleNotFoundError(
        "reference texture baking requires the optional 'reference-projection' "
        "extra: pip install 'img2blockbench[reference-projection]'"
    ) from exc
from PIL import Image

from img2blockbench import FACES, face_dimensions, hex_rgb, pack_faces
from semantic_evidence import (
    FACE_VERTICES,
    PerspectiveCamera,
    _clip_near_plane,
    cube_vertices,
)


ALGORITHM = "calibrated-perspective-visible-face-texture-bake-v1"
VIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReferenceTextureBakeOptions:
    """Configure an opt-in calibrated reference texture bake."""

    texture_density: int | None = None
    atlas_size: int | None = None
    mask_threshold: int = 128


@dataclass(frozen=True)
class _View:
    """One verified source image, foreground mask, and fixed camera."""

    view_id: str
    image_name: str
    image_sha256: str
    mask_name: str
    mask_sha256: str
    image: np.ndarray
    mask: np.ndarray
    camera: PerspectiveCamera


@dataclass(frozen=True)
class _Face:
    """One semantic cube face and its stable visibility-buffer identifier."""

    face_id: int
    cube: dict[str, Any]
    name: str
    vertices: np.ndarray


def _read_json(path: Path) -> tuple[Any, str]:
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except FileNotFoundError as exc:
        raise ValueError(f"view manifest not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in view manifest {path}: {exc}") from exc


def _required_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _resolve_manifest_input(manifest_path: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def _portable_input_name(value: str) -> str:
    """Keep relative provenance while avoiding machine-specific absolute paths."""
    path = Path(value)
    return path.name if path.is_absolute() else path.as_posix()


def _camera(value: Any, label: str) -> PerspectiveCamera:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if value.get("projection") != "perspective":
        raise ValueError(f"{label}.projection must be perspective")
    try:
        return PerspectiveCamera(
            image_size=tuple(value["image_size"]),
            focal_x=value["focal_x"],
            focal_y=value["focal_y"],
            principal_point=tuple(value["principal_point"]),
            world_to_camera=tuple(tuple(row) for row in value["world_to_camera"]),
            translation=tuple(value["translation"]),
            near=value.get("near", 0.1),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc


def _mask_pixels(image: Image.Image, threshold: int) -> np.ndarray:
    if "A" in image.getbands() and image.getchannel("A").getextrema()[0] < 255:
        values = np.asarray(image.getchannel("A"), dtype=np.uint8)
    else:
        values = np.asarray(image.convert("L"), dtype=np.uint8)
    return values >= threshold


def _load_views(
    manifest_path: Path,
    mask_threshold: int,
) -> tuple[list[_View], str]:
    manifest, manifest_sha256 = _read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("view manifest schema_version must be 1")
    records = manifest.get("views")
    if not isinstance(records, list) or not records:
        raise ValueError("view manifest views must be a non-empty array")

    views: list[_View] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        label = f"views[{index}]"
        if not isinstance(record, dict):
            raise ValueError(f"{label} must be an object")
        view_id = record.get("id")
        if not isinstance(view_id, str) or not VIEW_ID_RE.fullmatch(view_id):
            raise ValueError(f"{label}.id is invalid")
        if view_id in seen:
            raise ValueError(f"duplicate view id: {view_id}")
        seen.add(view_id)

        image_path = _resolve_manifest_input(manifest_path, record.get("image"), f"{label}.image")
        mask_path = _resolve_manifest_input(manifest_path, record.get("mask"), f"{label}.mask")
        image_sha256 = _required_sha(record.get("image_sha256"), f"{label}.image_sha256")
        mask_sha256 = _required_sha(record.get("mask_sha256"), f"{label}.mask_sha256")
        if not image_path.is_file():
            raise ValueError(f"{label}.image not found: {image_path}")
        if not mask_path.is_file():
            raise ValueError(f"{label}.mask not found: {mask_path}")
        image_raw = image_path.read_bytes()
        mask_raw = mask_path.read_bytes()
        if hashlib.sha256(image_raw).hexdigest() != image_sha256:
            raise ValueError(f"{label}.image SHA-256 mismatch")
        if hashlib.sha256(mask_raw).hexdigest() != mask_sha256:
            raise ValueError(f"{label}.mask SHA-256 mismatch")

        try:
            with Image.open(io.BytesIO(image_raw)) as opened:
                source = opened.convert("RGBA")
            with Image.open(io.BytesIO(mask_raw)) as opened:
                mask_image = opened.copy()
        except OSError as exc:
            raise ValueError(f"cannot read {label} image or mask: {exc}") from exc
        if source.size != mask_image.size:
            raise ValueError(f"{label} image and mask dimensions differ")
        camera = _camera(record.get("camera"), f"{label}.camera")
        if source.size != camera.image_size:
            raise ValueError(f"{label} camera image_size does not match source image")
        mask = _mask_pixels(mask_image, mask_threshold)
        if not mask.any():
            raise ValueError(f"{label} mask is empty")
        views.append(
            _View(
                view_id=view_id,
                image_name=_portable_input_name(str(record["image"])),
                image_sha256=image_sha256,
                mask_name=_portable_input_name(str(record["mask"])),
                mask_sha256=mask_sha256,
                image=np.asarray(source, dtype=np.uint8),
                mask=mask,
                camera=camera,
            )
        )
    return sorted(views, key=lambda view: view.view_id), manifest_sha256


def _faces(spec: dict[str, Any]) -> list[_Face]:
    records: list[_Face] = []
    for cube in sorted(spec["cubes"], key=lambda item: item["name"]):
        vertices = cube_vertices(spec, cube)
        for face_name in FACES:
            records.append(
                _Face(
                    face_id=len(records),
                    cube=cube,
                    name=face_name,
                    vertices=vertices[list(FACE_VERTICES[face_name])],
                )
            )
    return records


def _raster_visibility_triangle(
    owner: np.ndarray,
    zbuffer: np.ndarray,
    points: np.ndarray,
    depths: np.ndarray,
    face_id: int,
) -> None:
    minimum_x = max(0, math.floor(float(points[:, 0].min())))
    maximum_x = min(owner.shape[1] - 1, math.ceil(float(points[:, 0].max())))
    minimum_y = max(0, math.floor(float(points[:, 1].min())))
    maximum_y = min(owner.shape[0] - 1, math.ceil(float(points[:, 1].max())))
    if maximum_x < minimum_x or maximum_y < minimum_y:
        return
    denominator = (
        (points[1, 1] - points[2, 1]) * (points[0, 0] - points[2, 0])
        + (points[2, 0] - points[1, 0]) * (points[0, 1] - points[2, 1])
    )
    if abs(float(denominator)) < 1e-9:
        return
    grid_x, grid_y = np.meshgrid(
        np.arange(minimum_x, maximum_x + 1, dtype=np.float64) + 0.5,
        np.arange(minimum_y, maximum_y + 1, dtype=np.float64) + 0.5,
    )
    weight_a = (
        (points[1, 1] - points[2, 1]) * (grid_x - points[2, 0])
        + (points[2, 0] - points[1, 0]) * (grid_y - points[2, 1])
    ) / denominator
    weight_b = (
        (points[2, 1] - points[0, 1]) * (grid_x - points[2, 0])
        + (points[0, 0] - points[2, 0]) * (grid_y - points[2, 1])
    ) / denominator
    weight_c = 1.0 - weight_a - weight_b
    inverse_depth = (
        weight_a / depths[0]
        + weight_b / depths[1]
        + weight_c / depths[2]
    )
    valid = (
        (weight_a >= -1e-7)
        & (weight_b >= -1e-7)
        & (weight_c >= -1e-7)
        & np.isfinite(inverse_depth)
        & (inverse_depth > 0)
    )
    if not valid.any():
        return
    depth = np.full(inverse_depth.shape, np.inf, dtype=np.float64)
    depth[valid] = 1.0 / inverse_depth[valid]
    target_depth = zbuffer[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    visible = valid & (depth < target_depth - 1e-9)
    if not visible.any():
        return
    target_owner = owner[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    target_depth[visible] = depth[visible]
    target_owner[visible] = face_id


def _visibility_buffer(faces: list[_Face], camera: PerspectiveCamera) -> np.ndarray:
    width, height = camera.image_size
    owner = np.full((height, width), -1, dtype=np.int32)
    zbuffer = np.full((height, width), np.inf, dtype=np.float64)
    rotation = np.asarray(camera.world_to_camera, dtype=np.float64)
    translation = np.asarray(camera.translation, dtype=np.float64)

    for face in faces:
        camera_vertices = face.vertices @ rotation.T + translation
        camera_normal = np.cross(
            camera_vertices[1] - camera_vertices[0],
            camera_vertices[2] - camera_vertices[0],
        )
        length = float(np.linalg.norm(camera_normal))
        if length <= 1e-12:
            continue
        camera_normal /= length
        if float(np.dot(camera_normal, -camera_vertices.mean(axis=0))) <= 1e-9:
            continue
        for triangle in ((0, 1, 2), (0, 2, 3)):
            triangle_vertices = camera_vertices[list(triangle)]
            clipped, _ = _clip_near_plane(
                triangle_vertices,
                np.zeros((3, 2), dtype=np.float64),
                camera.near,
            )
            for index in range(1, len(clipped) - 1):
                vertices = clipped[[0, index, index + 1]]
                depths = -vertices[:, 2]
                with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                    screen = np.column_stack(
                        (
                            camera.focal_x * vertices[:, 0] / depths
                            + camera.principal_point[0],
                            camera.principal_point[1]
                            - camera.focal_y * vertices[:, 1] / depths,
                        )
                    )
                if np.all(np.isfinite(screen)):
                    _raster_visibility_triangle(
                        owner,
                        zbuffer,
                        screen,
                        depths,
                        face.face_id,
                    )
    return owner


def _face_world_points(
    face: _Face,
    width: int,
    height: int,
) -> np.ndarray:
    override = face.cube.get("faces", {}).get(face.name, {})
    flip_x = (face.name in {"east", "north"}) ^ bool(override.get("flip_x", False))
    flip_y = bool(override.get("flip_y", False))
    horizontal = (np.arange(width, dtype=np.float64) + 0.5) / width
    vertical = (np.arange(height, dtype=np.float64) + 0.5) / height
    if flip_x:
        horizontal = 1.0 - horizontal
    if flip_y:
        vertical = 1.0 - vertical
    horizontal_grid, vertical_grid = np.meshgrid(horizontal, vertical)
    left = horizontal_grid[:, :, None]
    top = vertical_grid[:, :, None]
    bottom_left, bottom_right, top_right, top_left = face.vertices
    return (
        (1.0 - left) * (1.0 - top) * top_left
        + left * (1.0 - top) * top_right
        + left * top * bottom_right
        + (1.0 - left) * top * bottom_left
    )


def _face_view_score(face: _Face, camera: PerspectiveCamera) -> float:
    rotation = np.asarray(camera.world_to_camera, dtype=np.float64)
    translation = np.asarray(camera.translation, dtype=np.float64)
    camera_vertices = face.vertices @ rotation.T + translation
    normal = np.cross(
        camera_vertices[1] - camera_vertices[0],
        camera_vertices[2] - camera_vertices[0],
    )
    normal_length = float(np.linalg.norm(normal))
    direction = -camera_vertices.mean(axis=0)
    direction_length = float(np.linalg.norm(direction))
    if normal_length <= 1e-12 or direction_length <= 1e-12:
        return -1.0
    return float(np.dot(normal / normal_length, direction / direction_length))


def _project_points(camera: PerspectiveCamera, points: np.ndarray) -> tuple[np.ndarray, ...]:
    rotation = np.asarray(camera.world_to_camera, dtype=np.float64)
    translation = np.asarray(camera.translation, dtype=np.float64)
    camera_points = points @ rotation.T + translation
    depths = -camera_points[:, 2]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        pixel_x = camera.focal_x * camera_points[:, 0] / depths + camera.principal_point[0]
        pixel_y = camera.principal_point[1] - camera.focal_y * camera_points[:, 1] / depths
    width, height = camera.image_size
    valid = (
        np.isfinite(pixel_x)
        & np.isfinite(pixel_y)
        & (depths >= camera.near)
        & (pixel_x >= 0)
        & (pixel_x < width)
        & (pixel_y >= 0)
        & (pixel_y < height)
    )
    sample_x = np.zeros(len(points), dtype=np.int64)
    sample_y = np.zeros(len(points), dtype=np.int64)
    sample_x[valid] = np.floor(pixel_x[valid]).astype(np.int64)
    sample_y[valid] = np.floor(pixel_y[valid]).astype(np.int64)
    return valid, sample_x, sample_y


def _png_data_uri(pixels: np.ndarray) -> str:
    output = io.BytesIO()
    Image.fromarray(pixels, mode="RGBA").save(
        output,
        format="PNG",
        optimize=False,
        compress_level=9,
    )
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _source_texture(pixels: np.ndarray) -> dict[str, Any]:
    return {
        "data_uri": _png_data_uri(pixels),
        "repeat": [1, 1],
        "offset": [0, 0],
        "center": [0, 0],
        "rotation": 0,
        "wrap": [1001, 1001],
        "flip_y": False,
    }


def _validate_options(options: ReferenceTextureBakeOptions) -> None:
    if options.texture_density is not None and (
        isinstance(options.texture_density, bool)
        or not isinstance(options.texture_density, int)
        or options.texture_density not in {1, 2, 4}
    ):
        raise ValueError("texture_density must be 1, 2, or 4")
    if options.atlas_size is not None and (
        isinstance(options.atlas_size, bool)
        or not isinstance(options.atlas_size, int)
        or options.atlas_size
        not in {16, 32, 64, 128, 256, 512, 1024, 2048}
    ):
        raise ValueError("atlas_size must be a power of two from 16..2048")
    if (
        isinstance(options.mask_threshold, bool)
        or not isinstance(options.mask_threshold, int)
        or not 1 <= options.mask_threshold <= 255
    ):
        raise ValueError("mask_threshold must be within 1..255")


def bake_reference_textures(
    spec: dict[str, Any],
    manifest_path: Path,
    options: ReferenceTextureBakeOptions = ReferenceTextureBakeOptions(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bake verified, unoccluded source pixels into embedded per-face patches."""
    _validate_options(options)
    output = json.loads(json.dumps(spec))
    if options.texture_density is not None:
        output["texture"]["density"] = options.texture_density
    if options.atlas_size is not None:
        output["texture"]["atlas_size"] = options.atlas_size
    output["texture"]["quantize_source"] = False

    views, manifest_sha256 = _load_views(manifest_path, options.mask_threshold)
    faces = _faces(output)
    owners = {
        view.view_id: _visibility_buffer(faces, view.camera)
        for view in views
    }
    cube_by_name = {cube["name"]: cube for cube in output["cubes"]}
    per_view_counts: Counter[str] = Counter()
    per_face: list[dict[str, Any]] = []
    total_texels = 0
    source_texels = 0

    for face in faces:
        cube = cube_by_name[face.cube["name"]]
        width, height = face_dimensions(output, cube, face.name)
        points = _face_world_points(face, width, height).reshape(-1, 3)
        material_name = cube.get("faces", {}).get(face.name, {}).get(
            "material", cube["material"]
        )
        fallback = np.asarray(
            (*hex_rgb(output["materials"][material_name]["base"]), 255),
            dtype=np.uint8,
        )
        patch = np.tile(fallback, (len(points), 1))
        best_score = np.full(len(points), -np.inf, dtype=np.float64)
        winner = np.full(len(points), -1, dtype=np.int32)

        for view_index, view in enumerate(views):
            score = _face_view_score(face, view.camera)
            if score <= 1e-9:
                continue
            valid, sample_x, sample_y = _project_points(view.camera, points)
            indexes = np.flatnonzero(valid)
            if not len(indexes):
                continue
            pixel_x = sample_x[indexes]
            pixel_y = sample_y[indexes]
            visible = owners[view.view_id][pixel_y, pixel_x] == face.face_id
            visible &= view.mask[pixel_y, pixel_x]
            visible &= view.image[pixel_y, pixel_x, 3] >= 16
            indexes = indexes[visible]
            if not len(indexes):
                continue
            replace = score > best_score[indexes] + 1e-12
            indexes = indexes[replace]
            if not len(indexes):
                continue
            patch[indexes] = view.image[sample_y[indexes], sample_x[indexes]]
            best_score[indexes] = score
            winner[indexes] = view_index

        observed = winner >= 0
        observed_count = int(observed.sum())
        face_texels = width * height
        source_texels += observed_count
        total_texels += face_texels
        winner_counts = Counter(int(value) for value in winner[observed])
        for view_index, count in winner_counts.items():
            per_view_counts[views[view_index].view_id] += count

        face_override = cube.setdefault("faces", {}).setdefault(face.name, {})
        face_override.pop("source_region", None)
        face_override["source_texture"] = _source_texture(
            patch.reshape(height, width, 4)
        )
        per_face.append(
            {
                "cube": cube["name"],
                "face": face.name,
                "size": [width, height],
                "source_texels": observed_count,
                "fallback_texels": face_texels - observed_count,
                "source_fraction": round(observed_count / face_texels, 6),
                "source_views": {
                    views[index].view_id: count
                    for index, count in sorted(winner_counts.items())
                },
            }
        )

    fallback_texels = total_texels - source_texels
    if source_texels == 0:
        raise ValueError(
            "no source texels passed the camera, foreground-mask, and occlusion checks"
        )
    resolved_atlas_size, _ = pack_faces(output)
    transfer = {
        "algorithm": ALGORITHM,
        "manifest_sha256": manifest_sha256,
        "mask_threshold": options.mask_threshold,
        "texture": {
            "density": output["texture"]["density"],
            "minimum_atlas_size": output["texture"]["atlas_size"],
            "resolved_atlas_size": resolved_atlas_size,
        },
        "view_tie_break": "highest face-incidence cosine, then lexicographic view id",
        "visibility": "frontmost cuboid face in fixed-camera z-buffer and foreground mask",
        "unobserved_policy": "solid effective material base; no hidden texture inferred",
        "palette_quantization": False,
        "views": [
            {
                "id": view.view_id,
                "image": view.image_name,
                "image_sha256": view.image_sha256,
                "mask": view.mask_name,
                "mask_sha256": view.mask_sha256,
                "camera": view.camera.as_dict(),
                "selected_source_texels": per_view_counts[view.view_id],
            }
            for view in views
        ],
        "coverage": {
            "total_face_texels": total_texels,
            "source_texels": source_texels,
            "fallback_texels": fallback_texels,
            "source_fraction": round(source_texels / max(1, total_texels), 6),
            "faces_with_source": sum(record["source_texels"] > 0 for record in per_face),
            "fallback_only_faces": sum(record["source_texels"] == 0 for record in per_face),
            "total_faces": len(per_face),
        },
        "faces": per_face,
    }
    output.setdefault("generation", {})["texture_transfer"] = transfer
    return output, transfer
