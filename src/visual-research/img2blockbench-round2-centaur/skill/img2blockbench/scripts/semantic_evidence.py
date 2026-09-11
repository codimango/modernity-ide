#!/usr/bin/env python3
"""Deterministic multi-view renderer and attachment metrics for cuboid specs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    raise ModuleNotFoundError(
        "semantic_evidence requires the optional 'semantic-evidence' extra: "
        "pip install 'img2blockbench[semantic-evidence]'"
    ) from exc
from PIL import Image, ImageDraw, ImageFont, ImageOps

from img2blockbench import build_texture, exported_cube_bounds, face_uv
from photo_reconstruction import _cube_point


FACE_VERTICES = {
    "north": (1, 0, 3, 2),
    "east": (5, 1, 2, 6),
    "south": (4, 5, 6, 7),
    "west": (0, 4, 7, 3),
    "up": (7, 6, 2, 3),
    "down": (0, 1, 5, 4),
}

STANDARD_VIEWS = {
    "front": (0.0, 0.04, 1.0),
    "back": (0.0, 0.04, -1.0),
    "left": (1.0, 0.06, 0.0),
    "right": (-1.0, 0.06, 0.0),
    "top": (0.001, 1.0, 0.0),
    "isometric": (1.0, 0.58, 1.0),
}

CAMERA_ROTATION_TOLERANCE = 1e-6


def _finite_tuple(
    values: Sequence[float], length: int, label: str
) -> tuple[float, ...]:
    """Return a fixed-size tuple after rejecting booleans and non-finite values."""
    try:
        items = tuple(values)
    except TypeError as exc:
        raise ValueError(f"{label} must contain {length} finite numbers") from exc
    if len(items) != length or not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in items
    ):
        raise ValueError(f"{label} must contain {length} finite numbers")
    return tuple(float(value) for value in items)


def _image_size(values: Sequence[int]) -> tuple[int, int]:
    """Return validated positive image dimensions."""
    try:
        items = tuple(values)
    except TypeError as exc:
        raise ValueError("image_size must contain two positive integers") from exc
    if (
        len(items) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in items
        )
        or any(value <= 0 or value > 8192 for value in items)
    ):
        raise ValueError("image_size must contain two integers within 1..8192")
    return int(items[0]), int(items[1])


@dataclass(frozen=True)
class ProjectedPoint:
    """One point projected into a fixed perspective camera frame."""

    pixel: tuple[float, float] | None
    depth: float
    in_front: bool
    in_frame: bool

    def __post_init__(self) -> None:
        """Validate and canonicalize the immutable projection result."""
        if (
            isinstance(self.depth, bool)
            or not isinstance(self.depth, (int, float))
            or not math.isfinite(float(self.depth))
        ):
            raise ValueError("depth must be a finite number")
        if not isinstance(self.in_front, bool) or not isinstance(self.in_frame, bool):
            raise ValueError("projection flags must be booleans")
        pixel = (
            None
            if self.pixel is None
            else _finite_tuple(self.pixel, 2, "pixel")
        )
        if self.in_front != (pixel is not None):
            raise ValueError("in-front projections require pixels and vice versa")
        if self.in_frame and not self.in_front:
            raise ValueError("an in-frame projection must be in front of the camera")
        object.__setattr__(self, "pixel", pixel)
        object.__setattr__(self, "depth", float(self.depth))


@dataclass(frozen=True)
class PerspectiveCamera:
    """Validated fixed camera using a right-handed world-to-camera transform.

    Camera-space visible points have negative Z. ``translation`` is the usual
    extrinsic translation in ``camera = rotation @ world + translation``.
    Rotation validation allows ``1e-6`` absolute floating-point drift.
    """

    image_size: tuple[int, int]
    focal_x: float
    focal_y: float
    principal_point: tuple[float, float]
    world_to_camera: tuple[tuple[float, float, float], ...]
    translation: tuple[float, float, float]
    near: float = 0.1

    def __post_init__(self) -> None:
        """Validate and canonicalize every camera parameter."""
        width, height = _image_size(self.image_size)
        focal = _finite_tuple((self.focal_x, self.focal_y), 2, "focal lengths")
        if any(value <= 0 for value in focal):
            raise ValueError("focal lengths must be positive")
        principal = _finite_tuple(self.principal_point, 2, "principal_point")
        try:
            matrix_rows = tuple(self.world_to_camera)
        except TypeError as exc:
            raise ValueError("world_to_camera must be a 3x3 matrix") from exc
        if len(matrix_rows) != 3:
            raise ValueError("world_to_camera must be a 3x3 matrix")
        rows = tuple(
            _finite_tuple(row, 3, f"world_to_camera row {index}")
            for index, row in enumerate(matrix_rows)
        )
        matrix = np.asarray(rows, dtype=np.float64)
        if not np.allclose(
            matrix @ matrix.T,
            np.eye(3),
            atol=CAMERA_ROTATION_TOLERANCE,
            rtol=0,
        ):
            raise ValueError("world_to_camera must be orthonormal")
        if not math.isclose(
            float(np.linalg.det(matrix)),
            1.0,
            abs_tol=CAMERA_ROTATION_TOLERANCE,
        ):
            raise ValueError("world_to_camera must be a right-handed rotation")
        translation = _finite_tuple(self.translation, 3, "translation")
        if (
            isinstance(self.near, bool)
            or not isinstance(self.near, (int, float))
            or not math.isfinite(float(self.near))
            or float(self.near) <= 0
        ):
            raise ValueError("near must be a positive finite number")
        object.__setattr__(self, "image_size", (int(width), int(height)))
        object.__setattr__(self, "focal_x", focal[0])
        object.__setattr__(self, "focal_y", focal[1])
        object.__setattr__(self, "principal_point", principal)
        object.__setattr__(self, "world_to_camera", rows)
        object.__setattr__(self, "translation", translation)
        object.__setattr__(self, "near", float(self.near))

    @classmethod
    def from_orbit(
        cls,
        image_size: tuple[int, int],
        *,
        yaw_degrees: float,
        pitch_degrees: float,
        roll_degrees: float = 0.0,
        vertical_fov_degrees: float = 50.0,
        target: Sequence[float] = (0.0, 0.0, 0.0),
        distance: float = 10.0,
        near: float = 0.1,
        principal_point: Sequence[float] | None = None,
    ) -> "PerspectiveCamera":
        """Construct a fixed camera orbiting a target in the Y-up model frame."""
        image_size = _image_size(image_size)
        angles = _finite_tuple(
            (yaw_degrees, pitch_degrees, roll_degrees), 3, "orbit angles"
        )
        yaw, pitch, roll = (math.radians(value) for value in angles)
        if abs(angles[1]) >= 89.9:
            raise ValueError("pitch_degrees must be strictly between -89.9 and 89.9")
        if (
            isinstance(vertical_fov_degrees, bool)
            or not isinstance(vertical_fov_degrees, (int, float))
            or not math.isfinite(float(vertical_fov_degrees))
            or not 1.0 <= float(vertical_fov_degrees) <= 179.0
        ):
            raise ValueError("vertical_fov_degrees must be within 1..179")
        if (
            isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or not math.isfinite(float(distance))
            or float(distance) <= 0
        ):
            raise ValueError("distance must be a positive finite number")
        if (
            isinstance(near, bool)
            or not isinstance(near, (int, float))
            or not math.isfinite(float(near))
            or float(near) <= 0
        ):
            raise ValueError("near must be a positive finite number")
        if float(distance) <= float(near):
            raise ValueError("distance must exceed the near plane")
        target_vector = np.asarray(_finite_tuple(target, 3, "target"), dtype=np.float64)
        outward = np.asarray(
            (
                math.sin(yaw) * math.cos(pitch),
                math.sin(pitch),
                math.cos(yaw) * math.cos(pitch),
            ),
            dtype=np.float64,
        )
        position = target_vector + float(distance) * outward
        forward = -outward
        world_up = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
        right = np.cross(forward, world_up)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        cosine = math.cos(roll)
        sine = math.sin(roll)
        rolled_right = cosine * right + sine * up
        rolled_up = -sine * right + cosine * up
        rotation = np.vstack((rolled_right, rolled_up, -forward))
        translation = -(rotation @ position)
        width, height = image_size
        focal = (float(height) / 2.0) / math.tan(
            math.radians(float(vertical_fov_degrees)) / 2.0
        )
        principal = (
            (float(width) / 2.0, float(height) / 2.0)
            if principal_point is None
            else _finite_tuple(principal_point, 2, "principal_point")
        )
        return cls(
            image_size=image_size,
            focal_x=focal,
            focal_y=focal,
            principal_point=principal,
            world_to_camera=tuple(tuple(float(value) for value in row) for row in rotation),
            translation=tuple(float(value) for value in translation),
            near=near,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return stable JSON-ready intrinsic and extrinsic parameters."""
        return {
            "projection": "perspective",
            "image_size": list(self.image_size),
            "focal_x": self.focal_x,
            "focal_y": self.focal_y,
            "principal_point": list(self.principal_point),
            "world_to_camera": [list(row) for row in self.world_to_camera],
            "translation": list(self.translation),
            "near": self.near,
        }


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if bold
        else Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def cube_vertices(spec: dict[str, Any], cube: dict[str, Any]) -> np.ndarray:
    """Return the eight world-space corners using compiler conventions."""
    minimum, maximum = exported_cube_bounds(spec, cube)
    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    return np.asarray(
        [
            _cube_point(cube, x0, y0, z0),
            _cube_point(cube, x1, y0, z0),
            _cube_point(cube, x1, y1, z0),
            _cube_point(cube, x0, y1, z0),
            _cube_point(cube, x0, y0, z1),
            _cube_point(cube, x1, y0, z1),
            _cube_point(cube, x1, y1, z1),
            _cube_point(cube, x0, y1, z1),
        ],
        dtype=np.float64,
    )


