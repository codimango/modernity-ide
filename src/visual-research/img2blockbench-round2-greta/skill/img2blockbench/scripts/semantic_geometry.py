#!/usr/bin/env python3
"""Reusable geometry helpers for anatomy-driven Blockbench models."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


Point3 = tuple[float, float, float]


def _number(value: float) -> float | int:
    """Return stable JSON-friendly numbers without floating point chatter."""
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded


def _point(values: Sequence[float], label: str) -> Point3:
    if len(values) != 3 or not all(math.isfinite(float(value)) for value in values):
        raise ValueError(f"{label} must contain three finite numbers")
    return tuple(float(value) for value in values)  # type: ignore[return-value]


def segment_rotation(start: Sequence[float], end: Sequence[float]) -> list[float | int]:
    """Return XYZ Euler angles that aim a cuboid's local +Y axis at ``end``."""
    first = _point(start, "start")
    second = _point(end, "end")
    delta = tuple(second[index] - first[index] for index in range(3))
    length = math.sqrt(sum(value * value for value in delta))
    if length <= 1e-9:
        raise ValueError("segment endpoints must be distinct")
    direction = tuple(value / length for value in delta)

    # With the compiler's X, then Y, then Z convention, keeping Y rotation at
    # zero maps local +Y to (-sin(z) cos(x), cos(z) cos(x), sin(x)).
    rotation_x = math.degrees(math.asin(max(-1.0, min(1.0, direction[2]))))
    rotation_z = math.degrees(math.atan2(-direction[0], direction[1]))
    return [_number(rotation_x), 0, _number(rotation_z)]


def normal_rotation(direction: Sequence[float]) -> list[float | int]:
    """Return XYZ Euler angles that aim a cuboid's local +Z face outward."""
    vector = _point(direction, "direction")
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1e-9:
        raise ValueError("normal direction cannot be zero")
    x, y, z = (value / length for value in vector)
    rotation_x = -math.degrees(math.asin(max(-1.0, min(1.0, y))))
    rotation_y = math.degrees(math.atan2(x, z))
    return [_number(rotation_x), _number(rotation_y), 0]


def segment_cube(
    name: str,
    bone: str,
    start: Sequence[float],
    end: Sequence[float],
    thickness: float | Sequence[float],
    role: str,
    material: str,
    *,
    overlap: float = 0.25,
    faces: dict[str, Any] | None = None,
    longitudinal_axis: str = "y",
) -> dict[str, Any]:
    """Create one rotated cuboid spanning two joints with endpoint overlap."""
    first = _point(start, "start")
    second = _point(end, "end")
    delta = tuple(second[index] - first[index] for index in range(3))
    length = math.sqrt(sum(value * value for value in delta))
    if length <= 1e-9:
        raise ValueError("segment endpoints must be distinct")
    if isinstance(thickness, (int, float)) and not isinstance(thickness, bool):
        width = depth = float(thickness)
    else:
        pair = tuple(float(value) for value in thickness)
        if len(pair) != 2:
            raise ValueError("thickness must be a number or [width, depth]")
        width, depth = pair
    if not all(math.isfinite(value) and value > 0 for value in (width, depth)):
        raise ValueError("segment thickness must be finite and positive")
    if overlap < 0 or not math.isfinite(overlap):
        raise ValueError("segment overlap must be finite and non-negative")
    if longitudinal_axis == "y":
        # Center is expressed before rotation because Blockbench rotates the
        # box around origin. The rotated center is the path midpoint.
        center = (first[0], first[1] + length / 2, first[2])
        size = (width, length + overlap * 2, depth)
        rotation = segment_rotation(first, second)
    elif longitudinal_axis == "z":
        center = (first[0], first[1], first[2] + length / 2)
        size = (width, depth, length + overlap * 2)
        rotation = normal_rotation(delta)
    else:
        raise ValueError("longitudinal_axis must be 'y' or 'z'")
    return {
        "name": name,
        "bone": bone,
        "center": [_number(value) for value in center],
        "size": [_number(value) for value in size],
        "rotation": rotation,
        "origin": [_number(value) for value in first],
        "role": role,
        "material": material,
        "faces": dict(faces or {}),
    }


