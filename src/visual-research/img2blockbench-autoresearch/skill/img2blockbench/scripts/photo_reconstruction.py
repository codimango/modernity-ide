#!/usr/bin/env python3
"""Deterministic single-view photo segmentation and relief reconstruction."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
from collections import Counter, deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


@dataclass(frozen=True)
class PhotoReconstructionOptions:
    """Controls deterministic photo segmentation and relief complexity."""

    analysis_size: int = 96
    grid_size: int = 64
    max_cuboids: int = 70
    target_size: float = 32.0
    target_depth: float = 7.0
    relief_layers: int = 3
    geometry_precision: int | None = None
    texture_density: int | None = None
    palette_clusters: int = 16
    background_mode: str = "auto"
    foreground_mask: Path | None = None
    subject_bbox: tuple[int, int, int, int] | None = None
    depth_map: Path | None = None
    depth_mode: str = "one-sided"
    decomposition: str = "scanline"
    orientation_degrees: float | None = None
    mask_coverage: float = 0.08


@dataclass(frozen=True)
class SegmentationResult:
    """Foreground mask and deterministic reconstruction diagnostics."""

    mask: Image.Image
    analysis_mask: Image.Image
    bbox: tuple[int, int, int, int]
    method: str
    background_labels: tuple[int, ...]
    foreground_fraction: float
    input_mask_sha256: str | None = None
    requested_bbox: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class ReconstructionFrame:
    """Source, mask, and depth evidence in the decomposition coordinate frame."""

    source: Image.Image
    segmentation: SegmentationResult
    depth_map: Image.Image | None
    orientation: dict[str, Any] | None = None


def _pixel_data(image: Image.Image) -> Any:
    return (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(
        "ascii"
    )


def _adjusted_hex(color: str, factor: float) -> str:
    channels = [int(color[index : index + 2], 16) for index in (1, 3, 5)]
    adjusted = [max(0, min(255, round(channel * factor))) for channel in channels]
    return "#{:02x}{:02x}{:02x}".format(*adjusted)


def _rgb_hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _resized_for_analysis(image: Image.Image, max_size: int) -> Image.Image:
    width, height = image.size
    scale = min(1.0, max_size / max(width, height))
    size = (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )
    return image.resize(size, Image.Resampling.LANCZOS)


def _grid_from_image(mask: Image.Image) -> list[list[bool]]:
    gray = mask.convert("L")
    pixels = list(_pixel_data(gray))
    return [
        [pixels[y * gray.width + x] >= 128 for x in range(gray.width)]
        for y in range(gray.height)
    ]


def _image_from_grid(grid: list[list[bool]]) -> Image.Image:
    height = len(grid)
    width = len(grid[0]) if height else 0
    image = Image.new("L", (width, height), 0)
    image.putdata([255 if value else 0 for row in grid for value in row])
    return image


def _dilate(grid: list[list[bool]], iterations: int = 1) -> list[list[bool]]:
    output = [row[:] for row in grid]
    height = len(grid)
    width = len(grid[0]) if height else 0
    for _ in range(iterations):
        source = output
        output = [[False] * width for _ in range(height)]
        for y in range(height):
            for x in range(width):
                output[y][x] = any(
                    source[ny][nx]
                    for ny in range(max(0, y - 1), min(height, y + 2))
                    for nx in range(max(0, x - 1), min(width, x + 2))
                )
    return output


def _erode(grid: list[list[bool]], iterations: int = 1) -> list[list[bool]]:
    output = [row[:] for row in grid]
    height = len(grid)
    width = len(grid[0]) if height else 0
    for _ in range(iterations):
        source = output
        output = [[False] * width for _ in range(height)]
        for y in range(height):
            for x in range(width):
                output[y][x] = all(
                    0 <= ny < height
                    and 0 <= nx < width
                    and source[ny][nx]
                    for ny in range(y - 1, y + 2)
                    for nx in range(x - 1, x + 2)
                )
    return output


def _close(grid: list[list[bool]], iterations: int = 1) -> list[list[bool]]:
    return _erode(_dilate(grid, iterations), iterations)


def _components(grid: list[list[bool]]) -> list[list[tuple[int, int]]]:
    height = len(grid)
    width = len(grid[0]) if height else 0
    visited: set[tuple[int, int]] = set()
    output: list[list[tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            if not grid[y][x] or (x, y) in visited:
                continue
            queue = [(x, y)]
            visited.add((x, y))
            component: list[tuple[int, int]] = []
            while queue:
                current_x, current_y = queue.pop()
                component.append((current_x, current_y))
                for offset_x, offset_y in (
                    (-1, -1),
                    (0, -1),
                    (1, -1),
                    (-1, 0),
                    (1, 0),
                    (-1, 1),
                    (0, 1),
                    (1, 1),
                ):
                    neighbor = (current_x + offset_x, current_y + offset_y)
                    if (
                        0 <= neighbor[0] < width
                        and 0 <= neighbor[1] < height
                        and grid[neighbor[1]][neighbor[0]]
                        and neighbor not in visited
                    ):
                        visited.add(neighbor)
                        queue.append(neighbor)
            output.append(component)
    return output


def _fill_small_holes(
    grid: list[list[bool]],
    maximum_fraction: float = 0.01,
) -> list[list[bool]]:
    height = len(grid)
    width = len(grid[0]) if height else 0
    output = [row[:] for row in grid]
    inverted = [[not value for value in row] for row in grid]
    maximum_area = max(4, round(width * height * maximum_fraction))
    for component in _components(inverted):
        touches_border = any(
            x in {0, width - 1} or y in {0, height - 1}
            for x, y in component
        )
        if not touches_border and len(component) <= maximum_area:
            for x, y in component:
                output[y][x] = True
    return output


def _distance_from_seeds(
    width: int,
    height: int,
    seeds: list[tuple[int, int]],
) -> list[list[int]]:
    far = width + height + 1
    distance = [[far] * width for _ in range(height)]
    queue: deque[tuple[int, int]] = deque()
    for x, y in seeds:
        distance[y][x] = 0
        queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        candidate = distance[y][x] + 1
        for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if (
                0 <= next_x < width
                and 0 <= next_y < height
                and candidate < distance[next_y][next_x]
            ):
                distance[next_y][next_x] = candidate
                queue.append((next_x, next_y))
    return distance


def _largest_subject_component(
    foreground: list[list[bool]],
    preserve_connected_thin_parts: bool = False,
) -> list[list[bool]]:
    height = len(foreground)
    width = len(foreground[0]) if height else 0
    opened = _dilate(_erode(foreground, 1), 1)
    candidates = _components(opened)
    if not candidates:
        candidates = _components(foreground)
    if not candidates:
        return foreground

    center_x = (width - 1) / 2
    center_y = (height - 1) / 2

    def score(component: list[tuple[int, int]]) -> float:
        mean_x = sum(point[0] for point in component) / len(component)
        mean_y = sum(point[1] for point in component) / len(component)
        normalized_distance = math.hypot(
            (mean_x - center_x) / max(1, width),
            (mean_y - center_y) / max(1, height),
        )
        return len(component) * max(0.55, 1.2 - normalized_distance)

    core = max(candidates, key=score)
    if preserve_connected_thin_parts:
        core_points = set(core)
        connected = [
            component
            for component in _components(foreground)
            if any(point in core_points for point in component)
        ]
        if connected:
            retained = max(
                connected,
                key=lambda component: (
                    sum(point in core_points for point in component),
                    len(component),
                ),
            )
            retained_set = set(retained)
            return [
                [(x, y) in retained_set for x in range(width)]
                for y in range(height)
            ]
    distance = _distance_from_seeds(width, height, core)
    growth_radius = max(3, round(min(width, height) * 0.075))
    selected = [
        [foreground[y][x] and distance[y][x] <= growth_radius for x in range(width)]
        for y in range(height)
    ]
    selected = _fill_small_holes(_close(selected, 1))
    selected_components = _components(selected)
    if not selected_components:
        return selected
    retained = max(selected_components, key=len)
    retained_set = set(retained)
    return [
        [(x, y) in retained_set for x in range(width)]
        for y in range(height)
    ]


def _alpha_segmentation(image: Image.Image) -> list[list[bool]] | None:
    alpha = image.getchannel("A")
    alpha_data = list(_pixel_data(alpha))
    transparent = sum(value < 16 for value in alpha_data)
    if transparent < len(alpha_data) * 0.01:
        return None
    return _grid_from_image(alpha.point(lambda value: 255 if value >= 16 else 0))


def _validated_bbox(
    bbox: tuple[int, int, int, int] | None,
    source_size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    if (
        left < 0
        or top < 0
        or right > source_size[0]
        or bottom > source_size[1]
        or left >= right
        or top >= bottom
    ):
        raise ValueError(
            "subject_bbox must be [left, top, right, bottom] within the source image"
        )
    return bbox


def _external_mask(
    path: Path,
    source_size: tuple[int, int],
) -> Image.Image:
    try:
        with Image.open(path) as opened:
            if opened.size != source_size:
                raise ValueError(
                    "foreground mask dimensions must exactly match the source image "
                    f"({opened.width}x{opened.height} != "
                    f"{source_size[0]}x{source_size[1]})"
                )
            alpha = opened.getchannel("A") if "A" in opened.getbands() else None
            if alpha is not None and alpha.getextrema() != (255, 255):
                channel = alpha
            else:
                channel = opened.convert("L")
            return channel.point(lambda value: 255 if value >= 128 else 0)
    except OSError as exc:
        raise ValueError(f"cannot read foreground mask {path}: {exc}") from exc


def _segmentation_from_constraints(
    source: Image.Image,
    options: PhotoReconstructionOptions,
) -> SegmentationResult | None:
    requested_bbox = _validated_bbox(options.subject_bbox, source.size)
    if options.foreground_mask is None:
        return None

    mask = _external_mask(options.foreground_mask, source.size)
    method = "external-mask"
    input_mask_sha256 = _sha256_file(options.foreground_mask)

    if requested_bbox is not None:
        clipped = Image.new("L", source.size, 0)
        clipped.paste(mask.crop(requested_bbox), requested_bbox[:2])
        mask = clipped
        method = "external-mask+subject-bbox"

    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError("foreground constraints contain no selected pixels")
    analysis_mask = _resized_for_analysis(mask, options.analysis_size).point(
        lambda value: 255 if value >= 128 else 0
    )
    foreground_pixels = sum(
        value >= 128 for value in _pixel_data(analysis_mask)
    )
    if foreground_pixels < max(
        4,
        analysis_mask.width * analysis_mask.height * 0.002,
    ):
        raise ValueError("foreground constraints contain no stable subject")
    return SegmentationResult(
        mask=mask,
        analysis_mask=analysis_mask,
        bbox=bbox,
        method=method,
        background_labels=(),
        foreground_fraction=round(
            foreground_pixels / (analysis_mask.width * analysis_mask.height),
            6,
        ),
        input_mask_sha256=input_mask_sha256,
        requested_bbox=requested_bbox,
    )


def _palette_segmentation(
    image: Image.Image,
    clusters: int,
    preserve_connected_thin_parts: bool = False,
) -> tuple[list[list[bool]], tuple[int, ...]]:
    rgb = image.convert("RGB")
    indexed = rgb.quantize(
        colors=clusters,
        method=Image.Quantize.MAXCOVERAGE,
        dither=Image.Dither.NONE,
    )
    width, height = indexed.size
    labels = list(_pixel_data(indexed))
    border_width = max(1, round(min(width, height) * 0.055))
    totals = Counter(labels)
    border = Counter()
    border_pixels = 0
    for y in range(height):
        for x in range(width):
            if (
                x < border_width
                or x >= width - border_width
                or y < border_width
                or y >= height - border_width
            ):
                border[labels[y * width + x]] += 1
                border_pixels += 1
    border_fraction = border_pixels / max(1, width * height)
    background: set[int] = set()
    for label, count in totals.items():
        border_count = border[label]
        border_share = border_count / count
        border_coverage = border_count / max(1, border_pixels)
        image_coverage = count / (width * height)
        if (
            border_coverage >= 0.012
            and border_share >= border_fraction * 0.72
        ) or image_coverage >= 0.24:
            background.add(label)

    foreground = [
        [labels[y * width + x] not in background for x in range(width)]
        for y in range(height)
    ]
    return (
        _largest_subject_component(foreground, preserve_connected_thin_parts),
        tuple(sorted(background)),
    )


def _bbox_for_grid(grid: list[list[bool]]) -> tuple[int, int, int, int]:
    points = [
        (x, y)
        for y, row in enumerate(grid)
        for x, value in enumerate(row)
        if value
    ]
    if not points:
        width = len(grid[0]) if grid else 1
        height = len(grid)
        return 0, 0, width, height
    left = min(point[0] for point in points)
    top = min(point[1] for point in points)
    right = max(point[0] for point in points) + 1
    bottom = max(point[1] for point in points) + 1
    margin = max(1, round(min(right - left, bottom - top) * 0.025))
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(len(grid[0]), right + margin),
        min(len(grid), bottom + margin),
    )


def segment_foreground(
    source: Image.Image,
    options: PhotoReconstructionOptions,
) -> SegmentationResult:
    """Segment the most prominent non-border subject without network models."""
    if options.background_mode not in {"auto", "alpha", "none"}:
        raise ValueError("background_mode must be auto, alpha, or none")
    constrained = _segmentation_from_constraints(source, options)
    if constrained is not None:
        return constrained
    requested_bbox = _validated_bbox(options.subject_bbox, source.size)
    if requested_bbox is not None:
        crop = source.crop(requested_bbox)
        region = segment_foreground(
            crop,
            replace(options, subject_bbox=None),
        )
        mask = Image.new("L", source.size, 0)
        mask.paste(region.mask, requested_bbox[:2])
        local_bbox = region.bbox
        bbox = (
            requested_bbox[0] + local_bbox[0],
            requested_bbox[1] + local_bbox[1],
            requested_bbox[0] + local_bbox[2],
            requested_bbox[1] + local_bbox[3],
        )
        analysis_mask = _resized_for_analysis(mask, options.analysis_size).point(
            lambda value: 255 if value >= 128 else 0
        )
        foreground_pixels = sum(
            value >= 128 for value in _pixel_data(analysis_mask)
        )
        return SegmentationResult(
            mask=mask,
            analysis_mask=analysis_mask,
            bbox=bbox,
            method=f"subject-bbox-roi/{region.method}",
            background_labels=region.background_labels,
            foreground_fraction=round(
                foreground_pixels / (analysis_mask.width * analysis_mask.height),
                6,
            ),
            requested_bbox=requested_bbox,
        )
    analysis = _resized_for_analysis(source.convert("RGBA"), options.analysis_size)
    method = "opaque-frame"
    background_labels: tuple[int, ...] = ()
    if options.background_mode == "none":
        grid = [[True] * analysis.width for _ in range(analysis.height)]
    else:
        grid = _alpha_segmentation(analysis)
        if grid is not None:
            method = "alpha-connected-component"
            grid = _largest_subject_component(
                grid,
                options.decomposition == "oriented",
            )
        elif options.background_mode == "alpha":
            raise ValueError("alpha background mode requires transparent pixels")
        else:
            method = "border-palette-connected-component"
            grid, background_labels = _palette_segmentation(
                analysis,
                options.palette_clusters,
                options.decomposition == "oriented",
            )

    foreground_pixels = sum(value for row in grid for value in row)
    if foreground_pixels < max(4, analysis.width * analysis.height * 0.002):
        raise ValueError("foreground segmentation found no stable subject")
    analysis_bbox = _bbox_for_grid(grid)
    scale_x = source.width / analysis.width
    scale_y = source.height / analysis.height
    bbox = (
        max(0, math.floor(analysis_bbox[0] * scale_x)),
        max(0, math.floor(analysis_bbox[1] * scale_y)),
        min(source.width, math.ceil(analysis_bbox[2] * scale_x)),
        min(source.height, math.ceil(analysis_bbox[3] * scale_y)),
    )
    analysis_mask = _image_from_grid(grid)
    full_mask = analysis_mask.resize(source.size, Image.Resampling.NEAREST)
    return SegmentationResult(
        mask=full_mask,
        analysis_mask=analysis_mask,
        bbox=bbox,
        method=method,
        background_labels=background_labels,
        foreground_fraction=round(
            foreground_pixels / (analysis.width * analysis.height),
            6,
        ),
    )


def _row_run_rectangles(
    grid: list[list[bool]],
) -> list[tuple[int, int, int, int]]:
    rectangles: list[list[int]] = []
    active: dict[tuple[int, int], int] = {}
    for y, row in enumerate(grid):
        runs: list[tuple[int, int]] = []
        x = 0
        while x < len(row):
            if not row[x]:
                x += 1
                continue
            start = x
            while x < len(row) and row[x]:
                x += 1
            runs.append((start, x))
        next_active: dict[tuple[int, int], int] = {}
        for run in runs:
            if run in active:
                index = active[run]
                rectangles[index][3] = y + 1
            else:
                index = len(rectangles)
                rectangles.append([run[0], y, run[1], y + 1])
            next_active[run] = index
        active = next_active
    return [tuple(rectangle) for rectangle in rectangles]


def _largest_true_rectangle(
    grid: list[list[bool]],
) -> tuple[int, int, int, int] | None:
    """Find one deterministic maximum-area rectangle in a binary grid."""
    height = len(grid)
    width = len(grid[0]) if height else 0
    heights = [0] * width
    best: tuple[int, int, int, int] | None = None
    best_score: tuple[int, int, int, int, int] | None = None
    for y, row in enumerate(grid):
        heights = [heights[x] + 1 if row[x] else 0 for x in range(width)]
        stack: list[tuple[int, int]] = []
        for x in range(width + 1):
            current = heights[x] if x < width else 0
            start = x
            while stack and stack[-1][1] > current:
                start, rectangle_height = stack.pop()
                rectangle_width = x - start
                top = y - rectangle_height + 1
                candidate = (start, top, x, y + 1)
                score = (
                    rectangle_width * rectangle_height,
                    rectangle_width,
                    rectangle_height,
                    -top,
                    -start,
                )
                if best_score is None or score > best_score:
                    best = candidate
                    best_score = score
            if current and (not stack or stack[-1][1] < current):
                stack.append((start, current))
    return best


def _adaptive_rectangles(
    grid: list[list[bool]],
) -> list[tuple[int, int, int, int]]:
    """Exactly cover a mask with greedily selected large cuboid footprints."""
    remaining = [row[:] for row in grid]
    rectangles: list[tuple[int, int, int, int]] = []
    while True:
        rectangle = _largest_true_rectangle(remaining)
        if rectangle is None:
            return rectangles
        rectangles.append(rectangle)
        left, top, right, bottom = rectangle
        for y in range(top, bottom):
            for x in range(left, right):
                remaining[y][x] = False


def _decompose_grid(
    grid: list[list[bool]],
    mode: str,
) -> list[tuple[int, int, int, int]]:
    if mode == "scanline":
        return _row_run_rectangles(grid)
    if mode == "adaptive":
        return _adaptive_rectangles(grid)
    if mode == "oriented":
        return _adaptive_rectangles(grid)
    raise ValueError("decomposition must be scanline, adaptive, or oriented")


def _grid_mask_for_bbox(
    segmentation: SegmentationResult,
    max_dimension: int,
    coverage_threshold: float | None = None,
) -> tuple[list[list[bool]], tuple[int, int]]:
    crop = segmentation.mask.crop(segmentation.bbox)
    scale = max_dimension / max(crop.size)
    size = (
        max(1, round(crop.width * scale)),
        max(1, round(crop.height * scale)),
    )
    if coverage_threshold is None:
        resized = crop.resize(size, Image.Resampling.NEAREST)
        grid = _grid_from_image(resized)
    else:
        resized = crop.resize(size, Image.Resampling.BOX)
        threshold = max(1, min(255, math.ceil(coverage_threshold * 255)))
        pixels = list(_pixel_data(resized.convert("L")))
        grid = [
            [pixels[y * resized.width + x] >= threshold for x in range(resized.width)]
            for y in range(resized.height)
        ]
    if not segmentation.method.startswith("external-mask"):
        grid = _close(grid, 1)
    return grid, size


def _read_depth_map(
    path: Path | None,
    source_size: tuple[int, int],
) -> Image.Image | None:
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            if opened.size != source_size:
                raise ValueError(
                    "depth map dimensions must exactly match the source image "
                    f"({opened.width}x{opened.height} != "
                    f"{source_size[0]}x{source_size[1]})"
                )
            return opened.convert("L")
    except OSError as exc:
        raise ValueError(f"cannot read depth map {path}: {exc}") from exc


def _principal_axis(
    mask: Image.Image,
    override_degrees: float | None,
) -> tuple[float, float, list[tuple[float, float]]]:
    """Measure a stable foreground axis in source-image coordinates."""
    analysis = _resized_for_analysis(mask.convert("L"), 512)
    scale_x = mask.width / analysis.width
    scale_y = mask.height / analysis.height
    points = [
        ((x + 0.5) * scale_x, (y + 0.5) * scale_y)
        for y in range(analysis.height)
        for x in range(analysis.width)
        if analysis.getpixel((x, y)) >= 128
    ]
    if len(points) < 2:
        raise ValueError("oriented decomposition requires at least two mask pixels")
    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    covariance_xx = sum((point[0] - mean_x) ** 2 for point in points) / len(points)
    covariance_yy = sum((point[1] - mean_y) ** 2 for point in points) / len(points)
    covariance_xy = sum(
        (point[0] - mean_x) * (point[1] - mean_y) for point in points
    ) / len(points)
    discriminant = math.hypot(
        covariance_xx - covariance_yy,
        2 * covariance_xy,
    )
    largest = (covariance_xx + covariance_yy + discriminant) / 2
    smallest = max(
        1e-9,
        (covariance_xx + covariance_yy - discriminant) / 2,
    )
    measured_angle = 0.5 * math.atan2(
        2 * covariance_xy,
        covariance_xx - covariance_yy,
    )
    angle = (
        math.radians(override_degrees)
        if override_degrees is not None
        else measured_angle
    )
    while angle < -math.pi / 2:
        angle += math.pi
    while angle >= math.pi / 2:
        angle -= math.pi
    return angle, largest / smallest, points


def _oriented_reconstruction_frame(
    source: Image.Image,
    segmentation: SegmentationResult,
    depth_map: Image.Image | None,
    options: PhotoReconstructionOptions,
) -> ReconstructionFrame:
    """Rectify a mask onto its principal axis and retain invertible provenance."""
    angle, axis_ratio, points = _principal_axis(
        segmentation.mask,
        options.orientation_degrees,
    )
    axis_x = math.cos(angle)
    axis_y = math.sin(angle)
    normal_x = -axis_y
    normal_y = axis_x
    projections_x = [point[0] * axis_x + point[1] * axis_y for point in points]
    projections_y = [point[0] * normal_x + point[1] * normal_y for point in points]
    sampling_margin = max(
        2.0,
        source.width / min(512, source.width),
        source.height / min(512, source.height),
    )
    minimum_x = min(projections_x) - sampling_margin
    maximum_x = max(projections_x) + sampling_margin
    minimum_y = min(projections_y) - sampling_margin
    maximum_y = max(projections_y) + sampling_margin
    frame_size = (
        max(1, math.ceil(maximum_x - minimum_x)),
        max(1, math.ceil(maximum_y - minimum_y)),
    )
    frame_to_source = (
        axis_x,
        normal_x,
        axis_x * minimum_x + normal_x * minimum_y,
        axis_y,
        normal_y,
        axis_y * minimum_x + normal_y * minimum_y,
    )
    source_to_frame = (
        axis_x,
        axis_y,
        -minimum_x,
        normal_x,
        normal_y,
        -minimum_y,
    )
    transformed_source = source.transform(
        frame_size,
        Image.Transform.AFFINE,
        frame_to_source,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    transformed_mask = segmentation.mask.transform(
        frame_size,
        Image.Transform.AFFINE,
        frame_to_source,
        resample=Image.Resampling.NEAREST,
        fillcolor=0,
    ).point(lambda value: 255 if value >= 128 else 0)
    transformed_depth = None
    if depth_map is not None:
        transformed_depth = depth_map.transform(
            frame_size,
            Image.Transform.AFFINE,
            frame_to_source,
            resample=Image.Resampling.BILINEAR,
            fillcolor=0,
        )
    bbox = transformed_mask.getbbox()
    if bbox is None:
        raise ValueError("principal-axis transform contains no foreground")
    analysis_mask = _resized_for_analysis(
        transformed_mask,
        options.analysis_size,
    ).point(lambda value: 255 if value >= 128 else 0)
    foreground_pixels = sum(
        value >= 128 for value in _pixel_data(analysis_mask)
    )
    orientation = {
        "mode": "principal-axis",
        "selection": (
            "explicit-angle" if options.orientation_degrees is not None else "mask-pca"
        ),
        "source_angle_degrees": round(math.degrees(angle), 6),
        "model_rotation_degrees": round(-math.degrees(angle), 6),
        "principal_axis_ratio": round(axis_ratio, 6),
        "frame_size": list(frame_size),
        "frame_bbox_pixels": list(bbox),
        "source_to_frame_affine": [round(value, 9) for value in source_to_frame],
        "frame_to_source_affine": [round(value, 9) for value in frame_to_source],
        "mask_coverage_threshold": options.mask_coverage,
    }
    return ReconstructionFrame(
        source=transformed_source,
        segmentation=SegmentationResult(
            mask=transformed_mask,
            analysis_mask=analysis_mask,
            bbox=bbox,
            method=f"{segmentation.method}+principal-axis",
            background_labels=segmentation.background_labels,
            foreground_fraction=round(
                foreground_pixels / (analysis_mask.width * analysis_mask.height),
                6,
            ),
            input_mask_sha256=segmentation.input_mask_sha256,
            requested_bbox=segmentation.requested_bbox,
        ),
        depth_map=transformed_depth,
        orientation=orientation,
    )


def _reconstruction_frame(
    source: Image.Image,
    segmentation: SegmentationResult,
    options: PhotoReconstructionOptions,
) -> ReconstructionFrame:
    """Resolve the coordinate frame used for mask decomposition."""
    depth_map = _read_depth_map(options.depth_map, source.size)
    if options.decomposition == "oriented":
        return _oriented_reconstruction_frame(
            source,
            segmentation,
            depth_map,
            options,
        )
    return ReconstructionFrame(
        source=source,
        segmentation=segmentation,
        depth_map=depth_map,
    )


def _depth_layers(
    foreground: list[list[bool]],
    depth_map: Image.Image,
    bbox: tuple[int, int, int, int],
    count: int,
) -> list[list[list[bool]]]:
    height = len(foreground)
    width = len(foreground[0]) if height else 0
    sampled = depth_map.crop(bbox).resize((width, height), Image.Resampling.BOX)
    values = list(_pixel_data(sampled))
    layers = [foreground]
    for layer_index in range(1, count):
        threshold = round(255 * layer_index / count)
        layer = [
            [
                foreground[y][x] and values[y * width + x] >= threshold
                for x in range(width)
            ]
            for y in range(height)
        ]
        layers.append(layer)
    return layers


def _fit_grid_to_budget(
    segmentation: SegmentationResult,
    options: PhotoReconstructionOptions,
    depth_map: Image.Image | None = None,
) -> tuple[
    list[list[bool]],
    list[tuple[list[list[bool]], list[tuple[int, int, int, int]]]],
]:
    if options.depth_mode not in {"one-sided", "symmetric"}:
        raise ValueError("depth_mode must be one-sided or symmetric")
    if options.decomposition not in {"scanline", "adaptive", "oriented"}:
        raise ValueError("decomposition must be scanline, adaptive, or oriented")
    if not 0 < options.mask_coverage <= 1:
        raise ValueError("mask_coverage must be within (0, 1]")
    if depth_map is None and options.depth_map is not None:
        depth_map = _read_depth_map(options.depth_map, segmentation.mask.size)
    for max_dimension in range(options.grid_size, 11, -1):
        grid, _ = _grid_mask_for_bbox(
            segmentation,
            max_dimension,
            options.mask_coverage if options.decomposition == "oriented" else None,
        )
        if depth_map is not None:
            layer_grids = _depth_layers(
                grid,
                depth_map,
                segmentation.bbox,
                options.relief_layers,
            )
        else:
            layer_grid = grid
            layer_grids = []
            for layer_index in range(options.relief_layers):
                if layer_index:
                    layer_grid = _erode(layer_grid, 1)
                if not any(value for row in layer_grid for value in row):
                    break
                layer_grids.append(layer_grid)
        layers = [
            (layer_grid, _decompose_grid(layer_grid, options.decomposition))
            for layer_grid in layer_grids
        ]
        cuboids = sum(len(rectangles) for _, rectangles in layers)
        if layers and 1 <= cuboids <= options.max_cuboids:
            return grid, layers
    raise ValueError(
        f"cannot fit segmented silhouette within {options.max_cuboids} cuboids"
    )


def _median_color(
    image: Image.Image,
    mask: Image.Image,
    box: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int]:
    source = image.convert("RGB")
    selected_mask = mask
    if box is not None:
        source = source.crop(box)
        selected_mask = mask.crop(box)
    source.thumbnail((128, 128), Image.Resampling.LANCZOS)
    selected_mask = selected_mask.resize(source.size, Image.Resampling.NEAREST)
    colors = [
        pixel
        for pixel, selected in zip(_pixel_data(source), _pixel_data(selected_mask))
        if selected >= 128
    ]
    if not colors:
        colors = list(_pixel_data(source))
    channels = [sorted(color[index] for color in colors) for index in range(3)]
    return tuple(channel[len(channel) // 2] for channel in channels)


def _average_color(
    image: Image.Image,
    box: tuple[int, int, int, int],
    mask: Image.Image | None = None,
) -> tuple[int, int, int]:
    crop = image.convert("RGB").crop(box)
    crop.thumbnail((32, 32), Image.Resampling.BOX)
    if mask is None:
        pixels = list(_pixel_data(crop))
    else:
        selected = mask.crop(box).resize(crop.size, Image.Resampling.BOX)
        pixels = [
            pixel
            for pixel, alpha in zip(_pixel_data(crop), _pixel_data(selected))
            if alpha >= 128
        ]
    if not pixels:
        pixels = list(_pixel_data(crop))
    if not pixels:
        return (128, 128, 128)
    return tuple(round(sum(pixel[index] for pixel in pixels) / len(pixels)) for index in range(3))


def _embedded_reference(
    image: Image.Image,
    mask: Image.Image,
    max_size: int = 512,
) -> Image.Image:
    embedded = image.convert("RGBA")
    embedded.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    embedded.putalpha(mask.resize(embedded.size, Image.Resampling.LANCZOS))
    return embedded


def _relative_input_name(path: Path, output_path: Path) -> str:
    try:
        return path.resolve().relative_to(output_path.parent.resolve()).as_posix()
    except ValueError:
        return Path(
            os.path.relpath(path.resolve(), output_path.parent.resolve())
        ).as_posix()


def reconstruct_photo_spec(
    image_path: Path,
    output_path: Path,
    model_id: str,
    description: str,
    subject_type: str,
    options: PhotoReconstructionOptions,
) -> tuple[dict[str, Any], SegmentationResult]:
    """Create a native cuboid relief spec from one image."""
    with Image.open(image_path) as opened:
        source = opened.convert("RGBA")
    segmentation = segment_foreground(source, options)
    frame = _reconstruction_frame(source, segmentation, options)
    working_source = frame.source
    working_segmentation = frame.segmentation
    grid, layers = _fit_grid_to_budget(
        working_segmentation,
        options,
        frame.depth_map,
    )
    grid_height = len(grid)
    grid_width = len(grid[0])
    cell_size = options.target_size / max(grid_width, grid_height)

    embedded = _embedded_reference(working_source, working_segmentation.mask)
    embedded_uri = _png_data_uri(embedded)
    median = _median_color(working_source, working_segmentation.mask)
    reference_material = {
        "base": _rgb_hex(median),
        "shade": _adjusted_hex(_rgb_hex(median), 0.58),
        "highlight": _adjusted_hex(_rgb_hex(median), 1.24),
        "pattern": "solid",
        "pattern_scale": 1,
        "source_texture": {
            "data_uri": embedded_uri,
            "repeat": [1, 1],
            "offset": [0, 0],
            "center": [0, 0],
            "rotation": 0,
            "wrap": [1001, 1001],
            "flip_y": True,
        },
    }
    materials: dict[str, Any] = {"reference_photo": reference_material}
    cubes: list[dict[str, Any]] = []
    bbox_left, bbox_top, bbox_right, bbox_bottom = working_segmentation.bbox
    bbox_width = bbox_right - bbox_left
    bbox_height = bbox_bottom - bbox_top
    layer_depth = options.target_depth / len(layers)
    project_each_layer = options.depth_mode == "symmetric"
    cube_index = 0
    layer_counts = []
    for layer_index, (_, rectangles) in enumerate(layers):
        layer_counts.append(len(rectangles))
        for left, top, right, bottom in rectangles:
            cube_index += 1
            source_box = (
                max(0, round(bbox_left + left / grid_width * bbox_width)),
                max(0, round(bbox_top + top / grid_height * bbox_height)),
                min(
                    working_source.width,
                    round(bbox_left + right / grid_width * bbox_width),
                ),
                min(
                    working_source.height,
                    round(bbox_top + bottom / grid_height * bbox_height),
                ),
            )
            average = _average_color(
                working_source,
                source_box,
                working_segmentation.mask,
            )
            material_name = f"surface_{cube_index:03d}"
            base = _rgb_hex(average)
            materials[material_name] = {
                "base": base,
                "shade": _adjusted_hex(base, 0.58),
                "highlight": _adjusted_hex(base, 1.2),
                "pattern": "gradient",
                "pattern_scale": 2,
            }
            size_x = (right - left) * cell_size
            size_y = (bottom - top) * cell_size
            center_x = ((left + right) / 2 - grid_width / 2) * cell_size
            center_y = (grid_height - (top + bottom) / 2) * cell_size
            faces: dict[str, Any] = {}
            source_face = {
                "material": "reference_photo",
                "source_region": [
                    source_box[0] / working_source.width,
                    source_box[1] / working_source.height,
                    source_box[2] / working_source.width,
                    source_box[3] / working_source.height,
                ],
            }
            if layer_index == 0 or project_each_layer:
                faces["south"] = source_face
            if project_each_layer:
                faces["north"] = {
                    "material": "reference_photo",
                    "source_region": source_face["source_region"],
                }
            if options.depth_mode == "symmetric":
                center_z = 0.0
                size_z = layer_depth * (layer_index + 1)
            else:
                center_z = -(layer_index + 0.5) * layer_depth
                size_z = layer_depth
            cubes.append(
                {
                    "name": f"relief_l{layer_index + 1}_{cube_index:03d}",
                    "bone": "relief",
                    "center": [
                        round(center_x, 6),
                        round(center_y, 6),
                        round(center_z, 6),
                    ],
                    "size": [
                        round(size_x, 6),
                        round(size_y, 6),
                        round(size_z, 6),
                    ],
                    "rotation": [
                        0,
                        0,
                        (
                            frame.orientation["model_rotation_degrees"]
                            if frame.orientation is not None
                            else 0
                        ),
                    ],
                    "origin": [0, 0, 0],
                    "role": f"foreground relief shell {layer_index + 1}",
                    "material": material_name,
                    "faces": faces,
                }
            )

    reference_name = _relative_input_name(image_path, output_path)
    model_width = grid_width * cell_size
    model_height = grid_height * cell_size
    if frame.orientation is not None:
        radians = math.radians(frame.orientation["model_rotation_degrees"])
        collision_width = abs(math.cos(radians)) * model_width + abs(
            math.sin(radians)
        ) * model_height
        collision_height = abs(math.sin(radians)) * model_width + abs(
            math.cos(radians)
        ) * model_height
    else:
        collision_width = model_width
        collision_height = model_height
    texture_density = options.texture_density or (
        2 if options.depth_mode == "symmetric" else 4
    )
    depth_map_record = None
    if options.depth_map is not None:
        depth_map_record = {
            "image": _relative_input_name(options.depth_map, output_path),
            "sha256": _sha256_file(options.depth_map),
            "encoding": "grayscale thickness; black=minimum, white=maximum",
        }
    mask_record = None
    if options.foreground_mask is not None:
        mask_record = {
            "image": _relative_input_name(options.foreground_mask, output_path),
            "sha256": _sha256_file(options.foreground_mask),
            "encoding": "alpha when non-opaque, otherwise grayscale >=128",
        }
    advanced_depthfield = any(
        (
            options.foreground_mask is not None,
            options.subject_bbox is not None,
            options.depth_map is not None,
            options.depth_mode != "one-sided",
            options.decomposition != "scanline",
        )
    )
    return (
        {
            "schema_version": 1,
            "id": model_id,
            "reference": {
                "image": reference_name,
                "sha256": _sha256_file(image_path),
                "width": source.width,
                "height": source.height,
            },
            "subject": {
                "type": subject_type,
                "description": description,
                "symmetry": "none",
                "uncertainties": [
                    "Single-view relief: hidden surfaces use conservative sampled colors",
                    "Automatic foreground segmentation may omit thin or background-colored details",
                ],
            },
            "quality_contract": {
                "complexity": "complex",
                "target_cuboids": [1, options.max_cuboids],
                "identity_features": [
                    "source-derived silhouette",
                    "source-projected color and surface detail",
                ],
                "required_views": ["source-facing", "isometric", "profile"],
                "review_targets": [
                    "silhouette",
                    "texture fidelity",
                    "relief depth",
                    "foreground segmentation",
                ],
            },
            "texture": {
                "density": texture_density,
                "palette_size": 64,
                "gutter": 1,
                "atlas_size": 256,
                "quantize_source": False,
            },
            **(
                {"geometry": {"precision": options.geometry_precision}}
                if options.geometry_precision is not None
                else {}
            ),
            "materials": materials,
            "bones": [
                {"name": "root", "parent": None, "pivot": [0, 0, 0]},
                {"name": "relief", "parent": "root", "pivot": [0, 0, 0]},
            ],
            "cubes": cubes,
            "landmarks": [],
            "collision": {
                "width": round(collision_width / 16, 3),
                "height": round(collision_height / 16, 3),
                "eye_height": round(collision_height * 0.75 / 16, 3),
            },
            "generation": {
                "lane": "photo-relief",
                "algorithm": (
                    "principal-axis-depthfield-cuboids-v3"
                    if frame.orientation is not None
                    else (
                        "ray-depthfield-adaptive-cuboids-v2"
                        if advanced_depthfield
                        else "border-palette-component-row-relief-v1"
                    )
                ),
                "source_projection": (
                    "principal-axis-normalized-face-regions"
                    if frame.orientation is not None
                    else "normalized-face-regions"
                ),
                "segmentation": {
                    "method": segmentation.method,
                    "analysis_size": list(segmentation.analysis_mask.size),
                    "background_labels": list(segmentation.background_labels),
                    "foreground_fraction": segmentation.foreground_fraction,
                    "bbox_pixels": list(segmentation.bbox),
                    "requested_bbox_pixels": (
                        list(segmentation.requested_bbox)
                        if segmentation.requested_bbox is not None
                        else None
                    ),
                    "input_mask": mask_record,
                },
                "relief": {
                    "grid_size": [grid_width, grid_height],
                    "cuboids": len(cubes),
                    "target_size": options.target_size,
                    "target_depth": options.target_depth,
                    "depth_mode": options.depth_mode,
                    "depth_map": depth_map_record,
                    "decomposition": options.decomposition,
                    "front_plane": (
                        "variable-positive-half-depth"
                        if options.depth_mode == "symmetric"
                        else 0
                    ),
                    "layers": len(layers),
                    "cuboids_per_layer": layer_counts,
                    **(
                        {"geometry_precision": options.geometry_precision}
                        if options.geometry_precision is not None
                        else {}
                    ),
                    **(
                        {"texture_density": texture_density}
                        if options.texture_density is not None
                        else {}
                    ),
                    **(
                        {"orientation": frame.orientation}
                        if frame.orientation is not None
                        else {}
                    ),
                },
            },
        },
        segmentation,
    )


def write_segmentation_diagnostics(
    image_path: Path,
    result: SegmentationResult,
    output_dir: Path,
) -> dict[str, Any]:
    """Write a mask, cutout, and JSON evidence for a segmentation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as opened:
        source = opened.convert("RGBA")
    mask = result.mask.convert("L")
    mask.save(output_dir / "foreground-mask.png", optimize=True)
    cutout = source.copy()
    cutout.putalpha(mask)
    cutout.crop(result.bbox).save(output_dir / "foreground-cutout.png", optimize=True)
    report = {
        "schema_version": 1,
        "algorithm": (
            "explicit-foreground-contract-v1"
            if result.method.startswith(("external-mask", "subject-bbox"))
            else "deterministic-border-palette-connected-component"
        ),
        "method": result.method,
        "source_sha256": _sha256_file(image_path),
        "source_size": list(source.size),
        "analysis_size": list(result.analysis_mask.size),
        "bbox_pixels": list(result.bbox),
        "foreground_fraction": result.foreground_fraction,
        "background_labels": list(result.background_labels),
        "input_mask_sha256": result.input_mask_sha256,
        "requested_bbox_pixels": (
            list(result.requested_bbox)
            if result.requested_bbox is not None
            else None
        ),
    }
    (output_dir / "segmentation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


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


def _rotate_point(
    point: tuple[float, float, float],
    origin: tuple[float, float, float],
    rotation: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Apply the compiler's XYZ Euler convention around one cuboid pivot."""
    x = point[0] - origin[0]
    y = point[1] - origin[1]
    z = point[2] - origin[2]
    angle_x, angle_y, angle_z = (math.radians(value) for value in rotation)
    cosine = math.cos(angle_x)
    sine = math.sin(angle_x)
    y, z = y * cosine - z * sine, y * sine + z * cosine
    cosine = math.cos(angle_y)
    sine = math.sin(angle_y)
    x, z = x * cosine + z * sine, -x * sine + z * cosine
    cosine = math.cos(angle_z)
    sine = math.sin(angle_z)
    x, y = x * cosine - y * sine, x * sine + y * cosine
    return x + origin[0], y + origin[1], z + origin[2]


def _cube_point(
    cube: dict[str, Any],
    x: float,
    y: float,
    z: float,
) -> tuple[float, float, float]:
    return _rotate_point(
        (x, y, z),
        tuple(float(value) for value in cube["origin"]),
        tuple(float(value) for value in cube["rotation"]),
    )


def _cube_bounds(cube: dict[str, Any]) -> tuple[float, float, float, float]:
    center_x, center_y, center_z = cube["center"]
    size_x, size_y, size_z = cube["size"]
    points = [
        _cube_point(cube, x, y, z)
        for x in (center_x - size_x / 2, center_x + size_x / 2)
        for y in (center_y - size_y / 2, center_y + size_y / 2)
        for z in (center_z - size_z / 2, center_z + size_z / 2)
    ]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _model_bounds(spec: dict[str, Any]) -> tuple[float, float, float, float]:
    bounds = [_cube_bounds(cube) for cube in spec["cubes"]]
    return (
        min(bound[0] for bound in bounds),
        min(bound[1] for bound in bounds),
        max(bound[2] for bound in bounds),
        max(bound[3] for bound in bounds),
    )


def _front_render(
    spec: dict[str, Any],
    atlas: Image.Image,
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
    size: tuple[int, int] = (720, 720),
) -> Image.Image:
    canvas = Image.new("RGBA", size, "#111820")
    draw = ImageDraw.Draw(canvas)
    left, bottom, right, top = _model_bounds(spec)
    margin = 48
    scale = min(
        (size[0] - margin * 2) / max(1e-6, right - left),
        (size[1] - margin * 2) / max(1e-6, top - bottom),
    )
    offset_x = (size[0] - (right - left) * scale) / 2 - left * scale
    offset_y = (size[1] + (top - bottom) * scale) / 2 + bottom * scale
    shadow_box = (
        size[0] * 0.2,
        offset_y - bottom * scale - 8,
        size[0] * 0.8,
        offset_y - bottom * scale + 20,
    )
    draw.ellipse(shadow_box, fill=(0, 0, 0, 70))
    for cube in sorted(
        spec["cubes"],
        key=lambda item: item["center"][2] + item["size"][2] / 2,
    ):
        source_region = cube.get("faces", {}).get("south", {}).get("source_region")
        if source_region is None:
            continue
        center_x, center_y, center_z = cube["center"]
        size_x, size_y = cube["size"][:2]
        placement = placements[(cube["name"], "south")]
        patch = atlas.crop(
            (
                placement[0],
                placement[1],
                placement[0] + placement[2],
                placement[1] + placement[3],
            )
        )
        angle = float(cube["rotation"][2])
        if abs(angle) <= 1e-9:
            destination = (
                round((center_x - size_x / 2) * scale + offset_x),
                round(offset_y - (center_y + size_y / 2) * scale),
                round((center_x + size_x / 2) * scale + offset_x),
                round(offset_y - (center_y - size_y / 2) * scale),
            )
            patch = patch.resize(
                (
                    max(1, destination[2] - destination[0]),
                    max(1, destination[3] - destination[1]),
                ),
                Image.Resampling.NEAREST,
            )
            canvas.alpha_composite(patch, destination[:2])
            continue
        patch = patch.resize(
            (max(1, round(size_x * scale)), max(1, round(size_y * scale))),
            Image.Resampling.NEAREST,
        ).rotate(angle, resample=Image.Resampling.NEAREST, expand=True)
        world_center = _cube_point(cube, center_x, center_y, center_z)
        destination = (
            round(world_center[0] * scale + offset_x - patch.width / 2),
            round(offset_y - world_center[1] * scale - patch.height / 2),
        )
        canvas.alpha_composite(patch, destination)
    return canvas


def _isometric_render(
    spec: dict[str, Any],
    atlas: Image.Image,
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
    size: tuple[int, int] = (720, 720),
) -> Image.Image:
    canvas = Image.new("RGBA", size, "#111820")

    def project(point: tuple[float, float, float]) -> tuple[float, float]:
        x, y, z = point
        return x - z * 0.52, -y + x * 0.12 + z * 0.22

    projected = []
    for cube in spec["cubes"]:
        cx, cy, cz = cube["center"]
        sx, sy, sz = cube["size"]
        for x in (cx - sx / 2, cx + sx / 2):
            for y in (cy - sy / 2, cy + sy / 2):
                for z in (cz - sz / 2, cz + sz / 2):
                    projected.append(project(_cube_point(cube, x, y, z)))
    minimum_x = min(point[0] for point in projected)
    maximum_x = max(point[0] for point in projected)
    minimum_y = min(point[1] for point in projected)
    maximum_y = max(point[1] for point in projected)
    margin = 46
    scale = min(
        (size[0] - margin * 2) / max(1e-6, maximum_x - minimum_x),
        (size[1] - margin * 2) / max(1e-6, maximum_y - minimum_y),
    )
    offset_x = (size[0] - (maximum_x - minimum_x) * scale) / 2 - minimum_x * scale
    offset_y = (size[1] - (maximum_y - minimum_y) * scale) / 2 - minimum_y * scale

    def screen(point: tuple[float, float, float]) -> tuple[float, float]:
        x, y = project(point)
        return x * scale + offset_x, y * scale + offset_y

    def uncovered_intervals(
        start: float,
        end: float,
        covered: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        output = [(start, end)]
        for cover_start, cover_end in sorted(covered):
            next_output = []
            for current_start, current_end in output:
                if cover_end <= current_start or cover_start >= current_end:
                    next_output.append((current_start, current_end))
                    continue
                if cover_start > current_start:
                    next_output.append((current_start, cover_start))
                if cover_end < current_end:
                    next_output.append((cover_end, current_end))
            output = next_output
        return output

    draw = ImageDraw.Draw(canvas)
    draw.ellipse(
        (size[0] * 0.22, size[1] * 0.84, size[0] * 0.82, size[1] * 0.91),
        fill=(0, 0, 0, 70),
    )
    for cube in sorted(
        spec["cubes"],
        key=lambda item: (
            item["center"][2] + item["size"][2] / 2,
            -item["center"][1],
        ),
    ):
        cx, cy, cz = cube["center"]
        sx, sy, sz = cube["size"]
        x0, x1 = cx - sx / 2, cx + sx / 2
        y0, y1 = cy - sy / 2, cy + sy / 2
        z0, z1 = cz - sz / 2, cz + sz / 2
        material = spec["materials"][cube["material"]]
        shade = tuple(int(material["shade"][index : index + 2], 16) for index in (1, 3, 5))
        highlight = tuple(int(material["highlight"][index : index + 2], 16) for index in (1, 3, 5))
        same_shell = [
            other
            for other in spec["cubes"]
            if other is not cube
            and all(
                abs(float(left) - float(right)) < 1e-9
                for left, right in zip(cube["rotation"], other["rotation"])
            )
            and all(
                abs(float(left) - float(right)) < 1e-9
                for left, right in zip(cube["origin"], other["origin"])
            )
            and abs(
                (other["center"][2] - other["size"][2] / 2) - z0
            ) < 1e-6
            and abs(
                (other["center"][2] + other["size"][2] / 2) - z1
            ) < 1e-6
        ]
        east_cover = []
        top_cover = []
        for other in same_shell:
            other_x0 = other["center"][0] - other["size"][0] / 2
            other_x1 = other["center"][0] + other["size"][0] / 2
            other_y0 = other["center"][1] - other["size"][1] / 2
            other_y1 = other["center"][1] + other["size"][1] / 2
            if abs(other_x0 - x1) < 1e-6:
                east_cover.append((max(y0, other_y0), min(y1, other_y1)))
            if abs(other_y0 - y1) < 1e-6:
                top_cover.append((max(x0, other_x0), min(x1, other_x1)))
        for visible_y0, visible_y1 in uncovered_intervals(y0, y1, east_cover):
            draw.polygon(
                [
                    screen(point)
                    for point in (
                        _cube_point(cube, x1, visible_y0, z1),
                        _cube_point(cube, x1, visible_y1, z1),
                        _cube_point(cube, x1, visible_y1, z0),
                        _cube_point(cube, x1, visible_y0, z0),
                    )
                ],
                fill=(*shade, 255),
            )
        for visible_x0, visible_x1 in uncovered_intervals(x0, x1, top_cover):
            draw.polygon(
                [
                    screen(point)
                    for point in (
                        _cube_point(cube, visible_x0, y1, z1),
                        _cube_point(cube, visible_x1, y1, z1),
                        _cube_point(cube, visible_x1, y1, z0),
                        _cube_point(cube, visible_x0, y1, z0),
                    )
                ],
                fill=(*highlight, 255),
            )

    for cube in sorted(
        spec["cubes"],
        key=lambda item: item["center"][2] + item["size"][2] / 2,
    ):
        cx, cy, cz = cube["center"]
        sx, sy, sz = cube["size"]
        x0, x1 = cx - sx / 2, cx + sx / 2
        y0, y1 = cy - sy / 2, cy + sy / 2
        z1 = cz + sz / 2
        placement = placements[(cube["name"], "south")]
        patch = atlas.crop(
            (
                placement[0],
                placement[1],
                placement[0] + placement[2],
                placement[1] + placement[3],
            )
        ).convert("RGBA")
        patch_pixels = patch.load()
        for pixel_y in range(patch.height):
            source_y0 = y1 - pixel_y / patch.height * (y1 - y0)
            source_y1 = y1 - (pixel_y + 1) / patch.height * (y1 - y0)
            for pixel_x in range(patch.width):
                source_x0 = x0 + pixel_x / patch.width * (x1 - x0)
                source_x1 = x0 + (pixel_x + 1) / patch.width * (x1 - x0)
                draw.polygon(
                    [
                        screen(_cube_point(cube, source_x0, source_y0, z1)),
                        screen(_cube_point(cube, source_x1, source_y0, z1)),
                        screen(_cube_point(cube, source_x1, source_y1, z1)),
                        screen(_cube_point(cube, source_x0, source_y1, z1)),
                    ],
                    fill=patch_pixels[pixel_x, pixel_y],
                )
    return canvas


def _reprojection(
    spec: dict[str, Any],
    atlas: Image.Image,
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
    source_size: tuple[int, int],
) -> Image.Image:
    orientation = spec.get("generation", {}).get("relief", {}).get("orientation")
    projection_size = source_size
    if isinstance(orientation, dict):
        candidate = orientation.get("frame_size")
        if (
            isinstance(candidate, list)
            and len(candidate) == 2
            and all(isinstance(value, int) and value > 0 for value in candidate)
        ):
            projection_size = (candidate[0], candidate[1])
    output = Image.new("RGBA", projection_size, (0, 0, 0, 0))
    for cube in spec["cubes"]:
        region = cube.get("faces", {}).get("south", {}).get("source_region")
        if region is None:
            continue
        box = (
            round(region[0] * projection_size[0]),
            round(region[1] * projection_size[1]),
            round(region[2] * projection_size[0]),
            round(region[3] * projection_size[1]),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        placement = placements[(cube["name"], "south")]
        patch = atlas.crop(
            (
                placement[0],
                placement[1],
                placement[0] + placement[2],
                placement[1] + placement[3],
            )
        ).resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.NEAREST)
        output.alpha_composite(patch, (box[0], box[1]))
    if isinstance(orientation, dict):
        source_to_frame = orientation.get("source_to_frame_affine")
        if (
            isinstance(source_to_frame, list)
            and len(source_to_frame) == 6
            and all(isinstance(value, (int, float)) for value in source_to_frame)
        ):
            output = output.transform(
                source_size,
                Image.Transform.AFFINE,
                tuple(float(value) for value in source_to_frame),
                resample=Image.Resampling.NEAREST,
                fillcolor=(0, 0, 0, 0),
            )
    return output


def _profile_render(
    spec: dict[str, Any],
    size: tuple[int, int] = (720, 300),
) -> tuple[Image.Image, float]:
    """Render the reconstruction frame's major-axis/depth profile."""
    canvas = Image.new("RGBA", size, "#111820")
    minimum_x = min(
        cube["center"][0] - cube["size"][0] / 2 for cube in spec["cubes"]
    )
    maximum_x = max(
        cube["center"][0] + cube["size"][0] / 2 for cube in spec["cubes"]
    )
    minimum_z = min(
        cube["center"][2] - cube["size"][2] / 2 for cube in spec["cubes"]
    )
    maximum_z = max(
        cube["center"][2] + cube["size"][2] / 2 for cube in spec["cubes"]
    )
    margin = 40
    scale = min(
        (size[0] - margin * 2) / max(1e-9, maximum_x - minimum_x),
        (size[1] - margin * 2) / max(1e-9, maximum_z - minimum_z),
    )
    offset_x = (size[0] - (maximum_x - minimum_x) * scale) / 2
    offset_z = (size[1] - (maximum_z - minimum_z) * scale) / 2
    draw = ImageDraw.Draw(canvas)
    for cube in sorted(spec["cubes"], key=lambda item: -item["size"][2]):
        center_x, _, center_z = cube["center"]
        size_x, _, size_z = cube["size"]
        material = spec["materials"][cube["material"]]
        box = (
            round(offset_x + (center_x - size_x / 2 - minimum_x) * scale),
            round(offset_z + (maximum_z - center_z - size_z / 2) * scale),
            round(offset_x + (center_x + size_x / 2 - minimum_x) * scale),
            round(offset_z + (maximum_z - center_z + size_z / 2) * scale),
        )
        draw.rectangle(box, fill=material["base"], outline=material["shade"])
    ratio = (maximum_z - minimum_z) / max(1e-9, maximum_x - minimum_x)
    return canvas, round(ratio, 6)


def _fidelity_metrics(source: Image.Image, reprojection: Image.Image) -> dict[str, Any]:
    original = source.convert("RGB")
    reconstructed = reprojection.convert("RGB")
    mask = reprojection.getchannel("A")
    squared_error = 0.0
    absolute_error = 0.0
    samples = 0
    for expected, actual, alpha in zip(
        _pixel_data(original),
        _pixel_data(reconstructed),
        _pixel_data(mask),
    ):
        if alpha < 128:
            continue
        for channel in range(3):
            delta = expected[channel] - actual[channel]
            squared_error += delta * delta
            absolute_error += abs(delta)
            samples += 1
    mse = squared_error / max(1, samples)
    psnr = 99.0 if mse == 0 else 10 * math.log10(255 * 255 / mse)
    return {
        "sampled_channels": samples,
        "mean_absolute_error": round(absolute_error / max(1, samples), 4),
        "texture_psnr_db": round(psnr, 4),
        "reprojected_fraction": round(
            sum(value >= 128 for value in _pixel_data(mask))
            / (source.width * source.height),
            6,
        ),
    }


def _reference_projection_mask(
    spec: dict[str, Any],
    source_size: tuple[int, int],
) -> Image.Image | None:
    """Recover the embedded reviewed foreground in original source coordinates."""
    generation = spec.get("generation", {})
    orientation = generation.get("relief", {}).get("orientation")
    input_mask = generation.get("segmentation", {}).get("input_mask")
    if orientation is None and not input_mask:
        return None
    material = spec.get("materials", {}).get("reference_photo")
    if not isinstance(material, dict):
        return None
    source_texture = material.get("source_texture")
    if not isinstance(source_texture, dict):
        return None
    data_uri = source_texture.get("data_uri")
    prefix = "data:image/png;base64,"
    if not isinstance(data_uri, str) or not data_uri.startswith(prefix):
        return None
    try:
        with Image.open(io.BytesIO(base64.b64decode(data_uri[len(prefix) :]))) as opened:
            embedded = opened.convert("RGBA")
    except (ValueError, OSError):
        return None
    projection_size = source_size
    if isinstance(orientation, dict):
        candidate = orientation.get("frame_size")
        if (
            isinstance(candidate, list)
            and len(candidate) == 2
            and all(isinstance(value, int) and value > 0 for value in candidate)
        ):
            projection_size = (candidate[0], candidate[1])
    mask = embedded.getchannel("A").resize(projection_size, Image.Resampling.LANCZOS)
    if isinstance(orientation, dict):
        source_to_frame = orientation.get("source_to_frame_affine")
        if isinstance(source_to_frame, list) and len(source_to_frame) == 6:
            mask = mask.transform(
                source_size,
                Image.Transform.AFFINE,
                tuple(float(value) for value in source_to_frame),
                resample=Image.Resampling.NEAREST,
                fillcolor=0,
            )
    return mask


def _silhouette_metrics(
    expected: Image.Image | None,
    actual: Image.Image,
) -> dict[str, float]:
    """Measure retained binary silhouette independently from texture PSNR."""
    if expected is None:
        return {}
    expected_values = list(_pixel_data(expected.convert("L")))
    actual_values = list(_pixel_data(actual.convert("L")))
    intersection = sum(
        left >= 128 and right >= 128
        for left, right in zip(expected_values, actual_values)
    )
    expected_count = sum(value >= 128 for value in expected_values)
    actual_count = sum(value >= 128 for value in actual_values)
    union = expected_count + actual_count - intersection
    return {
        "silhouette_iou": round(intersection / max(1, union), 6),
        "silhouette_recall": round(intersection / max(1, expected_count), 6),
        "silhouette_precision": round(intersection / max(1, actual_count), 6),
    }


def render_relief_evidence(
    spec: dict[str, Any],
    reference_path: Path,
    atlas: Image.Image,
    placements: dict[tuple[str, str], tuple[int, int, int, int]],
    output_dir: Path,
) -> dict[str, Any]:
    """Render deterministic source-facing and isometric relief evidence."""
    generation = spec.get("generation", {})
    if generation.get("lane") != "photo-relief":
        raise ValueError("deterministic relief rendering requires a photo-relief spec")
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(reference_path) as opened:
        source = opened.convert("RGBA")
    front = _front_render(spec, atlas, placements)
    isometric = _isometric_render(spec, atlas, placements)
    reprojection = _reprojection(spec, atlas, placements, source.size)
    profile, depth_to_length_ratio = _profile_render(spec)
    front.save(output_dir / "front.png", optimize=True)
    isometric.save(output_dir / "isometric.png", optimize=True)
    reprojection.save(output_dir / "reprojection.png", optimize=True)
    profile.save(output_dir / "profile.png", optimize=True)

    bbox = generation.get("segmentation", {}).get("bbox_pixels")
    reference_panel = source.convert("RGB")
    if (
        isinstance(bbox, list)
        and len(bbox) == 4
        and 0 <= bbox[0] < bbox[2] <= source.width
        and 0 <= bbox[1] < bbox[3] <= source.height
    ):
        reference_panel = reference_panel.crop(tuple(int(value) for value in bbox))
    panel_size = (560, 560)
    sheet = Image.new("RGB", (panel_size[0] * 3 + 64, 650), "#0b1118")
    draw = ImageDraw.Draw(sheet)
    title_font = _font(22, bold=True)
    label_font = _font(17, bold=True)
    body_font = _font(13)
    draw.text(
        (24, 16),
        f"{spec['id']}  /  deterministic depth-field cuboids",
        fill="#f5f7f8",
        font=title_font,
    )
    labels = ("REFERENCE SUBJECT", "SOURCE-FACING", "BLOCKBENCH ISOMETRIC")

    def fit_panel(image: Image.Image) -> Image.Image:
        panel = Image.new("RGB", panel_size, "#111820")
        contained = ImageOps.contain(
            image.convert("RGB"),
            panel_size,
            Image.Resampling.LANCZOS,
        )
        panel.paste(
            contained,
            (
                (panel_size[0] - contained.width) // 2,
                (panel_size[1] - contained.height) // 2,
            ),
        )
        return panel

    panels = (
        fit_panel(reference_panel),
        fit_panel(front),
        fit_panel(isometric),
    )
    for index, (label, panel) in enumerate(zip(labels, panels)):
        x = 16 + index * (panel_size[0] + 16)
        sheet.paste(panel, (x, 64))
        draw.rectangle((x, 64, x + 196, 94), fill="#111820")
        draw.text((x + 10, 72), label, fill="#ffb000", font=label_font)
    metrics = {
        **_fidelity_metrics(source, reprojection),
        **_silhouette_metrics(
            _reference_projection_mask(spec, source.size),
            reprojection.getchannel("A"),
        ),
    }
    draw.text(
        (24, 632),
        f"{len(spec['cubes'])} native cuboids  |  "
        f"texture PSNR {metrics['texture_psnr_db']:.2f} dB  |  "
        f"source SHA-256 {spec['reference']['sha256'][:16]}…",
        fill="#c8d1d9",
        font=body_font,
        anchor="lm",
    )
    sheet.save(output_dir / "comparison-sheet.png", optimize=True)
    report = {
        "schema_version": 1,
        "renderer": "pillow-orthographic-depthfield-v2",
        "model_id": spec["id"],
        "cuboids": len(spec["cubes"]),
        "source_sha256": spec["reference"]["sha256"],
        "depth_to_length_ratio": depth_to_length_ratio,
        **metrics,
        "views": [
            "front.png",
            "isometric.png",
            "profile.png",
            "reprojection.png",
            "comparison-sheet.png",
        ],
    }
    (output_dir / "evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