def camera_basis(direction: tuple[float, float, float]) -> tuple[np.ndarray, ...]:
    """Create an orthographic right/up/view camera basis."""
    view = np.asarray(direction, dtype=np.float64)
    if np.linalg.norm(view) <= 1e-12:
        raise ValueError("camera direction cannot be zero")
    view /= np.linalg.norm(view)
    world_up = np.asarray((0.0, 1.0, 0.0))
    if abs(float(np.dot(view, world_up))) > 0.96:
        world_up = np.asarray((0.0, 0.0, -1.0))
    right = np.cross(world_up, view)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    up /= np.linalg.norm(up)
    return right, up, view


def _raster_triangle(
    canvas: np.ndarray,
    zbuffer: np.ndarray,
    points: np.ndarray,
    depths: np.ndarray,
    texture_uv: np.ndarray,
    atlas: np.ndarray,
    brightness: float,
) -> None:
    minimum_x = max(0, math.floor(float(points[:, 0].min())))
    maximum_x = min(canvas.shape[1] - 1, math.ceil(float(points[:, 0].max())))
    minimum_y = max(0, math.floor(float(points[:, 1].min())))
    maximum_y = min(canvas.shape[0] - 1, math.ceil(float(points[:, 1].max())))
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
    inside = (weight_a >= -1e-7) & (weight_b >= -1e-7) & (weight_c >= -1e-7)
    if not inside.any():
        return
    depth = weight_a * depths[0] + weight_b * depths[1] + weight_c * depths[2]
    target_depth = zbuffer[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    visible = inside & (depth > target_depth)
    if not visible.any():
        return
    uv = (
        weight_a[:, :, None] * texture_uv[0]
        + weight_b[:, :, None] * texture_uv[1]
        + weight_c[:, :, None] * texture_uv[2]
    )
    texture_x = np.clip(np.rint(uv[:, :, 0]), 0, atlas.shape[1] - 1).astype(np.int64)
    texture_y = np.clip(np.rint(uv[:, :, 1]), 0, atlas.shape[0] - 1).astype(np.int64)
    sampled = atlas[texture_y, texture_x].copy()
    sampled[:, :, :3] = np.clip(
        np.rint(sampled[:, :, :3].astype(np.float64) * brightness), 0, 255
    ).astype(np.uint8)
    visible &= sampled[:, :, 3] >= 16
    target = canvas[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    target[visible] = sampled[visible]
    target_depth[visible] = depth[visible]


def render_view(
    spec: dict[str, Any],
    direction: tuple[float, float, float],
    *,
    atlas_image: Image.Image | None = None,
    placements: dict[tuple[str, str], tuple[int, int, int, int]] | None = None,
    selected_names: set[str] | None = None,
    size: tuple[int, int] = (640, 640),
    background: tuple[int, int, int, int] = (13, 20, 28, 255),
) -> Image.Image:
    """Render native rotated cuboids through an orthographic depth buffer."""
    if atlas_image is None or placements is None:
        atlas_image, placements = build_texture(spec)
    cubes = [
        cube for cube in spec["cubes"]
        if selected_names is None or cube["name"] in selected_names
    ]
    if not cubes:
        raise ValueError("render selection contains no cuboids")
    right, up, view = camera_basis(direction)
    all_vertices = np.concatenate([cube_vertices(spec, cube) for cube in cubes])
    projected = np.column_stack((all_vertices @ right, all_vertices @ up))
    lower = projected.min(axis=0)
    upper = projected.max(axis=0)
    margin = 42
    scale = min(
        (size[0] - margin * 2) / max(1e-6, upper[0] - lower[0]),
        (size[1] - margin * 2) / max(1e-6, upper[1] - lower[1]),
    )
    center = (lower + upper) / 2
    atlas = np.asarray(atlas_image.convert("RGBA"), dtype=np.uint8)
    canvas = np.empty((size[1], size[0], 4), dtype=np.uint8)
    canvas[:, :, :] = background
    zbuffer = np.full((size[1], size[0]), -np.inf, dtype=np.float64)
    light = np.asarray((0.35, 0.8, 0.48), dtype=np.float64)
    light /= np.linalg.norm(light)

    for cube in cubes:
        vertices = cube_vertices(spec, cube)
        screen = np.column_stack((vertices @ right, vertices @ up))
        screen[:, 0] = (screen[:, 0] - center[0]) * scale + size[0] / 2
        screen[:, 1] = size[1] / 2 - (screen[:, 1] - center[1]) * scale
        depths = vertices @ view
        for face_name, indexes in FACE_VERTICES.items():
            face_vertices = vertices[list(indexes)]
            normal = np.cross(
                face_vertices[1] - face_vertices[0],
                face_vertices[2] - face_vertices[0],
            )
            length = np.linalg.norm(normal)
            if length <= 1e-12:
                continue
            normal /= length
            if float(np.dot(normal, view)) <= 1e-7:
                continue
            placement = placements[(cube["name"], face_name)]
            first_u, first_v, second_u, second_v = face_uv(cube, face_name, placement)
            uv = np.asarray(
                ((first_u, second_v), (second_u, second_v),
                 (second_u, first_v), (first_u, first_v)),
                dtype=np.float64,
            )
            brightness = 0.72 + 0.32 * max(0.0, float(np.dot(normal, light)))
            for triangle in ((0, 1, 2), (0, 2, 3)):
                indexes_in_face = list(triangle)
                _raster_triangle(
                    canvas,
                    zbuffer,
                    screen[list(indexes)][indexes_in_face],
                    depths[list(indexes)][indexes_in_face],
                    uv[indexes_in_face],
                    atlas,
                    brightness,
                )
    return Image.fromarray(canvas, mode="RGBA")


def project_perspective_point(
    camera: PerspectiveCamera, point: Sequence[float]
) -> ProjectedPoint:
    """Project one world point without fitting or changing the camera frame.

    Depth is positive in front of the camera. Points behind the configured
    near plane retain their depth but do not receive image coordinates.
    """
    world = np.asarray(_finite_tuple(point, 3, "point"), dtype=np.float64)
    rotation = np.asarray(camera.world_to_camera, dtype=np.float64)
    translation = np.asarray(camera.translation, dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        transformed = rotation @ world + translation
    if not np.all(np.isfinite(transformed)):
        raise ValueError("perspective projection produced non-finite camera coordinates")
    depth = -float(transformed[2])
    if depth < camera.near:
        return ProjectedPoint(None, depth, False, False)
    pixel_x = camera.focal_x * float(transformed[0]) / depth + camera.principal_point[0]
    pixel_y = camera.principal_point[1] - camera.focal_y * float(transformed[1]) / depth
    if not math.isfinite(pixel_x) or not math.isfinite(pixel_y):
        raise ValueError("perspective projection produced non-finite pixel coordinates")
    width, height = camera.image_size
    return ProjectedPoint(
        (pixel_x, pixel_y),
        depth,
        True,
        0 <= pixel_x < width and 0 <= pixel_y < height,
    )


def _clip_near_plane(
    vertices: np.ndarray,
    texture_uv: np.ndarray,
    near: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Clip one camera-space triangle and its UVs against camera ``-near``."""
    output_vertices: list[np.ndarray] = []
    output_uv: list[np.ndarray] = []
    previous_vertex = vertices[-1]
    previous_uv = texture_uv[-1]
    previous_inside = -float(previous_vertex[2]) >= near
    for current_vertex, current_uv in zip(vertices, texture_uv):
        current_inside = -float(current_vertex[2]) >= near
        if current_inside != previous_inside:
            denominator = float(current_vertex[2] - previous_vertex[2])
            if abs(denominator) > 1e-15:
                amount = (-near - float(previous_vertex[2])) / denominator
                output_vertices.append(
                    previous_vertex + amount * (current_vertex - previous_vertex)
                )
                output_uv.append(previous_uv + amount * (current_uv - previous_uv))
        if current_inside:
            output_vertices.append(current_vertex)
            output_uv.append(current_uv)
        previous_vertex = current_vertex
        previous_uv = current_uv
        previous_inside = current_inside
    if len(output_vertices) < 3:
        return np.empty((0, 3), dtype=np.float64), np.empty((0, 2), dtype=np.float64)
    return np.asarray(output_vertices), np.asarray(output_uv)


def _raster_perspective_triangle(
    canvas: np.ndarray,
    zbuffer: np.ndarray,
    points: np.ndarray,
    depths: np.ndarray,
    texture_uv: np.ndarray,
    atlas: np.ndarray,
    brightness: float,
) -> None:
    """Raster one clipped triangle with perspective-correct UV interpolation."""
    minimum_x = max(0, math.floor(float(points[:, 0].min())))
    maximum_x = min(canvas.shape[1] - 1, math.ceil(float(points[:, 0].max())))
    minimum_y = max(0, math.floor(float(points[:, 1].min())))
    maximum_y = min(canvas.shape[0] - 1, math.ceil(float(points[:, 1].max())))
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
    inside = (weight_a >= -1e-7) & (weight_b >= -1e-7) & (weight_c >= -1e-7)
    inverse_depths = 1.0 / depths
    inverse_depth = (
        weight_a * inverse_depths[0]
        + weight_b * inverse_depths[1]
        + weight_c * inverse_depths[2]
    )
    valid = inside & np.isfinite(inverse_depth) & (inverse_depth > 0)
    if not valid.any():
        return
    depth = np.full(inverse_depth.shape, np.inf, dtype=np.float64)
    depth[valid] = 1.0 / inverse_depth[valid]
    target_depth = zbuffer[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    visible = valid & (depth < target_depth)
    if not visible.any():
        return
    numerator = (
        weight_a[:, :, None] * texture_uv[0] * inverse_depths[0]
        + weight_b[:, :, None] * texture_uv[1] * inverse_depths[1]
        + weight_c[:, :, None] * texture_uv[2] * inverse_depths[2]
    )
    uv = np.zeros_like(numerator)
    uv[valid] = numerator[valid] / inverse_depth[valid, None]
    texture_x = np.clip(np.rint(uv[:, :, 0]), 0, atlas.shape[1] - 1).astype(np.int64)
    texture_y = np.clip(np.rint(uv[:, :, 1]), 0, atlas.shape[0] - 1).astype(np.int64)
    sampled = atlas[texture_y, texture_x].copy()
    sampled[:, :, :3] = np.clip(
        np.rint(sampled[:, :, :3].astype(np.float64) * brightness), 0, 255
    ).astype(np.uint8)
    visible &= sampled[:, :, 3] >= 16
    target = canvas[minimum_y : maximum_y + 1, minimum_x : maximum_x + 1]
    target[visible] = sampled[visible]
    target_depth[visible] = depth[visible]


def render_perspective_view(
    spec: dict[str, Any],
    camera: PerspectiveCamera,
    *,
    atlas_image: Image.Image | None = None,
    placements: dict[tuple[str, str], tuple[int, int, int, int]] | None = None,
    selected_names: set[str] | None = None,
    background: tuple[int, int, int, int] = (13, 20, 28, 255),
) -> Image.Image:
    """Render native cuboids in one fixed perspective frame without auto-fit."""
    if atlas_image is None or placements is None:
        atlas_image, placements = build_texture(spec)
    cubes = sorted(
        (
            cube
            for cube in spec["cubes"]
            if selected_names is None or cube["name"] in selected_names
        ),
        key=lambda cube: cube["name"],
    )
    if not cubes:
        raise ValueError("render selection contains no cuboids")
    width, height = camera.image_size
    canvas = np.empty((height, width, 4), dtype=np.uint8)
    canvas[:, :, :] = background
    zbuffer = np.full((height, width), np.inf, dtype=np.float64)
    atlas = np.asarray(atlas_image.convert("RGBA"), dtype=np.uint8)
    rotation = np.asarray(camera.world_to_camera, dtype=np.float64)
    translation = np.asarray(camera.translation, dtype=np.float64)
    light = np.asarray((0.35, 0.8, 0.48), dtype=np.float64)
    light /= np.linalg.norm(light)

    for cube in cubes:
        world_vertices = cube_vertices(spec, cube)
        with np.errstate(over="ignore", invalid="ignore"):
            camera_vertices = world_vertices @ rotation.T + translation
        if not np.all(np.isfinite(camera_vertices)):
            raise ValueError("perspective projection produced non-finite camera coordinates")
        for face_name, indexes in FACE_VERTICES.items():
            face_world = world_vertices[list(indexes)]
            face_camera = camera_vertices[list(indexes)]
            camera_normal = np.cross(
                face_camera[1] - face_camera[0], face_camera[2] - face_camera[0]
            )
            normal_length = np.linalg.norm(camera_normal)
            if normal_length <= 1e-12:
                continue
            camera_normal /= normal_length
            if float(np.dot(camera_normal, -face_camera.mean(axis=0))) <= 1e-9:
                continue
            world_normal = np.cross(
                face_world[1] - face_world[0], face_world[2] - face_world[0]
            )
            world_normal /= np.linalg.norm(world_normal)
            brightness = 0.72 + 0.32 * max(0.0, float(np.dot(world_normal, light)))
            placement = placements[(cube["name"], face_name)]
            first_u, first_v, second_u, second_v = face_uv(cube, face_name, placement)
            face_uvs = np.asarray(
                (
                    (first_u, second_v),
                    (second_u, second_v),
                    (second_u, first_v),
                    (first_u, first_v),
                ),
                dtype=np.float64,
            )
            for triangle in ((0, 1, 2), (0, 2, 3)):
                local_indexes = list(triangle)
                clipped_vertices, clipped_uv = _clip_near_plane(
                    face_camera[local_indexes], face_uvs[local_indexes], camera.near
                )
                for index in range(1, len(clipped_vertices) - 1):
                    triangle_vertices = clipped_vertices[[0, index, index + 1]]
                    triangle_uv = clipped_uv[[0, index, index + 1]]
                    depths = -triangle_vertices[:, 2]
                    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                        screen = np.column_stack(
                            (
                                camera.focal_x * triangle_vertices[:, 0] / depths
                                + camera.principal_point[0],
                                camera.principal_point[1]
                                - camera.focal_y * triangle_vertices[:, 1] / depths,
                            )
                        )
                    if not np.all(np.isfinite(screen)):
                        raise ValueError(
                            "perspective projection produced non-finite pixel coordinates"
                        )
                    _raster_perspective_triangle(
                        canvas,
                        zbuffer,
                        screen,
                        depths,
                        triangle_uv,
                        atlas,
                        brightness,
                    )
    return Image.fromarray(canvas, mode="RGBA")


def _mask_pixels(mask: Image.Image, threshold: int, label: str) -> np.ndarray:
    """Return one explicit binary mask without cropping or inferred background."""
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= 255:
        raise ValueError("threshold must be an integer within 1..255")
    if "A" in mask.getbands() and mask.getchannel("A").getextrema()[0] < 255:
        values = np.asarray(mask.getchannel("A"), dtype=np.uint8)
    else:
        values = np.asarray(mask.convert("L"), dtype=np.uint8)
    result = values >= threshold
    if label == "reference" and not result.any():
        raise ValueError("reference mask is empty")
    return result


def aligned_mask_metrics(
    reference_mask: Image.Image,
    rendered_mask: Image.Image,
    *,
    threshold: int = 128,
) -> dict[str, Any]:
    """Compare two same-frame masks without fitting, scaling, or recentering."""
    if reference_mask.size != rendered_mask.size:
        raise ValueError("aligned masks must have identical image dimensions")
    reference = _mask_pixels(reference_mask, threshold, "reference")
    rendered = _mask_pixels(rendered_mask, threshold, "rendered")
    intersection = reference & rendered
    union = reference | rendered
    intersection_count = int(intersection.sum())
    reference_count = int(reference.sum())
    rendered_count = int(rendered.sum())
    reference_rows, reference_columns = np.where(reference)
    reference_bbox = [
        int(reference_columns.min()),
        int(reference_rows.min()),
        int(reference_columns.max()) + 1,
        int(reference_rows.max()) + 1,
    ]
    reference_edges = {
        "left": bool(reference[:, 0].any()),
        "top": bool(reference[0, :].any()),
        "right": bool(reference[:, -1].any()),
        "bottom": bool(reference[-1, :].any()),
    }
    return {
        "method": "raw-fixed-frame-mask-iou-v1",
        "alignment": "raw pixels; no crop, fit, scale, translation, or recentering",
        "image_size": list(reference_mask.size),
        "threshold": threshold,
        "reference_foreground_pixels": reference_count,
        "rendered_foreground_pixels": rendered_count,
        "reference_bbox": reference_bbox,
        "reference_touches_frame_edges": reference_edges,
        "reference_may_be_clipped": any(reference_edges.values()),
        "intersection_pixels": intersection_count,
        "union_pixels": int(union.sum()),
        "iou": round(intersection_count / max(1, int(union.sum())), 6),
        "recall": round(intersection_count / max(1, reference_count), 6),
        "precision": round(intersection_count / max(1, rendered_count), 6),
    }


def aligned_keypoint_metrics(
    reference_keypoints: Mapping[str, Sequence[float]],
    rendered_keypoints: Mapping[str, Sequence[float]],
    image_size: tuple[int, int],
    *,
    reference_subject_height: float,
) -> dict[str, Any]:
    """Score same-frame keypoints without moving either point set."""
    if set(reference_keypoints) != set(rendered_keypoints):
        raise ValueError("reference and rendered keypoint names must match")
    if not reference_keypoints:
        raise ValueError("at least one aligned keypoint is required")
    image_size = _image_size(image_size)
    if (
        isinstance(reference_subject_height, bool)
        or not isinstance(reference_subject_height, (int, float))
        or not math.isfinite(float(reference_subject_height))
        or float(reference_subject_height) <= 0
    ):
        raise ValueError("reference_subject_height must be a positive finite number")
    reference_subject_height = float(reference_subject_height)
    records = {}
    image_errors = []
    subject_errors = []
    for name in sorted(reference_keypoints):
        reference = _finite_tuple(reference_keypoints[name], 2, f"reference {name}")
        rendered = _finite_tuple(rendered_keypoints[name], 2, f"rendered {name}")
        delta = (rendered[0] - reference[0], rendered[1] - reference[1])
        error_pixels = math.hypot(*delta)
        image_normalized = error_pixels / image_size[1]
        subject_normalized = error_pixels / reference_subject_height
        image_errors.append(image_normalized)
        subject_errors.append(subject_normalized)
        records[name] = {
            "reference_pixels": [round(value, 6) for value in reference],
            "rendered_pixels": [round(value, 6) for value in rendered],
            "delta_pixels": [round(value, 6) for value in delta],
            "error_pixels": round(error_pixels, 6),
            "error_image_heights": round(image_normalized, 6),
            "error_subject_heights": round(subject_normalized, 6),
        }
    return {
        "method": "raw-fixed-frame-keypoint-error-v1",
        "alignment": "raw pixels; no crop, fit, scale, translation, or recentering",
        "normalization": (
            "raw Euclidean pixel distance divided by reference mask bounding-box height"
        ),
        "image_size": list(image_size),
        "reference_subject_height_pixels": reference_subject_height,
        "count": len(records),
        "mean_error_image_heights": round(sum(image_errors) / len(image_errors), 6),
        "maximum_error_image_heights": round(max(image_errors), 6),
        "mean_error_subject_heights": round(
            sum(subject_errors) / len(subject_errors), 6
        ),
        "maximum_error_subject_heights": round(max(subject_errors), 6),
        "points": records,
    }


def fixed_camera_perspective_evidence(
    spec: dict[str, Any],
    camera: PerspectiveCamera,
    reference_mask: Image.Image,
    *,
    reference_keypoints: Mapping[str, Sequence[float]] | None = None,
    world_keypoints: Mapping[str, Sequence[float]] | None = None,
    atlas_image: Image.Image | None = None,
    placements: dict[tuple[str, str], tuple[int, int, int, int]] | None = None,
    selected_names: set[str] | None = None,
    background: tuple[int, int, int, int] = (13, 20, 28, 255),
) -> tuple[Image.Image, dict[str, Any]]:
    """Render and score one estimated fixed camera without reconstructing shape."""
    if reference_mask.size != camera.image_size:
        raise ValueError("reference mask size must match camera.image_size")
    if (reference_keypoints is None) != (world_keypoints is None):
        raise ValueError("reference_keypoints and world_keypoints must be supplied together")
    rendered = render_perspective_view(
        spec,
        camera,
        atlas_image=atlas_image,
        placements=placements,
        selected_names=selected_names,
        background=background,
    )
    rendered_mask = foreground_mask(rendered, background[:3])
    silhouette = aligned_mask_metrics(reference_mask, rendered_mask)
    keypoints = None
    if reference_keypoints is not None and world_keypoints is not None:
        if set(reference_keypoints) != set(world_keypoints):
            raise ValueError("reference and world keypoint names must match")
        projected = {}
        for name in sorted(world_keypoints):
            point = project_perspective_point(camera, world_keypoints[name])
            if not point.in_front:
                raise ValueError(f"world keypoint is behind the near plane: {name}")
            assert point.pixel is not None
            projected[name] = point.pixel
        keypoints = aligned_keypoint_metrics(
            reference_keypoints,
            projected,
            camera.image_size,
            reference_subject_height=(
                silhouette["reference_bbox"][3] - silhouette["reference_bbox"][1]
            ),
        )
    report = {
        "schema_version": 1,
        "method": "fixed-camera-perspective-evidence-v1",
        "camera": camera.as_dict(),
        "camera_parameters_are_estimated": True,
        "visual_hull_used": False,
        "hidden_geometry_established": False,
        "alignment": "raw source pixels; no automatic fitting or recentering",
        "silhouette": silhouette,
        "keypoints": keypoints,
    }
    return rendered, report


def foreground_mask(
    image: Image.Image, background: tuple[int, int, int] = (13, 20, 28)
) -> Image.Image:
    """Extract foreground from a render with the standard solid background."""
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
    mask = np.any(pixels != np.asarray(background, dtype=np.uint8), axis=2)
    return Image.fromarray(mask.astype(np.uint8) * 255, mode="L")


def alpha_mask(image: Image.Image, *, threshold: int = 16) -> Image.Image:
    """Extract a silhouette from meaningful transparency without RGB guesses."""
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= 255:
        raise ValueError("alpha threshold must be an integer within 1..255")
    alpha = np.asarray(image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    if not np.any(alpha < 255):
        raise ValueError("image has no transparent pixels; provide a foreground mask")
    return Image.fromarray((alpha >= threshold).astype(np.uint8) * 255, mode="L")


def height_normalized_mask(
    mask: Image.Image,
    *,
    target_height: int = 496,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Crop and scale a mask by height while preserving its aspect ratio."""
    if (
        not isinstance(target_height, int)
        or isinstance(target_height, bool)
        or target_height < 8
    ):
        raise ValueError("target_height must be an integer of at least eight")
    pixels = np.asarray(mask.convert("L"), dtype=np.uint8) >= 128
    rows, columns = np.where(pixels)
    if not len(rows):
        raise ValueError("cannot normalize an empty silhouette")
    left = int(columns.min())
    top = int(rows.min())
    right = int(columns.max()) + 1
    bottom = int(rows.max()) + 1
    crop = pixels[top:bottom, left:right]
    scale = target_height / crop.shape[0]
    target_width = max(1, round(crop.shape[1] * scale))
    normalized = np.asarray(
        Image.fromarray(crop.astype(np.uint8) * 255, mode="L").resize(
            (target_width, target_height), Image.Resampling.NEAREST
        ),
        dtype=np.uint8,
    ) >= 128
    return normalized, {
        "bbox": [left, top, right, bottom],
        "source_width": int(crop.shape[1]),
        "source_height": int(crop.shape[0]),
        "normalized_width": target_width,
        "normalized_height": target_height,
        "scale": round(scale, 9),
        "touches_frame_edges": {
            "left": left == 0,
            "top": top == 0,
            "right": right == pixels.shape[1],
            "bottom": bottom == pixels.shape[0],
        },
    }


def _normalized_keypoint(
    point: Sequence[float], bounds: Sequence[int], label: str
) -> tuple[float, float]:
    """Express an image point relative to silhouette center and height."""
    if len(point) != 2 or not all(math.isfinite(float(value)) for value in point):
        raise ValueError(f"{label} must contain two finite numbers")
    left, top, right, bottom = (float(value) for value in bounds)
    height = bottom - top
    if height <= 0 or right <= left:
        raise ValueError(f"{label} silhouette bounds are degenerate")
    return (
        (float(point[0]) - (left + right) / 2) / height,
        (float(point[1]) - top) / height,
    )


def alpha_silhouette_metrics(
    reference: Image.Image,
    rendered: Image.Image,
    *,
    reference_keypoints: Mapping[str, Sequence[float]] | None = None,
    rendered_keypoints: Mapping[str, Sequence[float]] | None = None,
    rendered_background: tuple[int, int, int] = (13, 20, 28),
    alpha_threshold: int = 16,
    target_height: int = 496,
) -> dict[str, Any]:
    """Compare a transparent source and rendered silhouette at equal height.

    Optional named points are normalized by their own silhouette height and
    horizontal center before Euclidean error is measured. This keeps landmark
    scoring independent of source resolution and aspect ratio.
    """
    source_mask = alpha_mask(reference, threshold=alpha_threshold)
    model_mask = foreground_mask(rendered, background=rendered_background)
    source, source_transform = height_normalized_mask(
        source_mask, target_height=target_height
    )
    model, model_transform = height_normalized_mask(
        model_mask, target_height=target_height
    )
    padding = 8
    canvas_width = max(source.shape[1], model.shape[1]) + padding * 2

    def centered(mask: np.ndarray) -> np.ndarray:
        canvas = np.zeros((target_height, canvas_width), dtype=bool)
        left = (canvas_width - mask.shape[1]) // 2
        canvas[:, left : left + mask.shape[1]] = mask
        return canvas

    source_canvas = centered(source)
    model_canvas = centered(model)
    intersection = source_canvas & model_canvas
    union = source_canvas | model_canvas
    keypoint_report: dict[str, Any] | None = None
    if (reference_keypoints is None) != (rendered_keypoints is None):
        raise ValueError("reference and rendered keypoints must be supplied together")
    if reference_keypoints is not None and rendered_keypoints is not None:
        if set(reference_keypoints) != set(rendered_keypoints):
            raise ValueError("reference and rendered keypoint names must match")
        records = {}
        errors = []
        for name in sorted(reference_keypoints):
            source_point = _normalized_keypoint(
                reference_keypoints[name], source_transform["bbox"], f"reference {name}"
            )
            model_point = _normalized_keypoint(
                rendered_keypoints[name], model_transform["bbox"], f"rendered {name}"
            )
            error = math.dist(source_point, model_point)
            errors.append(error)
            records[name] = {
                "reference": [round(value, 6) for value in source_point],
                "rendered": [round(value, 6) for value in model_point],
                "error_subject_heights": round(error, 6),
            }
        keypoint_report = {
            "count": len(records),
            "mean_error_subject_heights": round(
                sum(errors) / max(1, len(errors)), 6
            ),
            "maximum_error_subject_heights": round(max(errors, default=0.0), 6),
            "points": records,
        }
    return {
        "method": "alpha-mask-aspect-preserving-height-normalized-centered-iou-v1",
        "alpha_threshold": alpha_threshold,
        "target_height": target_height,
        "iou": round(float(intersection.sum() / max(1, union.sum())), 6),
        "recall": round(float(intersection.sum() / max(1, source_canvas.sum())), 6),
        "precision": round(float(intersection.sum() / max(1, model_canvas.sum())), 6),
        "reference_aspect_ratio": round(source.shape[1] / source.shape[0], 6),
        "rendered_aspect_ratio": round(model.shape[1] / model.shape[0], 6),
        "reference_transform": source_transform,
        "rendered_transform": model_transform,
        "keypoints": keypoint_report,
        "source_touches_frame": any(source_transform["touches_frame_edges"].values()),
        "limitation": (
            "front alpha silhouette and annotated keypoints only; hidden-side geometry "
            "still requires multi-view inspection. A source touching the frame may contain "
            "clipped appendages, so IoU cannot establish their off-frame continuation."
        ),
    }


def bilateral_metrics(first: Image.Image, second: Image.Image) -> dict[str, float]:
    """Measure mirror silhouette and overlapping RGB consistency."""
    first_rgb = first.convert("RGB")
    second_rgb = ImageOps.mirror(second.convert("RGB"))
    first_mask = np.asarray(foreground_mask(first_rgb), dtype=np.uint8) >= 128
    second_mask = np.asarray(foreground_mask(second_rgb), dtype=np.uint8) >= 128
    intersection = first_mask & second_mask
    union = first_mask | second_mask
    first_pixels = np.asarray(first_rgb, dtype=np.int16)
    second_pixels = np.asarray(second_rgb, dtype=np.int16)
    mae = (
        float(np.abs(first_pixels[intersection] - second_pixels[intersection]).mean())
        if intersection.any() else 255.0
    )
    return {
        "silhouette_iou": round(
            float(np.count_nonzero(intersection) / max(1, np.count_nonzero(union))), 6
        ),
        "overlap_rgb_mae": round(mae, 4),
    }


def aabb_gap(spec: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> float:
    """Return shortest separation between rotated-cuboid world AABBs."""
    first_vertices = cube_vertices(spec, first)
    second_vertices = cube_vertices(spec, second)
    separation = np.maximum(
        0,
        np.maximum(
            first_vertices.min(axis=0) - second_vertices.max(axis=0),
            second_vertices.min(axis=0) - first_vertices.max(axis=0),
        ),
    )
    return float(np.linalg.norm(separation))


def contact_sheet(
    reference: Image.Image,
    views: dict[str, Image.Image],
    *,
    columns: int = 4,
    tile: tuple[int, int] = (300, 250),
) -> Image.Image:
    """Compose a labeled reference-plus-renders review sheet."""
    header = 38
    entries = [("reference", reference.convert("RGBA")), *views.items()]
    rows = math.ceil(len(entries) / columns)
    sheet = Image.new("RGB", (tile[0] * columns, (tile[1] + header) * rows), "#09111a")
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(entries):
        x = index % columns * tile[0]
        y = index // columns * (tile[1] + header)
        fitted = image.copy()
        fitted.thumbnail(tile, Image.Resampling.LANCZOS)
        panel = Image.new("RGBA", tile, "#0d141c")
        panel.alpha_composite(
            fitted,
            ((tile[0] - fitted.width) // 2, (tile[1] - fitted.height) // 2),
        )
        sheet.paste(panel.convert("RGB"), (x, y + header))
        draw.text(
            (x + 12, y + 10),
            name.upper().replace("_", " "),
            fill="#f0bd31",
            font=_font(17, bold=True),
        )
    return sheet