def radial_polyline(
    anchor: Sequence[float],
    azimuth_degrees: float,
    steps: Iterable[Sequence[float]],
) -> list[Point3]:
    """Expand radial/vertical steps into a 3D joint path around an anchor.

    Each step is ``(radial_distance, vertical_distance)`` relative to the
    preceding point. Zero degrees points along +X and 90 degrees along +Z.
    """
    point = _point(anchor, "anchor")
    if not math.isfinite(azimuth_degrees):
        raise ValueError("azimuth_degrees must be finite")
    angle = math.radians(azimuth_degrees)
    direction_x = math.cos(angle)
    direction_z = math.sin(angle)
    result = [point]
    for index, values in enumerate(steps):
        pair = tuple(float(value) for value in values)
        if len(pair) != 2 or not all(math.isfinite(value) for value in pair):
            raise ValueError(f"steps[{index}] must contain two finite numbers")
        radial, vertical = pair
        point = (
            point[0] + direction_x * radial,
            point[1] + vertical,
            point[2] + direction_z * radial,
        )
        result.append(tuple(float(_number(value)) for value in point))
    if len(result) < 2:
        raise ValueError("at least one radial step is required")
    return result


def transform_radial_profile(
    center: Sequence[float],
    azimuth_degrees: float,
    local_points: Iterable[Sequence[float]],
) -> list[Point3]:
    """Place tangent/up/outward profile points around a common 3D center."""
    origin = _point(center, "center")
    if not math.isfinite(azimuth_degrees):
        raise ValueError("azimuth_degrees must be finite")
    angle = math.radians(azimuth_degrees)
    radial = (math.cos(angle), 0.0, math.sin(angle))
    tangent = (-math.sin(angle), 0.0, math.cos(angle))
    transformed = []
    for index, values in enumerate(local_points):
        local = _point(values, f"local_points[{index}]")
        transformed.append(
            tuple(
                float(
                    _number(
                        origin[axis]
                        + tangent[axis] * local[0]
                        + (local[1] if axis == 1 else 0.0)
                        + radial[axis] * local[2]
                    )
                )
                for axis in range(3)
            )
        )
    if not transformed:
        raise ValueError("local_points cannot be empty")
    return transformed


def _inverse_rotate_point(
    point: Sequence[float], origin: Sequence[float], rotation: Sequence[float]
) -> Point3:
    """Undo the compiler's X, then Y, then Z Euler transform."""
    world = _point(point, "point")
    pivot = _point(origin, "origin")
    angles = _point(rotation, "rotation")
    x, y, z = (world[index] - pivot[index] for index in range(3))
    angle_x, angle_y, angle_z = (math.radians(value) for value in angles)
    cosine = math.cos(-angle_z)
    sine = math.sin(-angle_z)
    x, y = x * cosine - y * sine, x * sine + y * cosine
    cosine = math.cos(-angle_y)
    sine = math.sin(-angle_y)
    x, z = x * cosine + z * sine, -x * sine + z * cosine
    cosine = math.cos(-angle_x)
    sine = math.sin(-angle_x)
    y, z = y * cosine - z * sine, y * sine + z * cosine
    return x + pivot[0], y + pivot[1], z + pivot[2]


def point_to_cuboid_margin(
    cube: dict[str, Any],
    point: Sequence[float],
    *,
    compiled_bounds: tuple[Sequence[float], Sequence[float]] | None = None,
) -> float:
    """Return signed distance from a point to the nearest oriented box face.

    Positive values are inside the cuboid, zero lies on its surface, and a
    negative value proves a detached joint. This avoids false positives from
    overlapping world-axis bounds of rotated boxes.
    """
    local = _inverse_rotate_point(point, cube["origin"], cube["rotation"])
    if compiled_bounds is None:
        center = _point(cube["center"], "cube.center")
        size = _point(cube["size"], "cube.size")
    else:
        minimum = _point(compiled_bounds[0], "compiled minimum")
        maximum = _point(compiled_bounds[1], "compiled maximum")
        center = tuple((minimum[index] + maximum[index]) / 2 for index in range(3))
        size = tuple(maximum[index] - minimum[index] for index in range(3))
    margins = [
        size[axis] / 2 - abs(local[axis] - center[axis]) for axis in range(3)
    ]
    return min(margins)


