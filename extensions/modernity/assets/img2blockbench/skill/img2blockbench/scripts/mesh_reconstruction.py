#!/usr/bin/env python3
"""Deterministic ray-voxel reconstruction for textured triangle meshes."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from model_provenance import MODEL_CONTENT_HASH_METHOD, model_content_sha256


@dataclass(frozen=True)
class _CanonicalView:
    """Describe one deterministic orthographic mesh-review camera."""

    name: str
    axis: int
    positive_side: bool
    horizontal_axis: int
    horizontal_sign: int
    vertical_axis: int
    vertical_sign: int
    look_direction: tuple[int, int, int]
    up_direction: tuple[int, int, int]


_CANONICAL_VIEWS = (
    _CanonicalView("front", 2, True, 0, 1, 1, 1, (0, 0, -1), (0, 1, 0)),
    _CanonicalView("back", 2, False, 0, -1, 1, 1, (0, 0, 1), (0, 1, 0)),
    _CanonicalView("left", 0, False, 2, 1, 1, 1, (1, 0, 0), (0, 1, 0)),
    _CanonicalView("right", 0, True, 2, -1, 1, 1, (-1, 0, 0), (0, 1, 0)),
    _CanonicalView("top", 1, True, 0, 1, 2, -1, (0, -1, 0), (0, 0, -1)),
    _CanonicalView("bottom", 1, False, 0, 1, 2, 1, (0, 1, 0), (0, 0, 1)),
)
_AXIS_NAMES = ("x", "y", "z")
_MIN_MODEL_VOXEL_PRECISION = 0.25
_MIN_AXIS_SILHOUETTE_PRECISION = 0.5
_MIN_AXIS_DEPTH_ENVELOPE_PRECISION = 0.35
_MAX_AXIS_DEPTH_ENVELOPE_INFLATION = 3.0


@dataclass(frozen=True)
class MeshReconstructionOptions:
    """Control orthographic ray sampling and adaptive cuboid fitting."""

    resolution: int = 28
    max_cuboids: int = 72
    target_size: float = 32.0
    palette_size: int = 16
    fill_mode: str = "auto"
    surface_thickness: int = 1
    min_component_voxels: int = 2
    min_component_fraction: float = 0.001
    canonical_transform: tuple[float, ...] | None = None
    geometry_precision: int = 64
    texture_density: int = 1
    provider: str = "user-supplied"
    provider_model: str = "unrecorded"
    source_license: str = "unrecorded"


@dataclass
class _MeshData:
    vertices: Any
    faces: Any
    triangle_uv: Any
    triangle_texture: Any
    triangle_vertex_colors: Any
    triangle_flat_colors: Any
    texture_factors: Any
    textures: list[Any]
    geometry_count: int
    vertex_count: int
    face_count: int
    watertight: bool
    color_sources: tuple[str, ...]


@dataclass
class _VoxelData:
    occupancy: Any
    raw_surface: Any
    colors: Any
    component_labels: Any
    lower: Any
    pitch: float
    report: dict[str, Any]


@dataclass
class _Leaf:
    component: int
    serial: int
    coordinates: Any
    lower: Any
    upper: Any
    material: int
    cost: float


def _numpy() -> Any:
    """Import the shared voxel dependency without requiring mesh support."""
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            "voxel reconstruction requires numpy; install "
            "img2blockbench[multi-view] or img2blockbench[mesh-reconstruction]"
        ) from exc
    return np


def _trimesh() -> Any:
    """Import trimesh only while loading a triangle-mesh input."""
    try:
        import trimesh
    except ImportError as exc:
        raise ValueError(
            "mesh reconstruction requires trimesh; install "
            "img2blockbench[mesh-reconstruction]"
        ) from exc
    return trimesh


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_path(path: Path, output_path: Path) -> str:
    try:
        return path.resolve().relative_to(output_path.parent.resolve()).as_posix()
    except ValueError:
        return Path(
            os.path.relpath(path.resolve(), output_path.parent.resolve())
        ).as_posix()


def _rgb_hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _adjusted_hex(color: tuple[int, int, int], factor: float) -> str:
    return _rgb_hex(
        tuple(max(0, min(255, round(value * factor))) for value in color)
    )


def _material_factor(material: Any) -> tuple[float, float, float]:
    value = getattr(material, "baseColorFactor", None)
    if value is None:
        value = getattr(material, "main_color", None)
    if value is None:
        return (1.0, 1.0, 1.0)
    channels = list(value)[:3]
    if not channels:
        return (1.0, 1.0, 1.0)
    divisor = 255.0 if max(float(channel) for channel in channels) > 1.0 else 1.0
    return tuple(float(channel) / divisor for channel in channels)


def _material_image(material: Any) -> Image.Image | None:
    for attribute in ("baseColorTexture", "image"):
        image = getattr(material, attribute, None)
        if isinstance(image, Image.Image):
            return image.convert("RGB")
    return None


def _fallback_color(visual: Any, material: Any) -> tuple[int, int, int]:
    for owner, attribute in (
        (material, "main_color"),
        (material, "baseColorFactor"),
        (visual, "main_color"),
    ):
        value = getattr(owner, attribute, None)
        if value is None:
            continue
        channels = [float(channel) for channel in list(value)[:3]]
        if len(channels) == 3:
            if max(channels) <= 1.0:
                channels = [channel * 255 for channel in channels]
            return tuple(max(0, min(255, round(channel))) for channel in channels)
    return (154, 154, 154)


def _load_mesh(path: Path, transform_values: tuple[float, ...] | None) -> _MeshData:
    np = _numpy()
    trimesh = _trimesh()
    if not path.is_file():
        raise ValueError(f"mesh not found: {path}")
    try:
        loaded = trimesh.load(path, force="scene", process=False)
    except Exception as exc:
        raise ValueError(f"cannot load mesh {path}: {exc}") from exc

    if transform_values is not None:
        if len(transform_values) != 16 or not all(
            math.isfinite(float(value)) for value in transform_values
        ):
            raise ValueError("canonical_transform must contain 16 finite numbers")
        canonical = np.asarray(transform_values, dtype=np.float64).reshape(4, 4)
    else:
        canonical = np.eye(4, dtype=np.float64)

    vertices: list[Any] = []
    faces: list[Any] = []
    triangle_uv: list[Any] = []
    triangle_texture: list[Any] = []
    triangle_vertex_colors: list[Any] = []
    triangle_flat_colors: list[Any] = []
    texture_factors: list[Any] = []
    textures: list[Any] = []
    color_sources: set[str] = set()
    geometry_count = 0
    vertex_count = 0
    face_count = 0
    watertight = True

    nodes = sorted(loaded.graph.nodes_geometry, key=str)
    for node_name in nodes:
        node_transform, geometry_name = loaded.graph[node_name]
        geometry = loaded.geometry[geometry_name]
        if not isinstance(geometry, trimesh.Trimesh) or not len(geometry.faces):
            continue
        geometry_count += 1
        watertight = watertight and bool(geometry.is_watertight)
        points = trimesh.transform_points(
            np.asarray(geometry.vertices, dtype=np.float64),
            np.asarray(node_transform, dtype=np.float64),
        )
        points = trimesh.transform_points(points, canonical)
        geometry_faces = np.asarray(geometry.faces, dtype=np.int64)
        offset = sum(len(block) for block in vertices)
        vertices.append(points)
        faces.append(geometry_faces + offset)
        vertex_count += len(points)
        face_count += len(geometry_faces)

        visual = geometry.visual
        material = getattr(visual, "material", None)
        fallback = _fallback_color(visual, material)
        flat = np.tile(np.asarray(fallback, dtype=np.float64), (len(geometry_faces), 1))
        try:
            face_colors = getattr(visual, "face_colors", None)
            if face_colors is not None and len(face_colors) == len(geometry_faces):
                flat = np.asarray(face_colors, dtype=np.float64)[:, :3]
                color_sources.add("face-color")
        except (AttributeError, TypeError, ValueError):
            pass

        uv = getattr(visual, "uv", None)
        has_uv = uv is not None and len(uv) == len(points)
        triangle_uv.append(
            np.asarray(uv, dtype=np.float64)[geometry_faces]
            if has_uv
            else np.full((len(geometry_faces), 3, 2), np.nan, dtype=np.float64)
        )
        face_texture_indexes = np.full(len(geometry_faces), -1, dtype=np.int32)
        face_texture_factors = np.ones((len(geometry_faces), 3), dtype=np.float64)
        material_list = getattr(material, "materials", None)
        face_materials = getattr(visual, "face_materials", None)
        if material_list is not None and face_materials is not None:
            material_entries = [
                (int(index), entry) for index, entry in enumerate(material_list)
            ]
            face_materials = np.asarray(face_materials, dtype=np.int64)
        else:
            material_entries = [(0, material)]
            face_materials = np.zeros(len(geometry_faces), dtype=np.int64)
        if has_uv:
            for material_index, material_entry in material_entries:
                texture_image = _material_image(material_entry)
                selected_faces = face_materials == material_index
                if texture_image is None or not selected_faces.any():
                    continue
                texture_index = len(textures)
                textures.append(np.asarray(texture_image, dtype=np.uint8)[:, :, :3])
                face_texture_indexes[selected_faces] = texture_index
                face_texture_factors[selected_faces] = np.asarray(
                    _material_factor(material_entry), dtype=np.float64
                )
                color_sources.add("uv-texture")
        triangle_texture.append(face_texture_indexes)
        texture_factors.append(face_texture_factors)

        vertex_colors = getattr(visual, "vertex_colors", None)
        if vertex_colors is not None and len(vertex_colors) == len(points):
            triangle_vertex_colors.append(
                np.asarray(vertex_colors, dtype=np.float64)[geometry_faces, :3]
            )
            color_sources.add("vertex-color")
        else:
            triangle_vertex_colors.append(
                np.full((len(geometry_faces), 3, 3), np.nan, dtype=np.float64)
            )
        triangle_flat_colors.append(flat)
        if (
            not (face_texture_indexes >= 0).any()
            and vertex_colors is None
            and not (getattr(visual, "kind", None) == "face")
        ):
            color_sources.add("material-color")

    if not vertices:
        raise ValueError(f"no triangle geometry found in {path}")
    all_vertices = np.concatenate(vertices)
    if not np.isfinite(all_vertices).all():
        raise ValueError("mesh contains non-finite vertices")
    extents = np.ptp(all_vertices, axis=0)
    if float(extents.max()) <= 1e-12:
        raise ValueError("mesh has zero spatial extent")
    return _MeshData(
        vertices=all_vertices,
        faces=np.concatenate(faces),
        triangle_uv=np.concatenate(triangle_uv),
        triangle_texture=np.concatenate(triangle_texture),
        triangle_vertex_colors=np.concatenate(triangle_vertex_colors),
        triangle_flat_colors=np.concatenate(triangle_flat_colors),
        texture_factors=np.concatenate(texture_factors),
        textures=textures,
        geometry_count=geometry_count,
        vertex_count=vertex_count,
        face_count=face_count,
        watertight=watertight,
        color_sources=tuple(sorted(color_sources)),
    )


def _hit_colors(mesh: _MeshData, face_indexes: Any, weights: Any) -> Any:
    np = _numpy()
    colors = mesh.triangle_flat_colors[face_indexes].astype(np.float64, copy=True)

    vertex_values = mesh.triangle_vertex_colors[face_indexes]
    vertex_valid = np.isfinite(vertex_values).all(axis=(1, 2))
    if vertex_valid.any():
        colors[vertex_valid] = np.einsum(
            "ni,nij->nj", weights[vertex_valid], vertex_values[vertex_valid]
        )

    texture_indexes = mesh.triangle_texture[face_indexes]
    for texture_index in sorted(set(int(value) for value in texture_indexes if value >= 0)):
        selected = texture_indexes == texture_index
        uvs = np.einsum(
            "ni,nij->nj",
            weights[selected],
            mesh.triangle_uv[face_indexes[selected]],
        )
        uvs = uvs - np.floor(uvs)
        image = mesh.textures[texture_index]
        x = np.clip(np.rint(uvs[:, 0] * (image.shape[1] - 1)), 0, image.shape[1] - 1)
        y = np.clip(
            np.rint((1.0 - uvs[:, 1]) * (image.shape[0] - 1)),
            0,
            image.shape[0] - 1,
        )
        sampled = image[y.astype(np.int64), x.astype(np.int64), :3].astype(np.float64)
        sampled *= mesh.texture_factors[face_indexes[selected]]
        colors[selected] = sampled
    return np.clip(np.rint(colors), 0, 255).astype(np.uint8)


def _six_neighbors(point: tuple[int, int, int], shape: tuple[int, int, int]):
    x, y, z = point
    for dx, dy, dz in (
        (-1, 0, 0),
        (1, 0, 0),
        (0, -1, 0),
        (0, 1, 0),
        (0, 0, -1),
        (0, 0, 1),
    ):
        neighbor = (x + dx, y + dy, z + dz)
        if all(0 <= neighbor[index] < shape[index] for index in range(3)):
            yield neighbor


def _components(occupancy: Any) -> list[list[tuple[int, int, int]]]:
    np = _numpy()
    visited = np.zeros(occupancy.shape, dtype=bool)
    output: list[list[tuple[int, int, int]]] = []
    for coordinate in np.argwhere(occupancy):
        start = tuple(int(value) for value in coordinate)
        if visited[start]:
            continue
        visited[start] = True
        queue = deque([start])
        component: list[tuple[int, int, int]] = []
        while queue:
            point = queue.popleft()
            component.append(point)
            for neighbor in _six_neighbors(point, occupancy.shape):
                if occupancy[neighbor] and not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)
        output.append(component)
    output.sort(key=lambda item: (-len(item), min(item)))
    return output


def _dilate_six(occupancy: Any, iterations: int) -> Any:
    output = occupancy.copy()
    for _ in range(iterations):
        source = output
        output = source.copy()
        output[1:, :, :] |= source[:-1, :, :]
        output[:-1, :, :] |= source[1:, :, :]
        output[:, 1:, :] |= source[:, :-1, :]
        output[:, :-1, :] |= source[:, 1:, :]
        output[:, :, 1:] |= source[:, :, :-1]
        output[:, :, :-1] |= source[:, :, 1:]
    return output


def _projection_depths(occupancy: Any, axis: int) -> tuple[Any, Any, Any, Any]:
    """Return projection mask and near/far depth envelopes for one axis."""
    np = _numpy()
    projected = occupancy.any(axis=axis)
    first = np.argmax(occupancy, axis=axis)
    last = occupancy.shape[axis] - 1 - np.argmax(
        np.flip(occupancy, axis=axis), axis=axis
    )
    spans = np.zeros(projected.shape, dtype=np.int64)
    spans[projected] = last[projected] - first[projected] + 1
    return projected, first, last, spans


def _ranked_percentile(values: Any, percentile: float) -> int:
    """Return a deterministic nearest-rank percentile for integer samples."""
    if not len(values):
        return 0
    ordered = sorted(int(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _occupancy_axis_profile(occupancy: Any, axis: int) -> dict[str, Any]:
    """Measure actual occupancy and depth-envelope thickness along one axis."""
    np = _numpy()
    coordinates = np.argwhere(occupancy)
    if not len(coordinates):
        return {
            "axis": _AXIS_NAMES[axis],
            "axis_span_voxels": 0,
            "projected_pixels": 0,
            "occupied_voxels": 0,
            "grid_occupancy_fraction": 0.0,
            "bounding_box_occupancy_fraction": 0.0,
            "mean_occupied_voxels_per_projected_ray": 0.0,
            "mean_depth_envelope_voxels": 0.0,
            "median_depth_envelope_voxels": 0,
            "p95_depth_envelope_voxels": 0,
            "maximum_depth_envelope_voxels": 0,
        }
    projected, _, _, spans = _projection_depths(occupancy, axis)
    occupied_per_ray = occupancy.sum(axis=axis)[projected]
    depth_spans = spans[projected]
    bounds_minimum = coordinates.min(axis=0)
    bounds_maximum = coordinates.max(axis=0)
    bounding_volume = int(np.prod(bounds_maximum - bounds_minimum + 1))
    return {
        "axis": _AXIS_NAMES[axis],
        "axis_span_voxels": int(
            bounds_maximum[axis] - bounds_minimum[axis] + 1
        ),
        "projected_pixels": int(projected.sum()),
        "occupied_voxels": int(occupancy.sum()),
        "grid_occupancy_fraction": round(
            float(occupancy.mean()), 6
        ),
        "bounding_box_occupancy_fraction": round(
            int(occupancy.sum()) / max(1, bounding_volume), 6
        ),
        "mean_occupied_voxels_per_projected_ray": round(
            float(occupied_per_ray.mean()), 6
        ),
        "mean_depth_envelope_voxels": round(float(depth_spans.mean()), 6),
        "median_depth_envelope_voxels": _ranked_percentile(depth_spans, 0.5),
        "p95_depth_envelope_voxels": _ranked_percentile(depth_spans, 0.95),
        "maximum_depth_envelope_voxels": int(depth_spans.max()),
    }


def _directional_ray_evidence(
    axis_surfaces: list[Any],
    intersection_counts: list[int],
    odd_parity_counts: list[int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Summarize the six signed views represented by three shared ray grids."""
    axes: dict[str, Any] = {}
    for axis, surface in enumerate(axis_surfaces):
        projected, _, _, spans = _projection_depths(surface, axis)
        depth_spans = spans[projected]
        ray_count = int(projected.size)
        hit_rays = int(projected.sum())
        axes[_AXIS_NAMES[axis]] = {
            "ray_grid": [
                int(surface.shape[index]) for index in range(3) if index != axis
            ],
            "rays_cast": ray_count,
            "rays_with_hits": hit_rays,
            "ray_hit_fraction": round(hit_rays / max(1, ray_count), 6),
            "triangle_intersections": intersection_counts[axis],
            "unique_surface_voxels": int(surface.sum()),
            "rays_with_opposed_surfaces": int((depth_spans > 1).sum()),
            "opposed_surface_fraction": round(
                float((depth_spans > 1).sum()) / max(1, hit_rays), 6
            ),
            "mean_surface_depth_span_voxels": round(
                float(depth_spans.mean()) if len(depth_spans) else 0.0, 6
            ),
            "p95_surface_depth_span_voxels": _ranked_percentile(
                depth_spans, 0.95
            ),
            "odd_parity_rays": odd_parity_counts[axis],
        }

    directions: dict[str, Any] = {}
    for view in _CANONICAL_VIEWS:
        axis_evidence = axes[_AXIS_NAMES[view.axis]]
        projected, first, last, _ = _projection_depths(
            axis_surfaces[view.axis], view.axis
        )
        visible_depths = last[projected] if view.positive_side else first[projected]
        if view.positive_side:
            camera_distances = (
                axis_surfaces[view.axis].shape[view.axis] - 1 - visible_depths
            )
        else:
            camera_distances = visible_depths
        directions[view.name] = {
            "axis": _AXIS_NAMES[view.axis],
            "camera_side": "positive" if view.positive_side else "negative",
            "ray_direction": list(view.look_direction),
            "rays_cast": axis_evidence["rays_cast"],
            "rays_with_hits": axis_evidence["rays_with_hits"],
            "visible_surface_voxels": axis_evidence["rays_with_hits"],
            "triangle_intersections": axis_evidence["triangle_intersections"],
            "mean_visible_depth_index": round(
                float(visible_depths.mean()) if len(visible_depths) else 0.0, 6
            ),
            "mean_camera_surface_distance_voxels": round(
                float(camera_distances.mean()) if len(camera_distances) else 0.0,
                6,
            ),
            "opposed_surface_fraction": axis_evidence[
                "opposed_surface_fraction"
            ],
        }
    return axes, directions


