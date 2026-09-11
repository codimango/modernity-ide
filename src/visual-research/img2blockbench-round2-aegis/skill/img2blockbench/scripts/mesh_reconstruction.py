#!/usr/bin/env python3
"""Deterministic ray-voxel reconstruction for textured triangle meshes."""

from __future__ import annotations

import hashlib
import math
import os
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


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


def _dependencies() -> tuple[Any, Any]:
    """Import optional mesh dependencies only when Route 1 is invoked."""
    try:
        import numpy as np
        import trimesh
    except ImportError as exc:
        raise ValueError(
            "mesh or multi-view reconstruction requires optional dependencies; "
            "install img2blockbench[mesh-reconstruction] or "
            "img2blockbench[multi-view]"
        ) from exc
    return np, trimesh


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
    np, trimesh = _dependencies()
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
    np, _ = _dependencies()
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
    np, _ = _dependencies()
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


def _voxelize(mesh: _MeshData, options: MeshReconstructionOptions) -> _VoxelData:
    np, _ = _dependencies()
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
    inside_votes = np.zeros(shape, dtype=np.uint8)
    color_sums = np.zeros(shape + (3,), dtype=np.float64)
    color_counts = np.zeros(shape, dtype=np.uint32)
    ray_count = 0
    intersection_count = 0
    odd_parity_rays = 0
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
            colors = _hit_colors(mesh, face_indexes, weights)
            np.add.at(color_sums, tuple(coordinates.T), colors)
            np.add.at(color_counts, tuple(coordinates.T), 1)
            intersection_count += len(face_indexes)

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
        retained = retained[: options.max_cuboids]
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

    report = {
        "grid_dimensions": list(shape),
        "voxel_pitch_source_units": round(pitch, 9),
        "fill_mode_requested": options.fill_mode,
        "fill_mode_resolved": "solid" if solid else "surface",
        "surface_thickness_voxels": options.surface_thickness,
        "ray_evidence": {
            "method": "three orthographic ray grids evaluated bidirectionally",
            "direction_count": 6,
            "bidirectional_rays": ray_count * 2,
            "unique_direction_rays": ray_count,
            "triangle_intersections": intersection_count,
            "surface_voxels": int(surface.sum()),
            "odd_parity_rays": odd_parity_rays,
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
    np, _ = _dependencies()
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
    np, _ = _dependencies()
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


def _adaptive_cuboids(
    voxels: _VoxelData,
    labels: Any,
    maximum: int,
) -> tuple[list[_Leaf], dict[str, Any], Any]:
    np, _ = _dependencies()
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
        "mean_silhouette_iou": round(
            sum(value["iou"] for value in views.values()) / len(views), 6
        ),
    }
    return leaves, report, model_occupancy


def _mesh_reference(path: Path, voxels: _VoxelData) -> None:
    np, _ = _dependencies()
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
    leaves, overlap, _ = _adaptive_cuboids(
        voxels, labels, options.max_cuboids
    )

    if reference_path is None:
        reference_path = output_path.with_name(f"{model_id}.mesh-reference.png")
        _mesh_reference(reference_path, voxels)
        reference_origin = "mesh-ray-albedo projection"
    else:
        reference_origin = "user-supplied"
    reference = _image_reference(reference_path, output_path)

    np, _ = _dependencies()
    extents = voxels.pitch * np.asarray(voxels.occupancy.shape, dtype=np.float64)
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
        "algorithm": "orthographic-ray-voxel-adaptive-cuboids-v1",
        "source": {
            "path": _relative_path(mesh_path, output_path),
            "sha256": _sha256(mesh_path),
            "format": mesh_path.suffix.lower().lstrip("."),
            "geometries": mesh.geometry_count,
            "vertices": mesh.vertex_count,
            "triangles": mesh.face_count,
            "watertight": mesh.watertight,
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
            "required_views": ["front", "back", "left", "right", "top", "isometric"],
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
            "color_transfer": report["color_transfer"],
        },
    }
    return spec, report
