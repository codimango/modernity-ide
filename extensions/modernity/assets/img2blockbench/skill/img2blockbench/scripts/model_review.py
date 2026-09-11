#!/usr/bin/env python3
"""Create deterministic model-only evidence for all-angle visual review."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFont

from img2blockbench import (
    build_texture,
    resolve_reference_path,
    sha256_file,
    validated_spec,
    write_json,
)
from model_provenance import MODEL_CONTENT_HASH_METHOD, model_content_sha256
from semantic_evidence import STANDARD_VIEWS, foreground_mask, render_view


REQUIRED_VIEWS = (
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "isometric",
)
VIEW_DIRECTIONS = {
    "front": STANDARD_VIEWS["front"],
    "back": STANDARD_VIEWS["back"],
    "left": STANDARD_VIEWS["left"],
    "right": STANDARD_VIEWS["right"],
    "top": STANDARD_VIEWS["top"],
    "bottom": (0.001, -1.0, 0.0),
    "isometric": STANDARD_VIEWS["isometric"],
}
DEFAULT_BACKGROUND = (13, 20, 28, 255)
MANIFEST_NAME = "model-review.json"
SHEET_NAME = "all-angle-sheet.png"


def _numpy() -> Any:
    """Load the optional review dependency with an actionable message."""
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError(
            "model review requires numpy; install "
            "img2blockbench[semantic-evidence] or img2blockbench[all]"
        ) from exc
    return np


def _validated_image_size(value: Sequence[int]) -> tuple[int, int]:
    """Return a bounded render size suitable for deterministic evidence."""
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ValueError("image_size must contain two positive integers") from exc
    if (
        len(items) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) for item in items)
        or any(item < 64 or item > 2048 for item in items)
    ):
        raise ValueError("image_size must contain two integers within 64..2048")
    return int(items[0]), int(items[1])


def _validated_background(value: Sequence[int]) -> tuple[int, int, int, int]:
    """Return an opaque RGBA background usable for foreground extraction."""
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ValueError("background must contain four byte values") from exc
    if (
        len(items) != 4
        or any(not isinstance(item, int) or isinstance(item, bool) for item in items)
        or any(item < 0 or item > 255 for item in items)
        or items[3] != 255
    ):
        raise ValueError("background must be four byte values with alpha 255")
    return tuple(int(item) for item in items)


def _save_png(image: Image.Image, path: Path) -> None:
    """Write one metadata-free deterministic PNG."""
    image.save(path, format="PNG", optimize=True, compress_level=9)


def _view_metrics(
    image: Image.Image,
    background: tuple[int, int, int, int],
) -> dict[str, Any]:
    """Measure the foreground silhouette and its pixel-space bounding box."""
    np = _numpy()
    mask_image = foreground_mask(image, background[:3])
    mask = np.asarray(mask_image, dtype=np.uint8) >= 128
    foreground_pixels = int(np.count_nonzero(mask))
    image_width, image_height = image.size
    bbox_value = mask_image.getbbox()
    if bbox_value is None:
        bbox = None
        bbox_width = 0
        bbox_height = 0
        bbox_area = 0
        bbox_aspect_ratio = None
        bbox_fill_fraction = 0.0
        touches_frame_edges = {
            "left": False,
            "top": False,
            "right": False,
            "bottom": False,
        }
    else:
        left, top, right, bottom = (int(item) for item in bbox_value)
        bbox = [left, top, right, bottom]
        bbox_width = right - left
        bbox_height = bottom - top
        bbox_area = bbox_width * bbox_height
        bbox_aspect_ratio = round(bbox_width / bbox_height, 6)
        bbox_fill_fraction = round(foreground_pixels / bbox_area, 6)
        touches_frame_edges = {
            "left": left == 0,
            "top": top == 0,
            "right": right == image_width,
            "bottom": bottom == image_height,
        }
    return {
        "foreground": {
            "pixels": foreground_pixels,
            "fraction": round(foreground_pixels / (image_width * image_height), 6),
        },
        "silhouette": {
            "nonempty": foreground_pixels > 0,
            "sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
        },
        "bbox": {
            "pixels": bbox,
            "width": bbox_width,
            "height": bbox_height,
            "area": bbox_area,
            "aspect_ratio": bbox_aspect_ratio,
            "foreground_fill_fraction": bbox_fill_fraction,
            "touches_frame_edges": touches_frame_edges,
        },
    }


def _model_only_sheet(
    views: dict[str, Image.Image],
    image_size: tuple[int, int],
) -> Image.Image:
    """Compose a labeled sheet exclusively from generated model renders."""
    columns = 4
    rows = 2
    header_height = 28
    tile_width = min(image_size[0], 320)
    tile_height = min(image_size[1], 320)
    sheet = Image.new(
        "RGB",
        (columns * tile_width, rows * (tile_height + header_height)),
        "#09111a",
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, view_id in enumerate(REQUIRED_VIEWS):
        x = index % columns * tile_width
        y = index // columns * (tile_height + header_height)
        source = views[view_id]
        fitted = source.copy()
        fitted.thumbnail((tile_width, tile_height), Image.Resampling.NEAREST)
        panel = Image.new("RGBA", (tile_width, tile_height), "#0d141c")
        panel.alpha_composite(
            fitted,
            ((tile_width - fitted.width) // 2, (tile_height - fitted.height) // 2),
        )
        sheet.paste(panel.convert("RGB"), (x, y + header_height))
        draw.text(
            (x + 10, y + 9),
            view_id.upper(),
            fill="#f0bd31",
            font=font,
        )
    return sheet


def render_model_review(
    spec_path: Path | str,
    output_dir: Path | str,
    *,
    image_size: tuple[int, int] = (640, 640),
    background: tuple[int, int, int, int] = DEFAULT_BACKGROUND,
) -> dict[str, Any]:
    """Render a strict spec into portable model-only all-angle evidence.

    Completion means that the deterministic evidence bundle is structurally
    intact. It never means that the model resembles its source; an agent must
    inspect the rendered views before making that judgment.
    """
    spec_input = Path(spec_path)
    destination = Path(output_dir)
    render_size = _validated_image_size(image_size)
    render_background = _validated_background(background)
    spec = validated_spec(spec_input, strict=True)
    spec_sha256 = sha256_file(spec_input)
    atlas, placements = build_texture(spec)
    if destination.is_symlink() or (
        destination.exists() and not destination.is_dir()
    ):
        raise ValueError("review output must be a real directory path")
    protected_inputs = {
        spec_input.resolve(),
        resolve_reference_path(spec_input, spec).resolve(),
    }
    planned_outputs = [
        *(destination / f"{view_id}.png" for view_id in REQUIRED_VIEWS),
        destination / SHEET_NAME,
        destination / MANIFEST_NAME,
    ]
    for path in planned_outputs:
        if path.resolve() in protected_inputs:
            raise ValueError(
                f"review output would overwrite an input file: {path.name}"
            )
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"review output path is unsafe: {path}")
    destination.mkdir(parents=True, exist_ok=True)

    rendered_views: dict[str, Image.Image] = {}
    view_records: list[dict[str, Any]] = []
    for view_id in REQUIRED_VIEWS:
        image = render_view(
            spec,
            VIEW_DIRECTIONS[view_id],
            atlas_image=atlas,
            placements=placements,
            size=render_size,
            background=render_background,
        )
        image_path = destination / f"{view_id}.png"
        _save_png(image, image_path)
        image_sha256 = sha256_file(image_path)
        rendered_views[view_id] = image
        view_records.append(
            {
                "id": view_id,
                "image": image_path.relative_to(destination).as_posix(),
                "image_sha256": image_sha256,
                "bytes": image_path.stat().st_size,
                "image_size": list(image.size),
                "direction": [float(value) for value in VIEW_DIRECTIONS[view_id]],
                "metrics": _view_metrics(image, render_background),
            }
        )

    sheet_path = destination / SHEET_NAME
    _save_png(_model_only_sheet(rendered_views, render_size), sheet_path)

    generated_views = [record["id"] for record in view_records]
    image_hashes = [record["image_sha256"] for record in view_records]
    all_views_present = generated_views == list(REQUIRED_VIEWS)
    all_silhouettes_nonempty = all(
        record["metrics"]["silhouette"]["nonempty"] for record in view_records
    )
    unique_view_hashes = len(set(image_hashes)) == len(REQUIRED_VIEWS)
    portable_paths = all(
        not Path(record["image"]).is_absolute()
        and ".." not in Path(record["image"]).parts
        for record in view_records
    )
    gates = {
        "all_required_views_present": all_views_present,
        "all_silhouettes_nonempty": all_silhouettes_nonempty,
        "all_view_hashes_unique": unique_view_hashes,
        "portable_relative_paths": portable_paths,
    }
    blocking_gates = {
        key: gates[key]
        for key in (
            "all_required_views_present",
            "all_silhouettes_nonempty",
            "portable_relative_paths",
        )
    }
    complete = all(blocking_gates.values())
    manifest = {
        "schema_version": 1,
        "method": "semantic-model-only-all-angle-review-v1",
        "renderer": "semantic_evidence.render_view",
        "model_id": spec["id"],
        "model_spec": {
            "file_name": spec_input.name,
            "sha256": spec_sha256,
            "content_hash_method": MODEL_CONTENT_HASH_METHOD,
            "content_sha256": model_content_sha256(spec),
        },
        "model_only": True,
        "source_imagery_included": False,
        "resemblance_claimed": False,
        "agent_visual_review_required": True,
        "approval_status": "pending_agent_visual_review",
        "required_views": list(REQUIRED_VIEWS),
        "generated_views": generated_views,
        "views": view_records,
        "all_angle_sheet": {
            "image": sheet_path.relative_to(destination).as_posix(),
            "image_sha256": sha256_file(sheet_path),
            "bytes": sheet_path.stat().st_size,
            "model_only": True,
        },
        "view_sha256": {
            record["id"]: record["image_sha256"] for record in view_records
        },
        "unique_hash_gate": {
            "passed": unique_view_hashes,
            "unique_hashes": len(set(image_hashes)),
            "required_hashes": len(REQUIRED_VIEWS),
        },
        "gates": gates,
        "blocking_gates": blocking_gates,
        "warnings": (
            []
            if unique_view_hashes
            else [
                "some rendered views are pixel-identical; inspect whether this is "
                "legitimate symmetry or under-modeled directional structure"
            ]
        ),
        "complete": complete,
        "status": "complete" if complete else "incomplete",
        "scope": (
            "Generated model geometry and texture only; no source/reference image "
            "is included and no resemblance conclusion is made."
        ),
    }
    write_json(destination / MANIFEST_NAME, manifest)
    return manifest