def _voxelize(mesh: _MeshData, options: MeshReconstructionOptions) -> _VoxelData:
    np = _numpy()
    vertices = mesh.vertices
    triangles = vertices[mesh.faces]
    source_minimum = vertices.min(axis=0)
    extents = np.ptp(vertices, axis=0)
    pitch = float(extents.max()) / options.resolution
    source_lower = source_minimum - pitch / 2
    dimensions = np.maximum(
        1,
        np.ceil(extents / pitch - 1e-12).astype(np.int64) + 1,
    )
    shape = tuple(int(value) for value in dimensions)
    surface = np.zeros(shape, dtype=bool)
    axis_surfaces = [np.zeros(shape, dtype=bool) for _ in range(3)]
    inside_votes = np.zeros(shape, dtype=np.uint8)
    color_sums = np.zeros(shape + (3,), dtype=np.float64)
    color_counts = np.zeros(shape, dtype=np.uint32)
    ray_count = 0
    intersection_count = 0
    intersection_counts = [0, 0, 0]
    odd_parity_rays = 0
    odd_parity_counts = [0, 0, 0]
    solid = options.fill_mode == "solid" or (
        options.fill_mode == "auto" and mesh.watertight
    )

    for axis in range(3):
        plane_axes = tuple(index for index in range(3) if index != axis)
        first, second = plane_axes
        grid_first, grid_second = np.meshgrid(
            np.arange(shape[first]),
            np.arange(shape[second]),
            indexing="ij",
        )
        rays = np.column_stack(
            (
                source_lower[first] + (grid_first.ravel() + 0.5) * pitch,
                source_lower[second] + (grid_second.ravel() + 0.5) * pitch,
            )
        )
        ray_count += len(rays)
        projected = triangles[:, :, (first, second)]
        a = projected[:, 0]
        b = projected[:, 1]
        c = projected[:, 2]
        denominator = (
            (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0])
            + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        )
        valid_triangle = np.abs(denominator) > max(1e-15, pitch * pitch * 1e-12)
        safe_denominator = np.where(valid_triangle, denominator, 1.0)

        for batch_start in range(0, len(rays), 64):
            batch = rays[batch_start : batch_start + 64]
            point_x = batch[:, None, 0]
            point_y = batch[:, None, 1]
            weight_a = (
                (b[None, :, 1] - c[None, :, 1])
                * (point_x - c[None, :, 0])
                + (c[None, :, 0] - b[None, :, 0])
                * (point_y - c[None, :, 1])
            ) / safe_denominator[None, :]
            weight_b = (
                (c[None, :, 1] - a[None, :, 1])
                * (point_x - c[None, :, 0])
                + (a[None, :, 0] - c[None, :, 0])
                * (point_y - c[None, :, 1])
            ) / safe_denominator[None, :]
            weight_c = 1.0 - weight_a - weight_b
            hit = (
                valid_triangle[None, :]
                & (weight_a >= -1e-9)
                & (weight_b >= -1e-9)
                & (weight_c >= -1e-9)
            )
            ray_local, face_indexes = np.nonzero(hit)
            if not len(face_indexes):
                continue
            weights = np.column_stack(
                (
                    weight_a[ray_local, face_indexes],
                    weight_b[ray_local, face_indexes],
                    weight_c[ray_local, face_indexes],
                )
            )
            depths = np.einsum(
                "ni,ni->n", weights, triangles[face_indexes, :, axis]
            )
            depth_cells = np.clip(
                np.floor((depths - source_lower[axis]) / pitch).astype(np.int64),
                0,
                shape[axis] - 1,
            )
            ray_indexes = batch_start + ray_local
            coordinate_first = grid_first.ravel()[ray_indexes]
            coordinate_second = grid_second.ravel()[ray_indexes]
            coordinates = np.empty((len(face_indexes), 3), dtype=np.int64)
            coordinates[:, axis] = depth_cells
            coordinates[:, first] = coordinate_first
            coordinates[:, second] = coordinate_second
            surface[tuple(coordinates.T)] = True
            axis_surfaces[axis][tuple(coordinates.T)] = True
            colors = _hit_colors(mesh, face_indexes, weights)
            np.add.at(color_sums, tuple(coordinates.T), colors)
            np.add.at(color_counts, tuple(coordinates.T), 1)
            intersection_count += len(face_indexes)
            intersection_counts[axis] += len(face_indexes)

            if solid:
                for local_index in range(len(batch)):
                    selected = ray_local == local_index
                    if not selected.any():
                        continue
                    ordered = sorted(float(value) for value in depths[selected])
                    unique: list[float] = []
                    for value in ordered:
                        if not unique or abs(value - unique[-1]) > pitch * 1e-5:
                            unique.append(value)
                    if len(unique) % 2:
                        odd_parity_rays += 1
                        odd_parity_counts[axis] += 1
                        unique = unique[:-1]
                    global_ray = batch_start + local_index
                    fixed_first = int(grid_first.ravel()[global_ray])
                    fixed_second = int(grid_second.ravel()[global_ray])
                    for pair in range(0, len(unique), 2):
                        minimum = max(
                            0,
                            math.ceil(
                                (unique[pair] - source_lower[axis]) / pitch - 0.5
                            ),
                        )
                        maximum = min(
                            shape[axis],
                            math.floor(
                                (unique[pair + 1] - source_lower[axis]) / pitch - 0.5
                            )
                            + 1,
                        )
                        for depth_index in range(minimum, maximum):
                            point = [0, 0, 0]
                            point[axis] = depth_index
                            point[first] = fixed_first
                            point[second] = fixed_second
                            inside_votes[tuple(point)] += 1

    occupancy = surface | (inside_votes >= 2 if solid else False)
    if not solid and options.surface_thickness > 1:
        occupancy = _dilate_six(occupancy, options.surface_thickness - 1)

    raw_voxels = int(occupancy.sum())
    raw_components = _components(occupancy)
    threshold = max(
        options.min_component_voxels,
        math.ceil(raw_voxels * options.min_component_fraction),
    )
    retained = [component for component in raw_components if len(component) >= threshold]
    if not retained and raw_components:
        retained = [raw_components[0]]
    if len(retained) > options.max_cuboids:
        raise ValueError(
            f"{len(retained)} retained connected components exceed the "
            f"max_cuboids budget of {options.max_cuboids}; increase --max-cuboids "
            "rather than dropping source parts"
        )
    cleaned = np.zeros(shape, dtype=bool)
    component_labels = np.full(shape, -1, dtype=np.int32)
    for component_index, component in enumerate(retained):
        for point in component:
            cleaned[point] = True
            component_labels[point] = component_index
    if not cleaned.any():
        raise ValueError("orthographic rays did not retain any mesh surface voxels")

    colors = np.zeros(shape + (3,), dtype=np.uint8)
    colored = color_counts > 0
    colors[colored] = np.clip(
        np.rint(color_sums[colored] / color_counts[colored, None]),
        0,
        255,
    ).astype(np.uint8)
    queue: deque[tuple[int, int, int]] = deque(
        tuple(int(value) for value in point)
        for point in np.argwhere(cleaned & colored)
    )
    assigned = cleaned & colored
    if not queue:
        seed = tuple(int(value) for value in np.argwhere(cleaned)[0])
        colors[seed] = (154, 154, 154)
        assigned[seed] = True
        queue.append(seed)
    while queue:
        point = queue.popleft()
        for neighbor in _six_neighbors(point, shape):
            if cleaned[neighbor] and not assigned[neighbor]:
                colors[neighbor] = colors[point]
                assigned[neighbor] = True
                queue.append(neighbor)

    axis_ray_evidence, direction_ray_evidence = _directional_ray_evidence(
        axis_surfaces, intersection_counts, odd_parity_counts
    )
    component_details = []
    for component_index, component in enumerate(retained, start=1):
        component_coordinates = np.asarray(component, dtype=np.int64)
        minimum = component_coordinates.min(axis=0)
        maximum = component_coordinates.max(axis=0)
        component_details.append(
            {
                "component": component_index,
                "voxels": len(component),
                "minimum": [int(value) for value in minimum],
                "maximum": [int(value) for value in maximum],
                "spans": [
                    int(maximum[index] - minimum[index] + 1)
                    for index in range(3)
                ],
            }
        )
    report = {
        "grid_dimensions": list(shape),
        "voxel_pitch_source_units": round(pitch, 9),
        "fill_mode_requested": options.fill_mode,
        "fill_mode_resolved": "solid" if solid else "surface",
        "surface_thickness_voxels": options.surface_thickness,
        "ray_evidence": {
            "method": (
                "six signed orthographic surface views evaluated on three shared "
                "axis ray grids"
            ),
            "direction_count": 6,
            "bidirectional_rays": ray_count * 2,
            "unique_direction_rays": ray_count,
            "triangle_intersections": intersection_count,
            "surface_voxels": int(surface.sum()),
            "odd_parity_rays": odd_parity_rays,
            "axes": axis_ray_evidence,
            "directions": direction_ray_evidence,
        },
        "components": {
            "connectivity": 6,
            "before_cleanup": len(raw_components),
            "after_cleanup": len(retained),
            "minimum_voxels": threshold,
            "raw_voxels": raw_voxels,
            "retained_voxels": int(cleaned.sum()),
            "removed_voxels": raw_voxels - int(cleaned.sum()),
            "sizes": [len(component) for component in retained],
            "details": component_details,
            "budget_policy": "fail rather than drop a retained component",
        },
        "axis_profiles": {
            _AXIS_NAMES[axis]: _occupancy_axis_profile(cleaned, axis)
            for axis in range(3)
        },
    }
    return _VoxelData(
        occupancy=cleaned,
        raw_surface=surface,
        colors=colors,
        component_labels=component_labels,
        lower=source_lower,
        pitch=pitch,
        report=report,
    )


