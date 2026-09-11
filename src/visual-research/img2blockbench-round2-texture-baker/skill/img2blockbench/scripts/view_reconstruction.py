#!/usr/bin/env python3
"""Deterministic calibrated multi-view visual-hull reconstruction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from mesh_reconstruction import (
    _VoxelData,
    _adaptive_cuboids,
    _components,
    _palette,
    _six_neighbors,
)


ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VIEW_DUPLICATE_CORRELATION_THRESHOLD = 0.995
VIEW_DUPLICATE_NORMALIZED_MAE_THRESHOLD = 0.04


@dataclass(frozen=True)
class ViewReconstructionOptions:
    """Control calibrated silhouette carving and native cuboid fitting."""

    resolution: int = 32
    max_cuboids: int = 72
    target_size: float = 32.0
    palette_size: int = 16
    mask_threshold: int = 128
    min_component_voxels: int = 2
    min_component_fraction: float = 0.001
    geometry_precision: int = 64
    texture_density: int = 1


@dataclass(frozen=True)
class _CalibratedView:
    name: str
    image_path: Path
    mask_path: Path
    azimuth_degrees: float
    center_px: tuple[float, float]
    pixels_per_unit: float
    evidence_kind: str
    width: int
    height: int
    image: Any
    mask: Any
    image_sha256: str
    mask_sha256: str


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            "multi-view reconstruction requires numpy; install "
            "img2blockbench[mesh-reconstruction]"
        ) from exc
    return np


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_path(path: Path, output_path: Path) -> str:
    try:
        return path.resolve().relative_to(output_path.parent.resolve()).as_posix()
    except ValueError:
        return Path(
            os.path.relpath(path.resolve(), output_path.parent.resolve())
        ).as_posix()


def _finite_vector(value: Any, length: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label} must be a {length}-number array")
    if not all(
        isinstance(item, (int, float))
        and not isinstance(item, bool)
        and math.isfinite(float(item))
        for item in value
    ):
        raise ValueError(f"{label} must contain finite numbers")
    return tuple(float(item) for item in value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _load_mask(path: Path, expected_size: tuple[int, int], threshold: int) -> Any:
    np = _numpy()
    try:
        with Image.open(path) as opened:
            if opened.size != expected_size:
                raise ValueError(
                    f"mask {path} is {opened.size[0]}x{opened.size[1]}, expected "
                    f"{expected_size[0]}x{expected_size[1]}"
                )
            rgba = opened.convert("RGBA")
            alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
            if int(alpha.min()) < 255:
                values = alpha
            else:
                values = np.asarray(opened.convert("L"), dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"cannot read mask {path}: {exc}") from exc
    return values >= threshold


def image_content_similarity(
    first: Image.Image,
    second: Image.Image,
    *,
    first_mask: Image.Image | None = None,
    second_mask: Image.Image | None = None,
) -> dict[str, float | bool]:
    """Compare two frames after deterministic subject-aware normalization."""
    np = _numpy()
    if (first_mask is None) != (second_mask is None):
        raise ValueError("content masks must be supplied for both view images")

    def normalized_pixels(image: Image.Image, mask: Image.Image | None) -> Any:
        if image.width <= 0 or image.height <= 0:
            raise ValueError("view images must have positive dimensions")
        rgb = image.convert("RGB")
        feature_mask = None
        if mask is not None:
            if mask.size != image.size:
                raise ValueError("view image and content mask dimensions must match")
            feature_mask = mask.convert("L")
            bounds = feature_mask.getbbox()
            if bounds is None:
                raise ValueError("view content mask cannot be empty")
            rgb = rgb.crop(bounds)
            feature_mask = feature_mask.crop(bounds)
        rgb = rgb.resize(
            (96, 96), Image.Resampling.BILINEAR
        )
        pixels = np.asarray(rgb, dtype=np.float64) / 255.0
        if feature_mask is None:
            return pixels.reshape(-1)
        mask_values = np.asarray(
            feature_mask.resize((96, 96), Image.Resampling.BILINEAR),
            dtype=np.float64,
        ) / 255.0
        pixels = pixels * mask_values[:, :, None] + 0.5 * (
            1.0 - mask_values[:, :, None]
        )
        return np.concatenate((pixels.reshape(-1), mask_values.reshape(-1)))

    first_pixels = normalized_pixels(first, first_mask)
    second_pixels = normalized_pixels(second, second_mask)
    first_centered = first_pixels - float(first_pixels.mean())
    second_centered = second_pixels - float(second_pixels.mean())
    denominator = float(
        np.linalg.norm(first_centered) * np.linalg.norm(second_centered)
    )
    normalized_mae = float(np.mean(np.abs(first_pixels - second_pixels)))
    if denominator <= 1e-12:
        correlation = 1.0 if normalized_mae <= 1e-12 else 0.0
    else:
        correlation = float(
            np.dot(first_centered, second_centered) / denominator
        )
    correlation = max(-1.0, min(1.0, correlation))
    return {
        "rgb_correlation": round(correlation, 6),
        "normalized_mean_absolute_error": round(normalized_mae, 6),
        "near_duplicate": (
            correlation >= VIEW_DUPLICATE_CORRELATION_THRESHOLD
            and normalized_mae <= VIEW_DUPLICATE_NORMALIZED_MAE_THRESHOLD
        ),
    }


def _view_content_similarity(
    first: _CalibratedView,
    second: _CalibratedView,
) -> dict[str, float | bool]:
    return image_content_similarity(
        Image.fromarray(first.image),
        Image.fromarray(second.image),
        first_mask=Image.fromarray(first.mask.astype("uint8") * 255),
        second_mask=Image.fromarray(second.mask.astype("uint8") * 255),
    )


def _axis_constraints(views: list[_CalibratedView]) -> dict[str, Any]:
    np = _numpy()
    observed = [view for view in views if view.evidence_kind == "observed"]

    def summarize(selected: list[_CalibratedView]) -> tuple[int, list[float], float]:
        axes = sorted(float(view.azimuth_degrees % 180.0) for view in selected)
        unique: list[float] = []
        for value in axes:
            if not unique or abs(value - unique[-1]) > 1e-7:
                unique.append(value)
        if not selected:
            return 0, unique, 180.0
        matrix = np.asarray(
            [
                (
                    math.cos(math.radians(view.azimuth_degrees)),
                    -math.sin(math.radians(view.azimuth_degrees)),
                )
                for view in selected
            ],
            dtype=np.float64,
        )
        singular = np.linalg.svd(matrix, compute_uv=False)
        rank = int(sum(float(value) > 1e-7 for value in singular))
        if len(unique) <= 1:
            largest_gap = 180.0
        else:
            gaps = [
                unique[index + 1] - unique[index]
                for index in range(len(unique) - 1)
            ]
            gaps.append(unique[0] + 180.0 - unique[-1])
            largest_gap = max(gaps)
        return rank, unique, largest_gap

    rank_all, unique_all, largest_gap_all = summarize(views)
    rank_observed, unique_observed, largest_gap_observed = summarize(observed)

    parents = {view.name: view.name for view in observed}

    def find(name: str) -> str:
        while parents[name] != name:
            parents[name] = parents[parents[name]]
            name = parents[name]
        return name

    def union(first: str, second: str) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        parents[max(first_root, second_root)] = min(first_root, second_root)

    duplicate_pairs: list[dict[str, Any]] = []
    for index, first in enumerate(observed):
        for second in observed[index + 1 :]:
            similarity = _view_content_similarity(first, second)
            if not similarity["near_duplicate"]:
                continue
            union(first.name, second.name)
            duplicate_pairs.append(
                {
                    "views": [first.name, second.name],
                    **similarity,
                }
            )

    grouped: dict[str, list[str]] = {}
    for view in observed:
        grouped.setdefault(find(view.name), []).append(view.name)
    content_groups = sorted(
        (sorted(names) for names in grouped.values()),
        key=lambda names: names[0],
    )
    observed_by_name = {view.name: view for view in observed}
    independent_observed = [
        observed_by_name[names[0]] for names in content_groups
    ]
    (
        independent_rank,
        independent_axes,
        independent_largest_gap,
    ) = summarize(independent_observed)
    return {
        "coordinate_plane": "canonical x-z",
        "horizontal_constraint_rank_all": rank_all,
        "horizontal_constraint_rank_observed": rank_observed,
        "unique_unoriented_yaw_axes_degrees_all": [
            round(value, 6) for value in unique_all
        ],
        "unique_unoriented_yaw_axes_degrees_observed": [
            round(value, 6) for value in unique_observed
        ],
        "largest_unobserved_yaw_gap_degrees_all": round(largest_gap_all, 6),
        "largest_unobserved_yaw_gap_degrees_observed": round(
            largest_gap_observed, 6
        ),
        "content_independence_method": (
            "mask-cropped RGB plus silhouette normalized to 96x96; near duplicates require "
            f"correlation >= {VIEW_DUPLICATE_CORRELATION_THRESHOLD} and normalized "
            f"MAE <= {VIEW_DUPLICATE_NORMALIZED_MAE_THRESHOLD}"
        ),
        "observed_content_groups": content_groups,
        "duplicate_observed_view_pairs": duplicate_pairs,
        "independent_observed_view_count": len(independent_observed),
        "horizontal_constraint_rank_observed_independent_content": independent_rank,
        "unique_unoriented_yaw_axes_degrees_observed_independent_content": [
            round(value, 6) for value in independent_axes
        ],
        "largest_unobserved_yaw_gap_degrees_observed_independent_content": round(
            independent_largest_gap, 6
        ),
        "observed_view_count": len(observed),
        "synthetic_proxy_view_count": len(views) - len(observed),
        "vertical_axis": "constrained by every silhouette",
        "camera_elevation": "not represented by orthographic-yaw calibration",
    }


def _load_manifest(
    manifest_path: Path,
    threshold: int,
) -> tuple[dict[str, Any], Any, Any, list[_CalibratedView], dict[str, Any]]:
    np = _numpy()
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise ValueError("view manifest schema_version must be 1")
    calibration = manifest.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("view manifest calibration must be an object")
    if calibration.get("projection") != "orthographic-yaw":
        raise ValueError("calibration.projection must be 'orthographic-yaw'")
    bounds = calibration.get("volume_bounds")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("calibration.volume_bounds must contain lower and upper vectors")
    lower = np.asarray(_finite_vector(bounds[0], 3, "volume_bounds lower"))
    upper = np.asarray(_finite_vector(bounds[1], 3, "volume_bounds upper"))
    if not bool(np.all(upper > lower)):
        raise ValueError("volume_bounds upper values must exceed lower values")

    entries = manifest.get("views")
    if not isinstance(entries, list) or not 2 <= len(entries) <= 24:
        raise ValueError("view manifest must contain 2..24 calibrated views")
    names: set[str] = set()
    views: list[_CalibratedView] = []
    for index, entry in enumerate(entries):
        label = f"views[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object")
        name = entry.get("id")
        if not isinstance(name, str) or not ID_RE.fullmatch(name):
            raise ValueError(f"{label}.id is invalid")
        if name in names:
            raise ValueError(f"duplicate view id: {name}")
        names.add(name)
        image_value = entry.get("image")
        mask_value = entry.get("mask")
        if not isinstance(image_value, str) or not image_value:
            raise ValueError(f"{label}.image is required")
        if not isinstance(mask_value, str) or not mask_value:
            raise ValueError(f"{label}.mask is required; masks are never inferred")
        evidence_kind = entry.get("evidence_kind")
        if evidence_kind not in {"observed", "synthetic_proxy"}:
            raise ValueError(
                f"{label}.evidence_kind must be 'observed' or 'synthetic_proxy'"
            )
        image_path = (manifest_path.parent / image_value).resolve()
        mask_path = (manifest_path.parent / mask_value).resolve()
        try:
            with Image.open(image_path) as opened:
                rgba = opened.convert("RGBA")
                width, height = rgba.size
                image = np.asarray(rgba, dtype=np.uint8).copy()
        except OSError as exc:
            raise ValueError(f"cannot read view image {image_path}: {exc}") from exc
        mask = _load_mask(mask_path, (width, height), threshold)
        if not bool(mask.any()):
            raise ValueError(f"{label}.mask is empty")
        if bool(mask.all()):
            raise ValueError(f"{label}.mask is full-frame and does not constrain a hull")
        azimuth = entry.get("azimuth_degrees")
        if not isinstance(azimuth, (int, float)) or isinstance(azimuth, bool):
            raise ValueError(f"{label}.azimuth_degrees must be finite")
        azimuth = float(azimuth)
        if not math.isfinite(azimuth):
            raise ValueError(f"{label}.azimuth_degrees must be finite")
        center = _finite_vector(entry.get("center_px"), 2, f"{label}.center_px")
        pixels_per_unit = entry.get("pixels_per_unit")
        if (
            not isinstance(pixels_per_unit, (int, float))
            or isinstance(pixels_per_unit, bool)
            or not math.isfinite(float(pixels_per_unit))
            or float(pixels_per_unit) <= 0
        ):
            raise ValueError(f"{label}.pixels_per_unit must be positive and finite")
        views.append(
            _CalibratedView(
                name=name,
                image_path=image_path,
                mask_path=mask_path,
                azimuth_degrees=azimuth,
                center_px=(center[0], center[1]),
                pixels_per_unit=float(pixels_per_unit),
                evidence_kind=evidence_kind,
                width=width,
                height=height,
                image=image,
                mask=mask,
                image_sha256=_sha256(image_path),
                mask_sha256=_sha256(mask_path),
            )
        )
    views.sort(key=lambda view: view.name)
    reference_view = manifest.get("reference_view", views[0].name)
    if reference_view not in names:
        raise ValueError("reference_view must name one of the calibrated views")
    constraints = _axis_constraints(views)
    if constraints["horizontal_constraint_rank_all"] < 2:
        raise ValueError(
            "orthographic-yaw visual hull is depth-underconstrained; provide at "
            "least two non-parallel azimuth axes"
        )
    return manifest, lower, upper, views, constraints


def _project_points(points: Any, view: _CalibratedView) -> tuple[Any, Any, Any]:
    np = _numpy()
    angle = math.radians(view.azimuth_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    horizontal = points[:, 0] * cosine - points[:, 2] * sine
    depth = points[:, 0] * sine + points[:, 2] * cosine
    u = view.center_px[0] + horizontal * view.pixels_per_unit
    v = view.center_px[1] - points[:, 1] * view.pixels_per_unit
    return np.asarray(u), np.asarray(v), np.asarray(depth)


def _surface(occupancy: Any) -> Any:
    np = _numpy()
    interior = occupancy.copy()
    for axis in range(3):
        lower_neighbor = np.zeros_like(occupancy)
        upper_neighbor = np.zeros_like(occupancy)
        lower_slice = [slice(None)] * 3
        upper_slice = [slice(None)] * 3
        lower_slice[axis] = slice(1, None)
        upper_slice[axis] = slice(None, -1)
        lower_neighbor[tuple(lower_slice)] = occupancy[tuple(upper_slice)]
        upper_neighbor[tuple(upper_slice)] = occupancy[tuple(lower_slice)]
        interior &= lower_neighbor & upper_neighbor
    return occupancy & ~interior


def _carve(
    lower: Any,
    upper: Any,
    views: list[_CalibratedView],
    options: ViewReconstructionOptions,
) -> tuple[_VoxelData, dict[str, Any]]:
    np = _numpy()
    extents = upper - lower
    pitch = float(extents.max()) / options.resolution
    dimensions = np.maximum(1, np.ceil(extents / pitch - 1e-12).astype(np.int64))
    shape = tuple(int(value) for value in dimensions)
    indexes = np.indices(shape, dtype=np.float64).reshape(3, -1).T
    points = lower + (indexes + 0.5) * pitch
    occupancy_flat = np.ones(len(points), dtype=bool)
    per_view_samples: dict[str, int] = {}
    for view in views:
        u, v, _ = _project_points(points, view)
        x = np.rint(u).astype(np.int64)
        y = np.rint(v).astype(np.int64)
        inside = (x >= 0) & (x < view.width) & (y >= 0) & (y < view.height)
        accepted = np.zeros(len(points), dtype=bool)
        selected = np.flatnonzero(inside)
        accepted[selected] = view.mask[y[selected], x[selected]]
        occupancy_flat &= accepted
        per_view_samples[view.name] = int(accepted.sum())
    occupancy = occupancy_flat.reshape(shape)
    if not occupancy.any():
        raise ValueError(
            "calibrated silhouette intersection is empty; check masks, centers, "
            "scale, azimuths, and volume bounds"
        )
    raw_voxels = int(occupancy.sum())
    raw_components = _components(occupancy)
    threshold = max(
        options.min_component_voxels,
        math.ceil(raw_voxels * options.min_component_fraction),
    )
    retained = [component for component in raw_components if len(component) >= threshold]
    if not retained:
        retained = [raw_components[0]]
    if len(retained) > options.max_cuboids:
        retained = retained[: options.max_cuboids]
    cleaned = np.zeros(shape, dtype=bool)
    labels = np.full(shape, -1, dtype=np.int32)
    for component_index, component in enumerate(retained):
        coordinates = tuple(zip(*component))
        cleaned[coordinates] = True
        labels[coordinates] = component_index

    colors, color_report = _fuse_visible_colors(
        cleaned, lower, pitch, views
    )
    report = {
        "method": "order-independent intersection of calibrated silhouette cones",
        "grid_dimensions": list(shape),
        "voxel_pitch_source_units": round(pitch, 9),
        "candidate_voxels": int(math.prod(shape)),
        "per_view_inside_samples": per_view_samples,
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
        "color_fusion": color_report,
    }
    return (
        _VoxelData(
            occupancy=cleaned,
            raw_surface=_surface(cleaned),
            colors=colors,
            component_labels=labels,
            lower=lower,
            pitch=pitch,
            report=report,
        ),
        report,
    )


def _fuse_visible_colors(
    occupancy: Any,
    lower: Any,
    pitch: float,
    views: list[_CalibratedView],
) -> tuple[Any, dict[str, Any]]:
    np = _numpy()
    coordinates = np.argwhere(occupancy)
    points = lower + (coordinates.astype(np.float64) + 0.5) * pitch
    sums_by_kind = {
        kind: np.zeros(occupancy.shape + (3,), dtype=np.uint64)
        for kind in ("observed", "synthetic_proxy")
    }
    counts_by_kind = {
        kind: np.zeros(occupancy.shape, dtype=np.uint16)
        for kind in ("observed", "synthetic_proxy")
    }
    visible_by_view: dict[str, int] = {}
    visible_by_evidence_kind: Counter[str] = Counter()
    visible_union_by_evidence_kind = {
        kind: np.zeros(occupancy.shape, dtype=bool)
        for kind in ("observed", "synthetic_proxy")
    }
    for view in views:
        u, v, depth = _project_points(points, view)
        x = np.rint(u).astype(np.int64)
        y = np.rint(v).astype(np.int64)
        pixel_keys = y.astype(np.int64) * view.width + x
        order = np.lexsort((-depth, pixel_keys))
        ordered_keys = pixel_keys[order]
        first = np.empty(len(order), dtype=bool)
        first[0] = True
        first[1:] = ordered_keys[1:] != ordered_keys[:-1]
        selected = order[first]
        selected_coordinates = coordinates[selected]
        selected_index = tuple(selected_coordinates.T)
        sampled = view.image[y[selected], x[selected], :3].astype(np.uint64)
        sums_by_kind[view.evidence_kind][selected_index] += sampled
        counts_by_kind[view.evidence_kind][selected_index] += 1
        visible_by_view[view.name] = len(selected)
        visible_by_evidence_kind[view.evidence_kind] += len(selected)
        visible_union_by_evidence_kind[view.evidence_kind][selected_index] = True

    observed = occupancy & (counts_by_kind["observed"] > 0)
    proxy = occupancy & (counts_by_kind["synthetic_proxy"] > 0)
    proxy_only = proxy & ~observed
    colored = observed | proxy_only
    colors = np.zeros(occupancy.shape + (3,), dtype=np.uint8)
    colors[observed] = np.clip(
        np.rint(
            sums_by_kind["observed"][observed]
            / counts_by_kind["observed"][observed, None]
        ),
        0,
        255,
    ).astype(np.uint8)
    colors[proxy_only] = np.clip(
        np.rint(
            sums_by_kind["synthetic_proxy"][proxy_only]
            / counts_by_kind["synthetic_proxy"][proxy_only, None]
        ),
        0,
        255,
    ).astype(np.uint8)
    queue: deque[tuple[int, int, int]] = deque(
        tuple(int(value) for value in point) for point in np.argwhere(colored)
    )
    assigned = colored.copy()
    if not queue:
        raise ValueError("no occupied voxel is visible in calibrated input views")
    while queue:
        point = queue.popleft()
        for neighbor in _six_neighbors(point, occupancy.shape):
            if occupancy[neighbor] and not assigned[neighbor]:
                colors[neighbor] = colors[point]
                assigned[neighbor] = True
                queue.append(neighbor)
    visible_voxels = int(colored.sum())
    return colors, {
        "method": (
            "frontmost observed samples averaged; proxy samples used only where "
            "no observed sample exists; then nearest 6-connected fill"
        ),
        "view_order": [view.name for view in views],
        "visible_samples_by_view": visible_by_view,
        "visible_sample_contributions_by_evidence_kind": {
            kind: int(visible_by_evidence_kind[kind])
            for kind in ("observed", "synthetic_proxy")
        },
        "directly_colored_voxels_by_evidence_kind": {
            kind: int(visible_union_by_evidence_kind[kind].sum())
            for kind in ("observed", "synthetic_proxy")
        },
        "exclusive_direct_color_attribution": {
            "observed_only": int((observed & ~proxy).sum()),
            "synthetic_proxy_only": int(proxy_only.sum()),
            "both_observed_and_proxy": int((observed & proxy).sum()),
            "union": int(colored.sum()),
        },
        "color_precedence": "observed samples take precedence over synthetic proxies",
        "directly_colored_voxels": visible_voxels,
        "hidden_color_fill_voxels": int(occupancy.sum()) - visible_voxels,
        "hidden_color_claim": (
            "Filled colors are nearest visible-surface propagation, not observations"
        ),
    }


def _project_occupancy(
    occupancy: Any,
    lower: Any,
    pitch: float,
    view: _CalibratedView,
) -> Any:
    np = _numpy()
    canvas = Image.new("L", (view.width, view.height), 0)
    draw = ImageDraw.Draw(canvas)
    angle = math.radians(view.azimuth_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    coordinates = np.argwhere(occupancy)
    centers = lower + (coordinates.astype(np.float64) + 0.5) * pitch
    u, v, _ = _project_points(centers, view)
    half_width = (
        pitch * (abs(cosine) + abs(sine)) * view.pixels_per_unit / 2
    )
    half_height = pitch * view.pixels_per_unit / 2
    rectangles = zip(
        np.floor(u - half_width).astype(np.int64),
        np.floor(v - half_height).astype(np.int64),
        np.ceil(u + half_width).astype(np.int64),
        np.ceil(v + half_height).astype(np.int64),
    )
    for left, top, right, bottom in rectangles:
        draw.rectangle(
            (int(left), int(top), int(right), int(bottom)),
            fill=255,
        )
    return np.asarray(canvas, dtype=np.uint8) >= 128


def _silhouette_metrics(
    views: list[_CalibratedView],
    carved: Any,
    fitted: Any,
    lower: Any,
    pitch: float,
) -> dict[str, Any]:
    np = _numpy()
    output: dict[str, Any] = {}
    for view in views:
        source = view.mask
        carved_projection = _project_occupancy(carved, lower, pitch, view)
        fitted_projection = _project_occupancy(fitted, lower, pitch, view)

        def metrics(candidate: Any) -> dict[str, float | int]:
            intersection = int((source & candidate).sum())
            union = int((source | candidate).sum())
            source_count = int(source.sum())
            candidate_count = int(candidate.sum())
            return {
                "iou": round(intersection / max(1, union), 6),
                "source_coverage": round(intersection / max(1, source_count), 6),
                "model_precision": round(intersection / max(1, candidate_count), 6),
                "model_pixels": candidate_count,
            }

        output[view.name] = {
            "source_pixels": int(source.sum()),
            "carved_visual_hull": metrics(carved_projection),
            "fitted_cuboids": metrics(fitted_projection),
        }
    return output


def _rgb_hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _adjusted_hex(color: tuple[int, int, int], factor: float) -> str:
    return _rgb_hex(
        tuple(max(0, min(255, round(value * factor))) for value in color)
    )


def reconstruct_view_spec(
    manifest_path: Path,
    output_path: Path,
    model_id: str,
    description: str,
    subject_type: str,
    options: ViewReconstructionOptions,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct explicitly calibrated yaw silhouettes as a visual hull."""
    np = _numpy()
    if not ID_RE.fullmatch(model_id):
        raise ValueError("id must match [a-z0-9][a-z0-9_-]{0,63}")
    if not 8 <= options.resolution <= 96:
        raise ValueError("resolution must be within 8..96")
    if not 1 <= options.max_cuboids <= 96:
        raise ValueError("max_cuboids must be within 1..96")
    if not 4 <= options.palette_size <= 64:
        raise ValueError("palette_size must be within 4..64")
    if not 1 <= options.mask_threshold <= 255:
        raise ValueError("mask_threshold must be within 1..255")
    if options.min_component_voxels < 1:
        raise ValueError("min_component_voxels must be positive")
    if not 0 <= options.min_component_fraction <= 1:
        raise ValueError("min_component_fraction must be within 0..1")
    if options.target_size <= 0:
        raise ValueError("target_size must be positive")
    if not 1 <= options.geometry_precision <= 256:
        raise ValueError("geometry_precision must be within 1..256")
    if options.texture_density not in {1, 2, 4}:
        raise ValueError("texture_density must be 1, 2, or 4")

    manifest, lower, upper, views, constraints = _load_manifest(
        manifest_path, options.mask_threshold
    )
    voxels, voxel_report = _carve(lower, upper, views, options)
    palette, material_labels = _palette(
        voxels.colors, voxels.occupancy, options.palette_size
    )
    leaves, fit_report, fitted_occupancy = _adaptive_cuboids(
        voxels, material_labels, options.max_cuboids
    )
    per_view_metrics = _silhouette_metrics(
        views,
        voxels.occupancy,
        fitted_occupancy,
        voxels.lower,
        voxels.pitch,
    )

    extents = voxels.pitch * np.asarray(voxels.occupancy.shape, dtype=np.float64)
    scale = options.target_size / float(extents.max())
    center_x = float(voxels.lower[0] + extents[0] / 2)
    center_z = float(voxels.lower[2] + extents[2] / 2)
    ground_y = float(voxels.lower[1])
    model_extents = [float(value * scale) for value in extents]

    materials: dict[str, Any] = {}
    for index, color in enumerate(palette):
        materials[f"views_{index:02d}"] = {
            "base": _rgb_hex(color),
            "shade": _adjusted_hex(color, 0.62),
            "highlight": _adjusted_hex(color, 1.18),
            "pattern": "solid",
            "pattern_scale": 1,
        }

    cubes: list[dict[str, Any]] = []
    face_overrides = 0
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
                int(material_labels[tuple(point)]) for point in boundary_points
            )
            face_material = min(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[0]
            if face_material != leaf.material:
                faces[face] = {"material": f"views_{face_material:02d}"}
                face_overrides += 1
        cubes.append(
            {
                "name": f"view_c{leaf.component + 1:02d}_{index:03d}",
                "bone": "root",
                "center": [round(float(value), 6) for value in center],
                "size": [round(float(value), 6) for value in size],
                "rotation": [0, 0, 0],
                "origin": [0, 0, 0],
                "role": f"visual hull component {leaf.component + 1}",
                "material": f"views_{leaf.material:02d}",
                "faces": faces,
            }
        )

    reference_name = manifest.get("reference_view", views[0].name)
    reference_view = next(view for view in views if view.name == reference_name)
    view_evidence = [
        {
            "id": view.name,
            "image": _relative_path(view.image_path, output_path),
            "image_sha256": view.image_sha256,
            "mask": _relative_path(view.mask_path, output_path),
            "mask_sha256": view.mask_sha256,
            "dimensions": [view.width, view.height],
            "azimuth_degrees": round(view.azimuth_degrees, 9),
            "center_px": [round(value, 9) for value in view.center_px],
            "pixels_per_unit": round(view.pixels_per_unit, 9),
            "evidence_kind": view.evidence_kind,
        }
        for view in views
    ]
    hidden_geometry = {
        "method": "silhouette visual hull; no depth was estimated or claimed",
        "cannot_recover": [
            "concavities that do not alter any supplied silhouette",
            "occluded or never-visible surface markings",
            "top and bottom surface shape without elevated views",
            "semantic anatomy, articulation, or internal structure",
        ],
        "color_disclosure": voxel_report["color_fusion"]["hidden_color_claim"],
        "hidden_geometry_established_from_observed_views": (
            constraints[
                "horizontal_constraint_rank_observed_independent_content"
            ]
            >= 2
        ),
        "proxy_disclosure": (
            "Synthetic-proxy masks constrain the generated visual hull but do not "
            "establish that hidden geometry was observed"
        ),
    }
    report = {
        "schema_version": 1,
        "algorithm": "calibrated-orthographic-yaw-visual-hull-cuboids-v1",
        "manifest": {
            "path": _relative_path(manifest_path, output_path),
            "sha256": _sha256(manifest_path),
            "projection": "orthographic-yaw",
            "volume_bounds": [
                [round(float(value), 9) for value in lower],
                [round(float(value), 9) for value in upper],
            ],
            "reference_view": reference_name,
        },
        "views": view_evidence,
        "axis_constraints": constraints,
        "voxelization": voxel_report,
        "cuboid_fit": fit_report,
        "per_view_silhouette": per_view_metrics,
        "color_transfer": {
            **voxel_report["color_fusion"],
            "palette": [_rgb_hex(color) for color in palette],
            "palette_entries": len(palette),
            "face_material_overrides": face_overrides,
        },
        "hidden_geometry": hidden_geometry,
        "hidden_geometry_established_from_observed_views": hidden_geometry[
            "hidden_geometry_established_from_observed_views"
        ],
    }
    spec = {
        "schema_version": 1,
        "id": model_id,
        "reference": {
            "image": _relative_path(reference_view.image_path, output_path),
            "sha256": reference_view.image_sha256,
            "width": reference_view.width,
            "height": reference_view.height,
        },
        "subject": {
            "type": subject_type,
            "description": description,
            "symmetry": "none",
            "uncertainties": hidden_geometry["cannot_recover"],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [1, options.max_cuboids],
            "identity_features": [
                "intersection of every calibrated silhouette",
                "visible-color fusion from caller-labeled azimuths",
            ],
            "required_views": [view.name for view in views] + ["isometric"],
            "review_targets": [
                "per-view silhouette",
                "hidden-volume ambiguity",
                "color fusion",
                "components",
            ],
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
            "lane": "calibrated-multiview-visual-hull",
            "algorithm": report["algorithm"],
            "manifest": report["manifest"],
            "views": view_evidence,
            "axis_constraints": constraints,
            "voxelization": voxel_report,
            "cuboid_fit": fit_report,
            "per_view_silhouette": per_view_metrics,
            "hidden_geometry": hidden_geometry,
            "hidden_geometry_established_from_observed_views": hidden_geometry[
                "hidden_geometry_established_from_observed_views"
            ],
        },
    }
    return spec, report


def extract_clip_view_manifest(
    clip_path: Path,
    samples_path: Path,
    output_path: Path,
    frames_dir: Path,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Any]:
    """Extract caller-timestamped frames without estimating camera motion."""
    if not clip_path.is_file():
        raise ValueError(f"clip not found: {clip_path}")
    request = _read_json(samples_path)
    if request.get("schema_version") != 1:
        raise ValueError("clip sample request schema_version must be 1")
    calibration = request.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("clip sample request calibration must be an object")
    if calibration.get("projection") != "orthographic-yaw":
        raise ValueError("clip calibration.projection must be 'orthographic-yaw'")
    bounds = calibration.get("volume_bounds")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("clip calibration.volume_bounds is required")
    lower = _finite_vector(bounds[0], 3, "volume_bounds lower")
    upper = _finite_vector(bounds[1], 3, "volume_bounds upper")
    if not all(high > low for low, high in zip(lower, upper)):
        raise ValueError("volume_bounds upper values must exceed lower values")
    samples = request.get("samples")
    if not isinstance(samples, list) or not 2 <= len(samples) <= 24:
        raise ValueError("clip sample request must contain 2..24 samples")

    parsed: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, sample in enumerate(samples):
        label = f"samples[{index}]"
        if not isinstance(sample, dict):
            raise ValueError(f"{label} must be an object")
        name = sample.get("id")
        if not isinstance(name, str) or not ID_RE.fullmatch(name):
            raise ValueError(f"{label}.id is invalid")
        if name in names:
            raise ValueError(f"duplicate sample id: {name}")
        names.add(name)
        timestamp = sample.get("timestamp_seconds")
        azimuth = sample.get("azimuth_degrees")
        if (
            not isinstance(timestamp, (int, float))
            or isinstance(timestamp, bool)
            or not math.isfinite(float(timestamp))
            or float(timestamp) < 0
        ):
            raise ValueError(f"{label}.timestamp_seconds must be non-negative and finite")
        if (
            not isinstance(azimuth, (int, float))
            or isinstance(azimuth, bool)
            or not math.isfinite(float(azimuth))
        ):
            raise ValueError(f"{label}.azimuth_degrees must be finite and explicit")
        center = _finite_vector(sample.get("center_px"), 2, f"{label}.center_px")
        pixels_per_unit = sample.get("pixels_per_unit")
        if (
            not isinstance(pixels_per_unit, (int, float))
            or isinstance(pixels_per_unit, bool)
            or not math.isfinite(float(pixels_per_unit))
            or float(pixels_per_unit) <= 0
        ):
            raise ValueError(f"{label}.pixels_per_unit must be positive and finite")
        mask_value = sample.get("mask")
        if not isinstance(mask_value, str) or not mask_value:
            raise ValueError(
                f"{label}.mask is required; extraction does not invent segmentation"
            )
        mask_path = (samples_path.parent / mask_value).resolve()
        try:
            with Image.open(mask_path) as opened:
                mask_size = opened.size
                mask_values = _numpy().asarray(opened.convert("L"), dtype=_numpy().uint8)
        except OSError as exc:
            raise ValueError(f"cannot read {label}.mask {mask_path}: {exc}") from exc
        if not bool((mask_values >= 128).any()):
            raise ValueError(f"{label}.mask is empty")
        if bool((mask_values >= 128).all()):
            raise ValueError(f"{label}.mask is full-frame and does not constrain a hull")
        evidence_kind = sample.get("evidence_kind")
        if evidence_kind not in {"observed", "synthetic_proxy"}:
            raise ValueError(
                f"{label}.evidence_kind must be 'observed' or 'synthetic_proxy'"
            )
        parsed.append(
            {
                "id": name,
                "timestamp_seconds": float(timestamp),
                "azimuth_degrees": float(azimuth),
                "center_px": center,
                "pixels_per_unit": float(pixels_per_unit),
                "mask_path": mask_path,
                "mask_size": mask_size,
                "evidence_kind": evidence_kind,
            }
        )
    parsed.sort(key=lambda value: value["id"])
    reference_view = request.get("reference_view", parsed[0]["id"])
    if reference_view not in names:
        raise ValueError("reference_view must name one of the clip samples")
    yaws = [float(value["azimuth_degrees"]) for value in parsed]
    if not any(
        abs(math.sin(math.radians(first - second))) > 1e-7
        for index, first in enumerate(yaws)
        for second in yaws[index + 1 :]
    ):
        raise ValueError(
            "clip samples are depth-underconstrained; provide at least two "
            "non-parallel azimuth axes"
        )
    executable = shutil.which(ffmpeg)
    if executable is None:
        raise ValueError(f"ffmpeg executable not found: {ffmpeg}")
    frames_dir.mkdir(parents=True, exist_ok=True)
    views: list[dict[str, Any]] = []
    for sample in parsed:
        frame = frames_dir / f"{sample['id']}.png"
        command = [
            executable,
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(clip_path.resolve()),
            "-ss",
            format(sample["timestamp_seconds"], ".9f").rstrip("0").rstrip("."),
            "-map_metadata",
            "-1",
            "-frames:v",
            "1",
            "-vf",
            "format=rgba",
            str(frame.resolve()),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or str(exc)).strip()
            raise ValueError(
                f"ffmpeg failed for sample {sample['id']}: {message}"
            ) from exc
        if not frame.is_file():
            raise ValueError(f"ffmpeg did not create frame: {frame}")
        try:
            with Image.open(frame) as opened:
                opened.load()
                frame_size = opened.size
        except OSError as exc:
            raise ValueError(
                f"ffmpeg created an unreadable frame for {sample['id']}: {exc}"
            ) from exc
        if frame_size != sample["mask_size"]:
            raise ValueError(
                f"extracted frame {sample['id']} is {frame_size[0]}x{frame_size[1]}, "
                f"but its mask is {sample['mask_size'][0]}x{sample['mask_size'][1]}"
            )
        views.append(
            {
                "id": sample["id"],
                "image": _relative_path(frame, output_path),
                "mask": _relative_path(sample["mask_path"], output_path),
                "timestamp_seconds": sample["timestamp_seconds"],
                "azimuth_degrees": sample["azimuth_degrees"],
                "center_px": list(sample["center_px"]),
                "pixels_per_unit": sample["pixels_per_unit"],
                "evidence_kind": sample["evidence_kind"],
            }
        )
    manifest = {
        "schema_version": 1,
        "calibration": calibration,
        "reference_view": reference_view,
        "views": views,
        "clip_provenance": {
            "path": _relative_path(clip_path, output_path),
            "sha256": _sha256(clip_path),
            "sample_request": _relative_path(samples_path, output_path),
            "sample_request_sha256": _sha256(samples_path),
            "camera_motion": "not inferred; every timestamp and azimuth is caller supplied",
            "ffmpeg_executable": Path(executable).name,
            "extracted_frames": len(views),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_name(f".{output_path.name}.tmp")
    temporary_output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        _load_manifest(temporary_output, 128)
        os.replace(temporary_output, output_path)
    finally:
        if temporary_output.exists():
            temporary_output.unlink()
    return {
        "ok": True,
        "manifest": str(output_path.resolve()),
        "frames": len(views),
        "caller_calibrated": True,
        "camera_motion_inferred": False,
    }