def audit_attachments(
    model: dict[str, Any] | Sequence[dict[str, Any]],
    attachments: Iterable[tuple[str, str, Sequence[float]]],
    *,
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Audit that each declared joint lies inside both oriented cuboids.

    Pass a full specification to audit compiler-snapped bounds. A cube list is
    accepted for lightweight authoring checks and uses unsnapped dimensions.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and non-negative")
    if isinstance(model, dict):
        cubes = model.get("cubes")
        if not isinstance(cubes, list):
            raise ValueError("model specification must contain cubes")
        from img2blockbench import exported_cube_bounds

        bounds = {
            cube["name"]: exported_cube_bounds(model, cube) for cube in cubes
        }
        method = "shared-joint-compiled-oriented-cuboid-margin-v2"
    else:
        cubes = list(model)
        bounds = {cube["name"]: None for cube in cubes}
        method = "shared-joint-authored-oriented-cuboid-margin-v1"
    names = [cube.get("name") for cube in cubes]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("all audited cubes require names")
    if len(names) != len(set(names)):
        raise ValueError("audited cube names must be unique")
    cube_by_name = {cube["name"]: cube for cube in cubes}
    records = []
    for first_name, second_name, joint in attachments:
        if first_name not in cube_by_name or second_name not in cube_by_name:
            raise ValueError(f"attachment references unknown cubes: {first_name}, {second_name}")
        first_margin = point_to_cuboid_margin(
            cube_by_name[first_name], joint, compiled_bounds=bounds[first_name]
        )
        second_margin = point_to_cuboid_margin(
            cube_by_name[second_name], joint, compiled_bounds=bounds[second_name]
        )
        minimum = min(first_margin, second_margin)
        records.append(
            {
                "first": first_name,
                "second": second_name,
                "joint": [_number(value) for value in _point(joint, "joint")],
                "first_margin": _number(first_margin),
                "second_margin": _number(second_margin),
                "minimum_margin": _number(minimum),
                "connected": minimum >= -tolerance,
            }
        )
    return {
        "method": method,
        "attachments": records,
        "all_connected": all(record["connected"] for record in records),
        "minimum_margin": min(
            (float(record["minimum_margin"]) for record in records), default=0.0
        ),
    }


@dataclass(frozen=True)
class ChainResult:
    """Names and joints emitted for one articulated chain."""

    bones: tuple[str, ...]
    cubes: tuple[str, ...]
    joints: tuple[Point3, ...]

    @property
    def attachments(self) -> tuple[tuple[str, str, Point3], ...]:
        """Return adjacent cube pairs and their exact shared joints."""
        return tuple(
            (self.cubes[index], self.cubes[index + 1], self.joints[index + 1])
            for index in range(len(self.cubes) - 1)
        )


@dataclass(frozen=True)
class BranchNode:
    """One named joint in a deterministic branching geometry graph."""

    name: str
    point: Sequence[float]


@dataclass(frozen=True)
class BranchEdge:
    """A tapered semantic edge joining two named graph nodes."""

    name: str
    start: str
    end: str
    start_thickness: float
    end_thickness: float
    material: str
    role: str
    segments: int = 2
    start_depth: float | None = None
    end_depth: float | None = None


@dataclass(frozen=True)
class BranchGraphResult:
    """Native geometry and an explicit attachment manifest for a tree."""

    bones: tuple[str, ...]
    cubes: tuple[str, ...]
    attachments: tuple[tuple[str, str, Point3], ...]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class EllipsoidResult:
    """Greedy native-cuboid decomposition of an ellipsoid occupancy grid."""

    cubes: tuple[dict[str, Any], ...]
    grid_shape: tuple[int, int, int]
    occupied_voxels: int
    voxel_size: Point3
    base_occupied_voxels: int = 0
    removed_voxels: int = 0
    carved_faces: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EllipsoidCutout:
    """One subtractive ellipsoid used for deterministic occupancy carving."""

    center: Sequence[float]
    radii: Sequence[float]
    exponent: float = 2.0


def _grown_box(
    seed: tuple[int, int, int],
    occupied: set[tuple[int, int, int]],
    order: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Grow one positive-axis box under a deterministic axis ordering."""
    lower = list(seed)
    upper = list(seed)
    for axis in order:
        while True:
            candidate = upper.copy()
            candidate[axis] += 1
            cells = itertools.product(
                range(lower[0], candidate[0] + 1),
                range(lower[1], candidate[1] + 1),
                range(lower[2], candidate[2] + 1),
            )
            if all(cell in occupied for cell in cells):
                upper = candidate
            else:
                break
    return tuple(lower), tuple(upper)


def _axis_merged_boxes(
    occupied: set[tuple[int, int, int]],
    axis_order: tuple[int, int, int],
) -> list[tuple[tuple[int, int, int], tuple[int, int, int]]]:
    """Merge adjacent occupied cells without ever filling an empty voxel."""
    boxes = [(cell, cell) for cell in sorted(occupied)]
    changed = True
    while changed:
        changed = False
        for axis in axis_order:
            groups: dict[
                tuple[tuple[int, int], ...],
                list[tuple[tuple[int, int, int], tuple[int, int, int]]],
            ] = {}
            for lower, upper in boxes:
                key = tuple(
                    (lower[index], upper[index])
                    for index in range(3)
                    if index != axis
                )
                groups.setdefault(key, []).append((lower, upper))
            merged = []
            for key in sorted(groups):
                group = sorted(groups[key], key=lambda box: box[0][axis])
                current_lower, current_upper = group[0]
                for lower, upper in group[1:]:
                    if lower[axis] == current_upper[axis] + 1:
                        extended = list(current_upper)
                        extended[axis] = upper[axis]
                        current_upper = tuple(extended)  # type: ignore[assignment]
                        changed = True
                    else:
                        merged.append((current_lower, current_upper))
                        current_lower, current_upper = lower, upper
                merged.append((current_lower, current_upper))
            boxes = merged
    return sorted(boxes)


def ellipsoid_cuboids(
    name: str,
    bone: str,
    center: Sequence[float],
    radii: Sequence[float],
    subdivisions: Sequence[int],
    role: str,
    material: str,
    *,
    max_cuboids: int = 96,
    exponent: float = 2.0,
    cutouts: Sequence[EllipsoidCutout] = (),
) -> EllipsoidResult:
    """Voxelize and greedily merge a superellipsoid with optional cutouts.

    The default exponent of two is a mathematical ellipsoid. Slightly larger
    exponents create organic, fuller silhouettes while retaining rounded
    orthographic profiles and exact voxel occupancy. Each cutout subtracts a
    second ellipsoid at voxel-center resolution before merging, providing a
    deterministic negative-space/CSG primitive without emitting proxy solids.
    """
    origin = _point(center, "center")
    radius = _point(radii, "radii")
    if not all(value > 0 for value in radius):
        raise ValueError("radii must be positive")
    if len(subdivisions) != 3 or not all(
        isinstance(value, int) and not isinstance(value, bool) and 3 <= value <= 64
        for value in subdivisions
    ):
        raise ValueError("subdivisions must contain three integers within 3..64")
    shape = tuple(int(value) for value in subdivisions)
    if (
        not isinstance(max_cuboids, int)
        or isinstance(max_cuboids, bool)
        or max_cuboids < 1
    ):
        raise ValueError("max_cuboids must be positive")
    if not math.isfinite(exponent) or exponent < 1:
        raise ValueError("exponent must be finite and at least one")
    normalized_cutouts = []
    for index, cutout in enumerate(cutouts):
        if not isinstance(cutout, EllipsoidCutout):
            raise ValueError(f"cutouts[{index}] must be an EllipsoidCutout")
        cutout_center = _point(cutout.center, f"cutouts[{index}].center")
        cutout_radii = _point(cutout.radii, f"cutouts[{index}].radii")
        if not all(value > 0 for value in cutout_radii):
            raise ValueError(f"cutouts[{index}].radii must be positive")
        if not math.isfinite(cutout.exponent) or cutout.exponent < 1:
            raise ValueError(f"cutouts[{index}].exponent must be finite and at least one")
        normalized_cutouts.append((cutout_center, cutout_radii, float(cutout.exponent)))
    cell_size = tuple(2 * radius[axis] / shape[axis] for axis in range(3))
    base_occupied: set[tuple[int, int, int]] = set()
    for x in range(shape[0]):
        for y in range(shape[1]):
            for z in range(shape[2]):
                normalized = tuple(
                    (-radius[axis] + (index + 0.5) * cell_size[axis]) / radius[axis]
                    for axis, index in enumerate((x, y, z))
                )
                if sum(abs(value) ** exponent for value in normalized) <= 1.0:
                    base_occupied.add((x, y, z))
    occupied = set(base_occupied)
    for cell in base_occupied:
        world = tuple(
            origin[axis] - radius[axis] + (cell[axis] + 0.5) * cell_size[axis]
            for axis in range(3)
        )
        if any(
            sum(
                abs((world[axis] - cutout_center[axis]) / cutout_radii[axis])
                ** cutout_exponent
                for axis in range(3)
            )
            <= 1.0
            for cutout_center, cutout_radii, cutout_exponent in normalized_cutouts
        ):
            occupied.remove(cell)
    if not occupied:
        raise ValueError("ellipsoid occupancy is empty")
    occupied_count = len(occupied)
    removed = base_occupied - occupied
    remaining = set(occupied)
    boxes: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    orders = tuple(itertools.permutations((0, 1, 2)))
    while remaining:
        best: tuple[int, tuple[int, int, int], tuple[int, int, int]] | None = None
        for seed in sorted(remaining):
            for order in orders:
                lower, upper = _grown_box(seed, remaining, order)
                volume = math.prod(upper[axis] - lower[axis] + 1 for axis in range(3))
                candidate = (volume, lower, upper)
                if best is None or candidate > best:
                    best = candidate
        if best is None:
            raise RuntimeError("ellipsoid decomposition made no progress")
        _, lower, upper = best
        cells = set(
            itertools.product(
                range(lower[0], upper[0] + 1),
                range(lower[1], upper[1] + 1),
                range(lower[2], upper[2] + 1),
            )
        )
        remaining.difference_update(cells)
        boxes.append((lower, upper))
    candidates = [boxes]
    candidates.extend(
        _axis_merged_boxes(occupied, order)
        for order in itertools.permutations((0, 1, 2))
    )
    boxes = min(candidates, key=lambda candidate: (len(candidate), candidate))
    if len(boxes) > max_cuboids:
        raise ValueError(
            f"ellipsoid requires more than {max_cuboids} greedy cuboids; "
            "reduce subdivisions"
        )

    cubes = []
    for index, (lower, upper) in enumerate(boxes, start=1):
        cube_center = tuple(
            origin[axis]
            - radius[axis]
            + (lower[axis] + upper[axis] + 1) * cell_size[axis] / 2
            for axis in range(3)
        )
        cube_size = tuple(
            (upper[axis] - lower[axis] + 1) * cell_size[axis]
            for axis in range(3)
        )
        cubes.append(
            {
                "name": f"{name}_{index:03d}",
                "bone": bone,
                "center": [_number(value) for value in cube_center],
                "size": [_number(value) for value in cube_size],
                "rotation": [0, 0, 0],
                "origin": [_number(value) for value in cube_center],
                "role": f"{role} greedy volume {index}",
                "material": material,
                "faces": {},
            }
        )
    carved_faces = []
    face_directions = (
        ("west", 0, -1),
        ("east", 0, 1),
        ("down", 1, -1),
        ("up", 1, 1),
        ("north", 2, -1),
        ("south", 2, 1),
    )
    for cube, (lower, upper) in zip(cubes, boxes):
        for face, axis, direction in face_directions:
            ranges = [
                range(lower[index], upper[index] + 1)
                for index in range(3)
            ]
            ranges[axis] = range(
                lower[axis] if direction < 0 else upper[axis],
                (lower[axis] if direction < 0 else upper[axis]) + 1,
            )
            if any(
                tuple(
                    cell[index] + (direction if index == axis else 0)
                    for index in range(3)
                )
                in removed
                for cell in itertools.product(*ranges)
            ):
                carved_faces.append((cube["name"], face))
    return EllipsoidResult(
        tuple(cubes),
        shape,
        occupied_count,
        cell_size,
        len(base_occupied),
        len(removed),
        tuple(carved_faces),
    )


class SemanticModelBuilder:
    """Accumulate unique bones and semantic cuboids with connected chains."""

    def __init__(self, root_name: str = "root", pivot: Sequence[float] = (0, 0, 0)):
        root_pivot = _point(pivot, "pivot")
        self.bones: list[dict[str, Any]] = [
            {
                "name": root_name,
                "parent": None,
                "pivot": [_number(value) for value in root_pivot],
            }
        ]
        self.cubes: list[dict[str, Any]] = []
        self._bone_names = {root_name}
        self._cube_names: set[str] = set()

    def add_bone(
        self, name: str, parent: str, pivot: Sequence[float]
    ) -> dict[str, Any]:
        """Add one bone after checking uniqueness and parent ordering."""
        if name in self._bone_names:
            raise ValueError(f"duplicate bone name: {name}")
        if parent not in self._bone_names:
            raise ValueError(f"unknown parent bone: {parent}")
        record = {
            "name": name,
            "parent": parent,
            "pivot": [_number(value) for value in _point(pivot, "pivot")],
        }
        self.bones.append(record)
        self._bone_names.add(name)
        return record

    def add_cube(self, cube: dict[str, Any]) -> dict[str, Any]:
        """Add one fully described cuboid with unique name and known bone."""
        name = cube.get("name")
        bone = cube.get("bone")
        if not isinstance(name, str) or not name:
            raise ValueError("cube name is required")
        if name in self._cube_names:
            raise ValueError(f"duplicate cube name: {name}")
        if bone not in self._bone_names:
            raise ValueError(f"unknown cube bone: {bone}")
        self.cubes.append(cube)
        self._cube_names.add(name)
        return cube

    def add_chain(
        self,
        name: str,
        parent_bone: str,
        joints: Sequence[Sequence[float]],
        thicknesses: float | Sequence[float],
        materials: str | Sequence[str],
        role: str,
        *,
        overlap: float = 0.25,
        depths: float | Sequence[float] | None = None,
        longitudinal_axis: str = "y",
    ) -> ChainResult:
        """Add a parented bone/cuboid for every interval in a joint path.

        ``thicknesses`` controls local X width. Supplying ``depths`` produces
        rectangular cross-sections, useful for leaves, blades, and fins.
        """
        if parent_bone not in self._bone_names:
            raise ValueError(f"unknown parent bone: {parent_bone}")
        if not math.isfinite(overlap) or overlap < 0:
            raise ValueError("overlap must be finite and non-negative")
        if longitudinal_axis not in {"y", "z"}:
            raise ValueError("longitudinal_axis must be 'y' or 'z'")
        points = tuple(_point(value, f"joints[{index}]") for index, value in enumerate(joints))
        segment_count = len(points) - 1
        if segment_count < 1:
            raise ValueError("a chain requires at least two joints")

        def expanded(value: float | str | Sequence[float] | Sequence[str], label: str) -> list[Any]:
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                return [value] * segment_count
            items = list(value)
            if len(items) != segment_count:
                raise ValueError(f"{label} must have one value per segment")
            return items

        widths = expanded(thicknesses, "thicknesses")
        depth_values = expanded(depths, "depths") if depths is not None else widths
        paints = expanded(materials, "materials")
        generated_names = [f"{name}_{index + 1}" for index in range(segment_count)]
        duplicates = [
            generated
            for generated in generated_names
            if generated in self._bone_names or generated in self._cube_names
        ]
        if duplicates:
            raise ValueError(f"duplicate chain name: {duplicates[0]}")
        for index in range(segment_count):
            if math.dist(points[index], points[index + 1]) <= 1e-9:
                raise ValueError(f"chain segment {index + 1} endpoints must be distinct")
            width = float(widths[index])
            depth = float(depth_values[index])
            if not math.isfinite(width) or width <= 0:
                raise ValueError(f"thicknesses[{index}] must be finite and positive")
            if not math.isfinite(depth) or depth <= 0:
                raise ValueError(f"depths[{index}] must be finite and positive")
            if not isinstance(paints[index], str) or not paints[index]:
                raise ValueError(f"materials[{index}] must be a non-empty string")
        bone_names: list[str] = []
        cube_names: list[str] = []
        parent = parent_bone
        for index in range(segment_count):
            suffix = index + 1
            bone_name = generated_names[index]
            cube_name = bone_name
            self.add_bone(bone_name, parent, points[index])
            self.add_cube(
                segment_cube(
                    cube_name,
                    bone_name,
                    points[index],
                    points[index + 1],
                    (float(widths[index]), float(depth_values[index])),
                    f"{role} segment {suffix}",
                    str(paints[index]),
                    overlap=overlap,
                    longitudinal_axis=longitudinal_axis,
                )
            )
            bone_names.append(bone_name)
            cube_names.append(cube_name)
            parent = bone_name
        return ChainResult(tuple(bone_names), tuple(cube_names), points)

    def add_branch_graph(
        self,
        name: str,
        parent_bone: str,
        root_node: str,
        nodes: Sequence[BranchNode],
        edges: Sequence[BranchEdge],
        *,
        overlap: float = 0.25,
        parent_cube: str | None = None,
    ) -> BranchGraphResult:
        """Add a connected tapered tree while preserving atomic mutation.

        Edges may branch from any named joint. Each edge is split into one or
        more native cuboids forming a piecewise-constant approximation of the
        requested linear taper. The first bone of every child edge is parented
        to the last bone of the edge entering its start node.

        Validation and geometry generation complete before the builder is
        mutated, so an invalid graph cannot leave partial bones or cuboids.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("branch graph name is required")
        if parent_bone not in self._bone_names:
            raise ValueError(f"unknown parent bone: {parent_bone}")
        if parent_cube is not None and parent_cube not in self._cube_names:
            raise ValueError(f"unknown parent cube: {parent_cube}")
        if not math.isfinite(overlap) or overlap < 0:
            raise ValueError("overlap must be finite and non-negative")

        node_records = list(nodes)
        if not node_records:
            raise ValueError("branch graph requires at least two nodes")
        node_names = [node.name for node in node_records]
        if any(not isinstance(node_name, str) or not node_name for node_name in node_names):
            raise ValueError("branch node names must be non-empty strings")
        if len(node_names) != len(set(node_names)):
            raise ValueError("duplicate branch node name")
        points = {
            node.name: _point(node.point, f"node {node.name}") for node in node_records
        }
        if root_node not in points:
            raise ValueError(f"unknown root node: {root_node}")
        if parent_cube is not None:
            parent_record = next(
                cube for cube in self.cubes if cube["name"] == parent_cube
            )
            if parent_record["bone"] != parent_bone:
                raise ValueError("branch parent cube must belong to the parent bone")
            if point_to_cuboid_margin(parent_record, points[root_node]) < -1e-6:
                raise ValueError("branch root joint is detached from its parent cube")

        edge_records = list(edges)
        if not edge_records:
            raise ValueError("branch graph requires at least one edge")
        edge_names = [edge.name for edge in edge_records]
        if any(not isinstance(edge_name, str) or not edge_name for edge_name in edge_names):
            raise ValueError("branch edge names must be non-empty strings")
        if len(edge_names) != len(set(edge_names)):
            raise ValueError("duplicate branch edge name")

        incoming: dict[str, BranchEdge] = {}
        outgoing: dict[str, list[BranchEdge]] = {node_name: [] for node_name in node_names}
        for edge in edge_records:
            if edge.start not in points or edge.end not in points:
                raise ValueError(f"branch edge {edge.name} references an unknown node")
            if edge.start == edge.end or math.dist(points[edge.start], points[edge.end]) <= 1e-9:
                raise ValueError(f"branch edge {edge.name} endpoints must be distinct")
            if edge.end in incoming:
                raise ValueError(f"branch node {edge.end} has multiple incoming edges")
            if edge.end == root_node:
                raise ValueError("branch graph root cannot have an incoming edge")
            if (
                not isinstance(edge.segments, int)
                or isinstance(edge.segments, bool)
                or not 1 <= edge.segments <= 32
            ):
                raise ValueError(f"branch edge {edge.name} segments must be within 1..32")
            start_depth = (
                edge.start_thickness if edge.start_depth is None else edge.start_depth
            )
            end_depth = edge.end_thickness if edge.end_depth is None else edge.end_depth
            dimensions = (
                edge.start_thickness,
                edge.end_thickness,
                start_depth,
                end_depth,
            )
            if not all(math.isfinite(value) and value > 0 for value in dimensions):
                raise ValueError(
                    f"branch edge {edge.name} dimensions must be finite and positive"
                )
            if not isinstance(edge.material, str) or not edge.material:
                raise ValueError(f"branch edge {edge.name} material is required")
            if not isinstance(edge.role, str) or not edge.role:
                raise ValueError(f"branch edge {edge.name} role is required")
            incoming[edge.end] = edge
            outgoing[edge.start].append(edge)

        # Detect directed cycles independently so malformed disconnected cycles
        # are reported precisely rather than as a generic reachability failure.
        visit_state: dict[str, int] = {node_name: 0 for node_name in node_names}

        def visit(node_name: str) -> None:
            if visit_state[node_name] == 1:
                raise ValueError("branch graph contains a cycle")
            if visit_state[node_name] == 2:
                return
            visit_state[node_name] = 1
            for edge in outgoing[node_name]:
                visit(edge.end)
            visit_state[node_name] = 2

        for node_name in node_names:
            visit(node_name)

        ordered_edges: list[BranchEdge] = []
        reached = {root_node}
        pending = {edge.name: edge for edge in edge_records}
        while pending:
            ready = sorted(
                (edge for edge in pending.values() if edge.start in reached),
                key=lambda edge: edge.name,
            )
            if not ready:
                raise ValueError("branch graph contains nodes disconnected from its root")
            for edge in ready:
                ordered_edges.append(edge)
                reached.add(edge.end)
                del pending[edge.name]
        if reached != set(node_names):
            raise ValueError("branch graph contains nodes disconnected from its root")

        generated_names = [
            f"{name}_{edge.name}_{index + 1}"
            for edge in ordered_edges
            for index in range(edge.segments)
        ]
        if len(generated_names) != len(set(generated_names)):
            raise ValueError("branch graph generates duplicate segment names")
        from img2blockbench import ID_RE

        invalid_generated = [
            generated_name
            for generated_name in generated_names
            if not ID_RE.fullmatch(generated_name)
        ]
        if invalid_generated:
            raise ValueError(f"invalid branch segment name: {invalid_generated[0]}")
        collisions = [
            generated_name
            for generated_name in generated_names
            if generated_name in self._bone_names or generated_name in self._cube_names
        ]
        if collisions:
            raise ValueError(f"duplicate branch segment name: {collisions[0]}")

        local_bones: list[dict[str, Any]] = []
        local_cubes: list[dict[str, Any]] = []
        attachments: list[tuple[str, str, Point3]] = []
        terminal_bone_by_node: dict[str, str] = {root_node: parent_bone}
        terminal_cube_by_node: dict[str, str] = (
            {root_node: parent_cube} if parent_cube is not None else {}
        )
        edge_manifest = []
        for edge in ordered_edges:
            start = points[edge.start]
            end = points[edge.end]
            start_depth = (
                edge.start_thickness if edge.start_depth is None else edge.start_depth
            )
            end_depth = edge.end_thickness if edge.end_depth is None else edge.end_depth
            parent = terminal_bone_by_node[edge.start]
            previous_cube = terminal_cube_by_node.get(edge.start)
            emitted = []
            for index in range(edge.segments):
                first_fraction = index / edge.segments
                second_fraction = (index + 1) / edge.segments
                midpoint_fraction = (first_fraction + second_fraction) / 2
                first = tuple(
                    start[axis] + (end[axis] - start[axis]) * first_fraction
                    for axis in range(3)
                )
                second = tuple(
                    start[axis] + (end[axis] - start[axis]) * second_fraction
                    for axis in range(3)
                )
                width = edge.start_thickness + (
                    edge.end_thickness - edge.start_thickness
                ) * midpoint_fraction
                depth = start_depth + (end_depth - start_depth) * midpoint_fraction
                segment_name = f"{name}_{edge.name}_{index + 1}"
                local_bones.append(
                    {
                        "name": segment_name,
                        "parent": parent,
                        "pivot": [_number(value) for value in first],
                    }
                )
                local_cubes.append(
                    segment_cube(
                        segment_name,
                        segment_name,
                        first,
                        second,
                        (width, depth),
                        f"{edge.role} tapered segment {index + 1}",
                        edge.material,
                        overlap=overlap,
                    )
                )
                if previous_cube is not None:
                    attachments.append((previous_cube, segment_name, first))
                previous_cube = segment_name
                parent = segment_name
                emitted.append(segment_name)
            terminal_bone_by_node[edge.end] = emitted[-1]
            terminal_cube_by_node[edge.end] = emitted[-1]
            edge_manifest.append(
                {
                    "name": edge.name,
                    "start": edge.start,
                    "end": edge.end,
                    "segments": emitted,
                    "start_thickness": _number(edge.start_thickness),
                    "end_thickness": _number(edge.end_thickness),
                    "start_depth": _number(start_depth),
                    "end_depth": _number(end_depth),
                    "material": edge.material,
                    "role": edge.role,
                }
            )

        # This is the only mutation point. Everything above is validation or
        # construction in local collections.
        self.bones.extend(local_bones)
        self.cubes.extend(local_cubes)
        self._bone_names.update(generated_names)
        self._cube_names.update(generated_names)
        manifest = {
            "name": name,
            "root_node": root_node,
            "parent_bone": parent_bone,
            "parent_cube": parent_cube,
            "taper_method": "piecewise-constant-midpoint-sampling",
            "nodes": [
                {"name": node_name, "point": [_number(value) for value in points[node_name]]}
                for node_name in sorted(node_names)
            ],
            "edges": edge_manifest,
            "attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        }
        return BranchGraphResult(
            tuple(generated_names),
            tuple(generated_names),
            tuple(attachments),
            manifest,
        )