def _palette(colors: Any, occupancy: Any, maximum: int) -> tuple[list[tuple[int, int, int]], Any]:
    np = _numpy()
    selected = colors[occupancy].astype(np.int32)
    buckets: dict[tuple[int, int, int], list[Any]] = {}
    for color in selected:
        key = tuple(int(value // 16) for value in color)
        if key not in buckets:
            buckets[key] = [0, np.zeros(3, dtype=np.int64)]
        buckets[key][0] += 1
        buckets[key][1] += color
    ranked = sorted(buckets.items(), key=lambda item: (-item[1][0], item[0]))[:maximum]
    palette = [
        tuple(int(round(value / count)) for value in total)
        for _, (count, total) in ranked
    ]
    if not palette:
        palette = [(154, 154, 154)]
    palette_array = np.asarray(palette, dtype=np.int32)
    labels = np.full(occupancy.shape, -1, dtype=np.int16)
    difference = selected[:, None, :] - palette_array[None, :, :]
    assigned = np.argmin(np.sum(difference * difference, axis=2), axis=1)
    labels[occupancy] = assigned
    return palette, labels


def _make_leaf(component: int, serial: int, coordinates: Any, labels: Any) -> _Leaf:
    np = _numpy()
    lower = coordinates.min(axis=0)
    upper = coordinates.max(axis=0) + 1
    material_counts = Counter(int(labels[tuple(point)]) for point in coordinates)
    material, dominant_count = min(
        material_counts.items(), key=lambda item: (-item[1], item[0])
    )
    volume = int(np.prod(upper - lower))
    empty_error = volume - len(coordinates)
    color_error = len(coordinates) - dominant_count
    return _Leaf(
        component=component,
        serial=serial,
        coordinates=coordinates,
        lower=lower,
        upper=upper,
        material=material,
        cost=float(empty_error) + color_error * 0.45,
    )


def _best_split(leaf: _Leaf, labels: Any, serial: int) -> tuple[float, _Leaf, _Leaf] | None:
    best: tuple[tuple[float, int, int, int], _Leaf, _Leaf] | None = None
    for axis in range(3):
        for cut in range(int(leaf.lower[axis]) + 1, int(leaf.upper[axis])):
            selected = leaf.coordinates[:, axis] < cut
            if not selected.any() or selected.all():
                continue
            left = _make_leaf(
                leaf.component, serial, leaf.coordinates[selected], labels
            )
            right = _make_leaf(
                leaf.component, serial + 1, leaf.coordinates[~selected], labels
            )
            improvement = leaf.cost - left.cost - right.cost
            balance = min(len(left.coordinates), len(right.coordinates))
            key = (round(improvement, 12), balance, -axis, -cut)
            if best is None or key > best[0]:
                best = (key, left, right)
    if best is None or best[0][0] <= 1e-12:
        return None
    return float(best[0][0]), best[1], best[2]


def _axis_fit_metrics(source: Any, model: Any, axis: int) -> dict[str, Any]:
    """Compare model thickness to source thickness without penalizing thin sources."""
    np = _numpy()
    source_mask, source_first, source_last, source_spans = _projection_depths(
        source, axis
    )
    model_mask, model_first, model_last, model_spans = _projection_depths(model, axis)
    comparable = source_mask & model_mask
    overlap_spans = np.zeros(source_mask.shape, dtype=np.int64)
    overlap_spans[comparable] = np.maximum(
        0,
        np.minimum(source_last[comparable], model_last[comparable])
        - np.maximum(source_first[comparable], model_first[comparable])
        + 1,
    )
    source_profile = _occupancy_axis_profile(source, axis)
    model_profile = _occupancy_axis_profile(model, axis)
    source_axis_span = source_profile["axis_span_voxels"]
    model_axis_span = model_profile["axis_span_voxels"]
    source_depth_total = int(source_spans[source_mask].sum())
    model_depth_total = int(model_spans[model_mask].sum())
    projected_intersection = int(comparable.sum())
    collapsed = source_mask & (
        ~model_mask | (model_spans < source_spans)
    )
    if comparable.any():
        boundary_error = float(
            np.mean(
                (
                    np.abs(source_first[comparable] - model_first[comparable])
                    + np.abs(source_last[comparable] - model_last[comparable])
                )
                / 2
            )
        ) / max(1, source.shape[axis] - 1)
    else:
        boundary_error = 1.0
    return {
        "axis": _AXIS_NAMES[axis],
        "source": source_profile,
        "model": model_profile,
        "axis_span_preservation": round(
            min(1.0, model_axis_span / max(1, source_axis_span)), 6
        ),
        "source_depth_envelope_coverage": round(
            int(overlap_spans.sum()) / max(1, source_depth_total), 6
        ),
        "model_depth_envelope_precision": round(
            int(overlap_spans.sum()) / max(1, model_depth_total), 6
        ),
        "depth_envelope_inflation_ratio": round(
            model_depth_total / max(1, source_depth_total), 6
        ),
        "source_silhouette_coverage": round(
            projected_intersection / max(1, int(source_mask.sum())), 6
        ),
        "model_silhouette_precision": round(
            projected_intersection / max(1, int(model_mask.sum())), 6
        ),
        "collapsed_source_rays": int(collapsed.sum()),
        "collapsed_source_ray_fraction": round(
            int(collapsed.sum()) / max(1, int(source_mask.sum())), 6
        ),
        "bidirectional_boundary_mae": round(boundary_error, 6),
        "model_to_source_mean_depth_ratio": round(
            model_profile["mean_depth_envelope_voxels"]
            / max(1e-12, source_profile["mean_depth_envelope_voxels"]),
            6,
        ),
    }


def _adaptive_cuboids(
    voxels: _VoxelData,
    labels: Any,
    maximum: int,
) -> tuple[list[_Leaf], dict[str, Any], Any]:
    np = _numpy()
    leaves: list[_Leaf] = []
    serial = 0
    component_count = int(voxels.component_labels.max()) + 1
    for component in range(component_count):
        coordinates = np.argwhere(voxels.component_labels == component)
        leaves.append(_make_leaf(component, serial, coordinates, labels))
        serial += 1

    while len(leaves) < maximum:
        candidate: tuple[tuple[float, int, int], int, _Leaf, _Leaf] | None = None
        for index, leaf in enumerate(leaves):
            split = _best_split(leaf, labels, serial)
            if split is None:
                continue
            improvement, left, right = split
            key = (round(improvement, 12), len(leaf.coordinates), -leaf.serial)
            if candidate is None or key > candidate[0]:
                candidate = (key, index, left, right)
        if candidate is None:
            break
        _, index, left, right = candidate
        leaves[index : index + 1] = [left, right]
        serial += 2

    model_occupancy = np.zeros(voxels.occupancy.shape, dtype=bool)
    dominant_voxels = 0
    for leaf in leaves:
        slices = tuple(
            slice(int(leaf.lower[axis]), int(leaf.upper[axis])) for axis in range(3)
        )
        model_occupancy[slices] = True
        dominant_voxels += sum(
            int(labels[tuple(point)]) == leaf.material for point in leaf.coordinates
        )

    source_count = int(voxels.occupancy.sum())
    model_count = int(model_occupancy.sum())
    intersection = int((voxels.occupancy & model_occupancy).sum())
    union = int((voxels.occupancy | model_occupancy).sum())
    model_interior = model_occupancy.copy()
    for axis in range(3):
        lower_neighbor = np.zeros_like(model_occupancy)
        upper_neighbor = np.zeros_like(model_occupancy)
        lower_slice = [slice(None)] * 3
        upper_slice = [slice(None)] * 3
        lower_slice[axis] = slice(1, None)
        upper_slice[axis] = slice(None, -1)
        lower_neighbor[tuple(lower_slice)] = model_occupancy[tuple(upper_slice)]
        upper_neighbor[tuple(upper_slice)] = model_occupancy[tuple(lower_slice)]
        model_interior &= lower_neighbor & upper_neighbor
    model_surface = model_occupancy & ~model_interior
    expanded_model_surface = _dilate_six(model_surface, 1)
    expanded_source_surface = _dilate_six(voxels.raw_surface, 1)
    tolerant_intersection_source = int(
        (voxels.raw_surface & expanded_model_surface).sum()
    )
    tolerant_intersection_model = int(
        (model_surface & expanded_source_surface).sum()
    )
    surface_recall = tolerant_intersection_source / max(1, int(voxels.raw_surface.sum()))
    surface_precision = tolerant_intersection_model / max(1, int(model_surface.sum()))
    surface_f1 = (
        2 * surface_recall * surface_precision / (surface_recall + surface_precision)
        if surface_recall + surface_precision
        else 0.0
    )

    views: dict[str, Any] = {}
    for name, axis in (("side", 0), ("top", 1), ("front", 2)):
        source_mask = voxels.raw_surface.any(axis=axis)
        model_mask = model_occupancy.any(axis=axis)
        view_intersection = int((source_mask & model_mask).sum())
        view_union = int((source_mask | model_mask).sum())
        source_pixels = int(source_mask.sum())
        model_pixels = int(model_mask.sum())
        source_first = np.argmax(voxels.raw_surface, axis=axis)
        source_last = voxels.raw_surface.shape[axis] - 1 - np.argmax(
            np.flip(voxels.raw_surface, axis=axis), axis=axis
        )
        model_first = np.argmax(model_occupancy, axis=axis)
        model_last = model_occupancy.shape[axis] - 1 - np.argmax(
            np.flip(model_occupancy, axis=axis), axis=axis
        )
        comparable = source_mask & model_mask
        if comparable.any():
            depth_error = np.mean(
                (
                    np.abs(source_first[comparable] - model_first[comparable])
                    + np.abs(source_last[comparable] - model_last[comparable])
                )
                / 2
            ) / max(1, voxels.raw_surface.shape[axis] - 1)
        else:
            depth_error = 1.0
        views[name] = {
            "iou": round(view_intersection / max(1, view_union), 6),
            "source_coverage": round(view_intersection / max(1, source_pixels), 6),
            "model_precision": round(view_intersection / max(1, model_pixels), 6),
            "bidirectional_depth_mae": round(float(depth_error), 6),
            "source_pixels": source_pixels,
            "model_pixels": model_pixels,
        }
    axis_volume_metrics = {
        _AXIS_NAMES[axis]: _axis_fit_metrics(
            voxels.occupancy, model_occupancy, axis
        )
        for axis in range(3)
    }
    represented_components = {leaf.component for leaf in leaves}
    component_count = int(voxels.component_labels.max()) + 1
    fitted_components = _components(model_occupancy)
    fitted_component_labels = np.full(model_occupancy.shape, -1, dtype=np.int32)
    for fitted_index, component in enumerate(fitted_components):
        for point in component:
            fitted_component_labels[point] = fitted_index
    source_to_fitted: dict[str, list[int]] = {}
    for source_index in range(component_count):
        mapped = sorted(
            {
                int(value) + 1
                for value in fitted_component_labels[
                    voxels.component_labels == source_index
                ]
                if int(value) >= 0
            }
        )
        source_to_fitted[str(source_index + 1)] = mapped
    fitted_to_source: dict[str, list[int]] = {}
    for fitted_index, component in enumerate(fitted_components):
        source_labels = {
            int(voxels.component_labels[point])
            for point in component
            if int(voxels.component_labels[point]) >= 0
        }
        fitted_to_source[str(fitted_index + 1)] = [
            value + 1 for value in sorted(source_labels)
        ]
    merged_source_groups = [
        source_indexes
        for source_indexes in fitted_to_source.values()
        if len(source_indexes) > 1
    ]
    split_source_components = [
        int(source_index)
        for source_index, fitted_indexes in source_to_fitted.items()
        if len(fitted_indexes) > 1
    ]
    unmapped_fitted_components = [
        int(fitted_index)
        for fitted_index, source_indexes in fitted_to_source.items()
        if not source_indexes
    ]
    one_to_one_components = (
        len(fitted_components) == component_count
        and all(len(indexes) == 1 for indexes in source_to_fitted.values())
        and all(len(indexes) == 1 for indexes in fitted_to_source.values())
        and not merged_source_groups
        and not split_source_components
        and not unmapped_fitted_components
    )
    component_preservation = {
        "source_components": component_count,
        "represented_components": len(represented_components),
        "all_retained_components_represented": represented_components
        == set(range(component_count)),
        "cuboids_per_component": [
            sum(leaf.component == component for leaf in leaves)
            for component in range(component_count)
        ],
        "fitted_components": len(fitted_components),
        "fitted_component_sizes": [
            len(component) for component in fitted_components
        ],
        "source_to_fitted": source_to_fitted,
        "fitted_to_source": fitted_to_source,
        "merged_source_component_groups": merged_source_groups,
        "split_source_components": split_source_components,
        "unmapped_fitted_components": unmapped_fitted_components,
        "all_source_voxels_covered": bool(
            model_occupancy[voxels.occupancy].all()
        ),
        "one_to_one_fitted_connectivity": one_to_one_components,
    }
    source_axis_spans = {
        axis: metrics["source"]["axis_span_voxels"]
        for axis, metrics in axis_volume_metrics.items()
    }
    longest_source_span = max(source_axis_spans.values())
    source_axis_ratios = {
        axis: round(span / max(1, longest_source_span), 6)
        for axis, span in source_axis_spans.items()
    }
    minimum_span_preservation = min(
        metrics["axis_span_preservation"]
        for metrics in axis_volume_metrics.values()
    )
    minimum_depth_coverage = min(
        metrics["source_depth_envelope_coverage"]
        for metrics in axis_volume_metrics.values()
    )
    collapsed_source_rays = sum(
        metrics["collapsed_source_rays"]
        for metrics in axis_volume_metrics.values()
    )
    minimum_silhouette_precision = min(
        metrics["model_silhouette_precision"]
        for metrics in axis_volume_metrics.values()
    )
    minimum_depth_precision = min(
        metrics["model_depth_envelope_precision"]
        for metrics in axis_volume_metrics.values()
    )
    maximum_depth_inflation = max(
        metrics["depth_envelope_inflation_ratio"]
        for metrics in axis_volume_metrics.values()
    )
    model_voxel_precision = intersection / max(1, model_count)
    gate_checks = {
        "axis_span_preserved": minimum_span_preservation >= 1.0,
        "source_depth_envelopes_preserved": minimum_depth_coverage >= 1.0,
        "no_source_rays_collapsed": collapsed_source_rays == 0,
        "model_voxel_precision_bounded": (
            model_voxel_precision >= _MIN_MODEL_VOXEL_PRECISION
        ),
        "axis_silhouette_precision_bounded": (
            minimum_silhouette_precision >= _MIN_AXIS_SILHOUETTE_PRECISION
        ),
        "axis_depth_precision_bounded": (
            minimum_depth_precision >= _MIN_AXIS_DEPTH_ENVELOPE_PRECISION
        ),
        "axis_depth_inflation_bounded": (
            maximum_depth_inflation <= _MAX_AXIS_DEPTH_ENVELOPE_INFLATION
        ),
        "fitted_components_preserved_one_to_one": one_to_one_components,
        "all_six_signed_axis_views_recorded": len(_CANONICAL_VIEWS) == 6,
    }
    anti_pancake_gate = {
        "relative_to_source_mesh": True,
        "source_basis": "retained ray-voxel evidence after disclosed cleanup",
        "intrinsically_thin_source_axes": [
            axis for axis, ratio in source_axis_ratios.items() if ratio < 0.1
        ],
        "source_axis_span_ratios_to_longest": source_axis_ratios,
        "minimum_axis_span_preservation": round(minimum_span_preservation, 6),
        "minimum_source_depth_envelope_coverage": round(
            minimum_depth_coverage, 6
        ),
        "model_voxel_precision": round(model_voxel_precision, 6),
        "minimum_axis_model_silhouette_precision": round(
            minimum_silhouette_precision, 6
        ),
        "minimum_axis_model_depth_envelope_precision": round(
            minimum_depth_precision, 6
        ),
        "maximum_axis_depth_envelope_inflation": round(
            maximum_depth_inflation, 6
        ),
        "collapsed_source_rays": collapsed_source_rays,
        "recorded_signed_axis_views": len(_CANONICAL_VIEWS),
        "criteria": {
            "minimum_axis_span_preservation": 1.0,
            "minimum_source_depth_envelope_coverage": 1.0,
            "minimum_model_voxel_precision": _MIN_MODEL_VOXEL_PRECISION,
            "minimum_axis_model_silhouette_precision": (
                _MIN_AXIS_SILHOUETTE_PRECISION
            ),
            "minimum_axis_model_depth_envelope_precision": (
                _MIN_AXIS_DEPTH_ENVELOPE_PRECISION
            ),
            "maximum_axis_depth_envelope_inflation": (
                _MAX_AXIS_DEPTH_ENVELOPE_INFLATION
            ),
            "fitted_components_preserved_one_to_one": True,
            "required_signed_axis_views": 6,
        },
        "checks": gate_checks,
        "failed_checks": [
            name for name, passed in gate_checks.items() if not passed
        ],
        "passed": all(gate_checks.values()),
    }
    report = {
        "method": "adaptive binary 3D cuboid decomposition",
        "cuboids": len(leaves),
        "source_voxels": source_count,
        "cuboid_voxels": model_count,
        "intersection_voxels": intersection,
        "union_voxels": union,
        "voxel_iou": round(intersection / max(1, union), 6),
        "source_coverage": round(intersection / max(1, source_count), 6),
        "model_precision": round(intersection / max(1, model_count), 6),
        "dominant_color_fraction": round(dominant_voxels / max(1, source_count), 6),
        "surface_f1_tolerance_voxels": 1,
        "surface_precision_tolerant": round(surface_precision, 6),
        "surface_recall_tolerant": round(surface_recall, 6),
        "surface_f1_tolerant": round(surface_f1, 6),
        "orthographic_views": views,
        "axis_volume_metrics": axis_volume_metrics,
        "component_preservation": component_preservation,
        "anti_pancake_gate": anti_pancake_gate,
        "mean_silhouette_iou": round(
            sum(value["iou"] for value in views.values()) / len(views), 6
        ),
    }
    return leaves, report, model_occupancy


def _mesh_reference(path: Path, voxels: _VoxelData) -> None:
    np = _numpy()
    width, height, depth = voxels.occupancy.shape
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    for x in range(width):
        for y in range(height):
            occupied = np.flatnonzero(voxels.occupancy[x, y, :])
            if len(occupied):
                z = int(occupied[-1])
                color = tuple(int(value) for value in voxels.colors[x, y, z])
                pixels[x, height - y - 1] = color + (255,)
    scale = max(1, 256 // max(width, height))
    image = image.resize((width * scale, height * scale), Image.Resampling.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _model_color_volume(
    shape: tuple[int, int, int],
    leaves: list[_Leaf],
    palette: list[tuple[int, int, int]],
) -> tuple[Any, Any]:
    """Rasterize fitted cuboids and their dominant colors into the source grid."""
    np = _numpy()
    occupancy = np.zeros(shape, dtype=bool)
    colors = np.zeros(shape + (3,), dtype=np.uint8)
    for leaf in sorted(leaves, key=lambda item: (item.component, item.serial)):
        slices = tuple(
            slice(int(leaf.lower[axis]), int(leaf.upper[axis]))
            for axis in range(3)
        )
        region_occupancy = occupancy[slices]
        unassigned = ~region_occupancy
        region_colors = colors[slices]
        region_colors[unassigned] = palette[leaf.material]
        region_occupancy[unassigned] = True
    return occupancy, colors


def _project_cardinal(
    occupancy: Any,
    colors: Any,
    view: _CanonicalView,
) -> tuple[Any, Any]:
    """Project a colored voxel volume through a named signed-axis camera."""
    np = _numpy()
    width = occupancy.shape[view.horizontal_axis]
    height = occupancy.shape[view.vertical_axis]
    projected = np.zeros((height, width), dtype=bool)
    projected_colors = np.zeros((height, width, 3), dtype=np.uint8)
    for horizontal in range(width):
        for vertical in range(height):
            selector: list[int | slice] = [slice(None)] * 3
            selector[view.horizontal_axis] = horizontal
            selector[view.vertical_axis] = vertical
            depths = np.flatnonzero(occupancy[tuple(selector)])
            if not len(depths):
                continue
            depth = int(depths[-1] if view.positive_side else depths[0])
            point = [0, 0, 0]
            point[view.horizontal_axis] = horizontal
            point[view.vertical_axis] = vertical
            point[view.axis] = depth
            screen_x = (
                horizontal
                if view.horizontal_sign > 0
                else width - horizontal - 1
            )
            screen_y = (
                height - vertical - 1
                if view.vertical_sign > 0
                else vertical
            )
            projected[screen_y, screen_x] = True
            projected_colors[screen_y, screen_x] = colors[tuple(point)]
    return projected, projected_colors


def _project_isometric(occupancy: Any, colors: Any) -> tuple[Any, Any]:
    """Project +X/+Y/+Z voxel evidence into a deterministic oblique view."""
    np = _numpy()
    size_x, size_y, size_z = occupancy.shape
    minimum_u = -2 * (size_z - 1)
    maximum_u = 2 * (size_x - 1)
    minimum_v = -(size_x - 1) - (size_z - 1)
    maximum_v = 2 * (size_y - 1)
    padding = 2
    width = maximum_u - minimum_u + 1 + padding * 2
    height = maximum_v - minimum_v + 1 + padding * 2
    projected = np.zeros((height, width), dtype=bool)
    projected_colors = np.zeros((height, width, 3), dtype=np.uint8)
    depth_buffer = np.full((height, width), -1, dtype=np.int64)
    for coordinate in np.argwhere(occupancy):
        x, y, z = (int(value) for value in coordinate)
        screen_x = 2 * (x - z) - minimum_u + padding
        screen_y = maximum_v - (2 * y - x - z) + padding
        depth = x + y + z
        for offset_x, offset_y in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
            pixel_x = screen_x + offset_x
            pixel_y = screen_y + offset_y
            if depth < depth_buffer[pixel_y, pixel_x]:
                continue
            depth_buffer[pixel_y, pixel_x] = depth
            projected[pixel_y, pixel_x] = True
            projected_colors[pixel_y, pixel_x] = colors[x, y, z]
    return projected, projected_colors


def _review_preview(
    source_mask: Any,
    source_colors: Any,
    model_mask: Any,
    model_colors: Any,
) -> Image.Image:
    """Compose source albedo, fitted albedo, and silhouette-error panels."""
    np = _numpy()
    if source_mask.shape != model_mask.shape:
        raise ValueError("source and fitted review projections must have equal size")
    height, width = source_mask.shape
    background = np.asarray((20, 23, 28), dtype=np.uint8)
    source_panel = np.tile(background, (height, width, 1))
    model_panel = np.tile(background, (height, width, 1))
    source_panel[source_mask] = source_colors[source_mask]
    model_panel[model_mask] = model_colors[model_mask]
    overlay = np.tile(background, (height, width, 1))
    overlap = source_mask & model_mask
    source_only = source_mask & ~model_mask
    model_only = model_mask & ~source_mask
    overlay[overlap] = np.clip(
        source_colors[overlap].astype(np.int16) + 30, 0, 255
    ).astype(np.uint8)
    overlay[source_only] = (30, 202, 224)
    overlay[model_only] = (246, 139, 43)
    gutter = np.zeros((height, 1, 3), dtype=np.uint8)
    combined = np.concatenate(
        (source_panel, gutter, model_panel, gutter, overlay), axis=1
    )
    scale = max(1, min(12, 288 // max(1, width, height)))
    image = Image.fromarray(combined, mode="RGB")
    return image.resize(
        (combined.shape[1] * scale, height * scale),
        Image.Resampling.NEAREST,
    )


def _write_json(path: Path, value: Any) -> None:
    """Write deterministic JSON without importing the compiler module."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_multi_angle_review(
    output_path: Path,
    model_id: str,
    mesh_path: Path,
    voxels: _VoxelData,
    model_occupancy: Any,
    model_colors: Any,
    overlap: dict[str, Any],
) -> dict[str, Any]:
    """Emit deterministic ±axis and oblique source-versus-fit evidence."""
    view_directory = output_path.with_name(f"{model_id}.mesh-views")
    view_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path.with_name(f"{model_id}.mesh-views.json")
    manifest_views: list[dict[str, Any]] = []

    for view in _CANONICAL_VIEWS:
        source_mask, source_colors = _project_cardinal(
            voxels.raw_surface, voxels.colors, view
        )
        model_mask, fitted_colors = _project_cardinal(
            model_occupancy, model_colors, view
        )
        preview = _review_preview(
            source_mask, source_colors, model_mask, fitted_colors
        )
        preview_path = view_directory / f"{view.name}.png"
        preview.save(preview_path, format="PNG", optimize=False, compress_level=9)
        intersection = int((source_mask & model_mask).sum())
        union = int((source_mask | model_mask).sum())
        horizontal_direction = [0, 0, 0]
        horizontal_direction[view.horizontal_axis] = view.horizontal_sign
        manifest_views.append(
            {
                "id": view.name,
                "kind": "signed-axis",
                "axis": _AXIS_NAMES[view.axis],
                "camera_side": "positive" if view.positive_side else "negative",
                "look_direction": list(view.look_direction),
                "up_direction": list(view.up_direction),
                "horizontal_direction": horizontal_direction,
                "image": _relative_path(preview_path, manifest_path),
                "image_sha256": _sha256(preview_path),
                "image_size": list(preview.size),
                "source_visible_pixels": int(source_mask.sum()),
                "model_visible_pixels": int(model_mask.sum()),
                "silhouette_iou": round(intersection / max(1, union), 6),
            }
        )

    source_mask, source_colors = _project_isometric(
        voxels.raw_surface, voxels.colors
    )
    model_mask, fitted_colors = _project_isometric(
        model_occupancy, model_colors
    )
    preview = _review_preview(source_mask, source_colors, model_mask, fitted_colors)
    preview_path = view_directory / "isometric.png"
    preview.save(preview_path, format="PNG", optimize=False, compress_level=9)
    intersection = int((source_mask & model_mask).sum())
    union = int((source_mask | model_mask).sum())
    manifest_views.append(
        {
            "id": "isometric",
            "kind": "orthographic-oblique",
            "camera_side": "positive-x-positive-y-positive-z",
            "look_direction": [-1, -1, -1],
            "up_direction": [-1, 2, -1],
            "horizontal_direction": [1, 0, -1],
            "image": _relative_path(preview_path, manifest_path),
            "image_sha256": _sha256(preview_path),
            "image_size": list(preview.size),
            "source_visible_pixels": int(source_mask.sum()),
            "model_visible_pixels": int(model_mask.sum()),
            "silhouette_iou": round(intersection / max(1, union), 6),
        }
    )

    required_views = [view.name for view in _CANONICAL_VIEWS] + ["isometric"]
    generated_views = [view["id"] for view in manifest_views]
    manifest = {
        "schema_version": 1,
        "kind": "mesh-holistic-review",
        "algorithm": "six-signed-axis-plus-oblique-voxel-review-v1",
        "model_id": model_id,
        "source_mesh": {
            "path": _relative_path(mesh_path, manifest_path),
            "sha256": _sha256(mesh_path),
        },
        "coordinate_system": {
            "x": "left/right",
            "y": "vertical",
            "z": "back/front; positive z is front",
        },
        "voxel_grid": {
            "dimensions": [int(value) for value in voxels.occupancy.shape],
            "pitch_source_units": round(voxels.pitch, 9),
            "lower_source_units": [
                round(float(value), 9) for value in voxels.lower
            ],
        },
        "panels_left_to_right": [
            "source mesh ray-albedo",
            "fitted cuboid dominant-material projection",
            "overlap (bright source), source-only cyan, model-only orange",
        ],
        "required_views": required_views,
        "generated_views": generated_views,
        "complete": generated_views == required_views,
        "review_contract": {
            "automated_geometry_gate": (
                "pass" if overlap["anti_pancake_gate"]["passed"] else "fail"
            ),
            "agent_visual_review_required": True,
            "agent_visual_review_status": "pending",
            "required_checks": [
                "front and back preserve distinct source structure",
                "left and right retain source-relative thickness",
                "top and bottom preserve attachments and disconnected parts",
                "isometric fit has no collapsed or floating major volume",
            ],
        },
        "anti_pancake_gate": overlap["anti_pancake_gate"],
        "axis_volume_metrics": overlap["axis_volume_metrics"],
        "component_preservation": overlap["component_preservation"],
        "component_cleanup": voxels.report["components"],
        "views": manifest_views,
    }
    _write_json(manifest_path, manifest)
    return {
        "manifest": _relative_path(manifest_path, output_path),
        "manifest_sha256": _sha256(manifest_path),
        "directory": _relative_path(view_directory, output_path),
        "required_views": required_views,
        "generated_views": generated_views,
        "view_count": len(manifest_views),
        "complete": manifest["complete"],
        "agent_visual_review_required": True,
        "agent_visual_review_status": "pending",
        "views": {
            view["id"]: {
                "image": view["image"],
                "image_sha256": view["image_sha256"],
                "silhouette_iou": view["silhouette_iou"],
            }
            for view in manifest_views
        },
    }


def _image_reference(path: Path, output_path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as opened:
            width, height = opened.size
    except OSError as exc:
        raise ValueError(f"cannot read reference image {path}: {exc}") from exc
    return {
        "image": _relative_path(path, output_path),
        "sha256": _sha256(path),
        "width": width,
        "height": height,
    }


def reconstruct_mesh_spec(
    mesh_path: Path,
    output_path: Path,
    model_id: str,
    description: str,
    subject_type: str,
    options: MeshReconstructionOptions,
    reference_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct a textured mesh as deterministic native Blockbench cuboids."""
    if not 8 <= options.resolution <= 96:
        raise ValueError("resolution must be within 8..96")
    if not 1 <= options.max_cuboids <= 96:
        raise ValueError("max_cuboids must be within 1..96")
    if not 4 <= options.palette_size <= 64:
        raise ValueError("palette_size must be within 4..64")
    if options.fill_mode not in {"auto", "surface", "solid"}:
        raise ValueError("fill_mode must be auto, surface, or solid")
    if not 1 <= options.surface_thickness <= 4:
        raise ValueError("surface_thickness must be within 1..4")
    if options.target_size <= 0:
        raise ValueError("target_size must be positive")
    if not 1 <= options.geometry_precision <= 256:
        raise ValueError("geometry_precision must be within 1..256")
    if options.texture_density not in {1, 2, 4}:
        raise ValueError("texture_density must be 1, 2, or 4")

    mesh = _load_mesh(mesh_path, options.canonical_transform)
    voxels = _voxelize(mesh, options)
    palette, labels = _palette(voxels.colors, voxels.occupancy, options.palette_size)
    leaves, overlap, fitted_occupancy = _adaptive_cuboids(
        voxels, labels, options.max_cuboids
    )
    if not overlap["anti_pancake_gate"]["passed"]:
        failures = ", ".join(
            overlap["anti_pancake_gate"]["failed_checks"]
        )
        raise ValueError(
            "fitted cuboids failed source-relative anti-pancake validation: "
            f"{failures}"
        )
    rendered_occupancy, model_colors = _model_color_volume(
        voxels.occupancy.shape, leaves, palette
    )
    np = _numpy()
    if not np.array_equal(fitted_occupancy, rendered_occupancy):
        raise ValueError("fitted cuboid review occupancy disagrees with overlap audit")
    multi_angle_review = _write_multi_angle_review(
        output_path,
        model_id,
        mesh_path,
        voxels,
        fitted_occupancy,
        model_colors,
        overlap,
    )
    if not multi_angle_review["complete"]:
        raise ValueError("mesh reconstruction did not emit every required review view")

    if reference_path is None:
        reference_path = output_path.with_name(f"{model_id}.mesh-reference.png")
        _mesh_reference(reference_path, voxels)
        reference_origin = "mesh-ray-albedo projection"
    else:
        reference_origin = "user-supplied"
    reference = _image_reference(reference_path, output_path)

    extents = voxels.pitch * np.asarray(voxels.occupancy.shape, dtype=np.float64)
    mesh_axis_extents = np.ptp(mesh.vertices, axis=0)
    longest = float(max(extents))
    scale = options.target_size / longest
    center_x = float(voxels.lower[0] + extents[0] / 2)
    center_z = float(voxels.lower[2] + extents[2] / 2)
    ground_y = float(voxels.lower[1])

    materials: dict[str, Any] = {}
    for index, color in enumerate(palette):
        name = f"mesh_{index:02d}"
        materials[name] = {
            "base": _rgb_hex(color),
            "shade": _adjusted_hex(color, 0.62),
            "highlight": _adjusted_hex(color, 1.18),
            "pattern": "solid",
            "pattern_scale": 1,
        }

    cubes: list[dict[str, Any]] = []
    face_material_overrides = 0
    for index, leaf in enumerate(leaves, start=1):
        source_minimum = voxels.lower + leaf.lower * voxels.pitch
        source_maximum = voxels.lower + leaf.upper * voxels.pitch
        source_center = (source_minimum + source_maximum) / 2
        size = (source_maximum - source_minimum) * scale
        center = (
            (source_center[0] - center_x) * scale,
            (source_center[1] - ground_y) * scale,
            (source_center[2] - center_z) * scale,
        )
        faces: dict[str, Any] = {}
        for face, axis, boundary in (
            ("west", 0, int(leaf.lower[0])),
            ("east", 0, int(leaf.upper[0]) - 1),
            ("down", 1, int(leaf.lower[1])),
            ("up", 1, int(leaf.upper[1]) - 1),
            ("north", 2, int(leaf.lower[2])),
            ("south", 2, int(leaf.upper[2]) - 1),
        ):
            boundary_points = leaf.coordinates[
                leaf.coordinates[:, axis] == boundary
            ]
            if not len(boundary_points):
                continue
            counts = Counter(
                int(labels[tuple(point)]) for point in boundary_points
            )
            face_material = min(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[0]
            if face_material != leaf.material:
                faces[face] = {"material": f"mesh_{face_material:02d}"}
                face_material_overrides += 1
        cubes.append(
            {
                "name": f"mesh_c{leaf.component + 1:02d}_{index:03d}",
                "bone": "root",
                "center": [round(float(value), 6) for value in center],
                "size": [round(float(value), 6) for value in size],
                "rotation": [0, 0, 0],
                "origin": [0, 0, 0],
                "role": f"source mesh component {leaf.component + 1}",
                "material": f"mesh_{leaf.material:02d}",
                "faces": faces,
            }
        )

    model_extents = [float(value * scale) for value in extents]
    canonical = np.asarray(
        options.canonical_transform
        if options.canonical_transform is not None
        else (
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1,
        ),
        dtype=np.float64,
    ).reshape(4, 4)
    normalization = np.asarray(
        (
            (scale, 0, 0, -center_x * scale),
            (0, scale, 0, -ground_y * scale),
            (0, 0, scale, -center_z * scale),
            (0, 0, 0, 1),
        ),
        dtype=np.float64,
    )
    effective_transform = normalization @ canonical
    report = {
        "schema_version": 1,
        "algorithm": "orthographic-six-view-ray-voxel-adaptive-cuboids-v2",
        "source": {
            "path": _relative_path(mesh_path, output_path),
            "sha256": _sha256(mesh_path),
            "format": mesh_path.suffix.lower().lstrip("."),
            "geometries": mesh.geometry_count,
            "vertices": mesh.vertex_count,
            "triangles": mesh.face_count,
            "watertight": mesh.watertight,
            "axis_extents_source_units": [
                round(float(value), 9) for value in mesh_axis_extents
            ],
            "provider": options.provider,
            "provider_model": options.provider_model,
            "license": options.source_license,
            "canonical_transform": [
                round(float(value), 9) for value in canonical.ravel()
            ],
            "effective_model_transform": [
                round(float(value), 9) for value in effective_transform.ravel()
            ],
            "normalization": {
                "target_size": options.target_size,
                "scale": round(scale, 9),
                "model_extents": [round(value, 6) for value in model_extents],
                "grounded_y": 0,
                "centered_axes": ["x", "z"],
            },
        },
        "voxelization": voxels.report,
        "color_transfer": {
            "sources": list(mesh.color_sources),
            "method": "barycentric ray-hit sampling with per-cuboid face palette",
            "palette": [_rgb_hex(color) for color in palette],
            "palette_entries": len(palette),
            "face_material_overrides": face_material_overrides,
        },
        "source_mesh_overlap": overlap,
        "multi_angle_review": multi_angle_review,
    }
    spec = {
        "schema_version": 1,
        "id": model_id,
        "reference": reference,
        "subject": {
            "type": subject_type,
            "description": description,
            "symmetry": "none",
            "uncertainties": [
                "Voxel resolution and cuboid budget approximate curved surfaces",
                "Rig semantics cannot be inferred from an unrigged triangle mesh",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [1, options.max_cuboids],
            "identity_features": [
                "source-mesh six-direction silhouette",
                "mesh-derived surface palette",
            ],
            "required_views": [
                "front",
                "back",
                "left",
                "right",
                "top",
                "bottom",
                "isometric",
            ],
            "review_targets": ["silhouette", "volume", "components", "texture"],
        },
        "geometry": {"precision": options.geometry_precision},
        "texture": {
            "density": options.texture_density,
            "palette_size": max(4, min(64, len(palette))),
            "gutter": 1,
            "atlas_size": 256,
        },
        "materials": materials,
        "bones": [{"name": "root", "parent": None, "pivot": [0, 0, 0]}],
        "cubes": cubes,
        "landmarks": [],
        "collision": {
            "width": round(max(model_extents[0], model_extents[2]) / 16, 6),
            "height": round(model_extents[1] / 16, 6),
            "eye_height": round(model_extents[1] * 0.85 / 16, 6),
        },
        "generation": {
            "lane": "mesh-ray-voxel",
            "algorithm": report["algorithm"],
            "mesh": report["source"],
            "reference_origin": reference_origin,
            "voxelization": report["voxelization"],
            "source_mesh_overlap": overlap,
            "multi_angle_review": multi_angle_review,
            "color_transfer": report["color_transfer"],
        },
    }
    review_manifest_path = output_path.parent / Path(
        str(multi_angle_review["manifest"])
    )
    review_manifest = json.loads(review_manifest_path.read_text(encoding="utf-8"))
    review_manifest["model_spec"] = {
        "content_hash_method": MODEL_CONTENT_HASH_METHOD,
        "content_sha256": model_content_sha256(spec),
    }
    _write_json(review_manifest_path, review_manifest)
    multi_angle_review["manifest_sha256"] = _sha256(review_manifest_path)
    return spec, report
