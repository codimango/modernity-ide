#!/usr/bin/env python3
"""Prepare a reviewed silhouette for the Militech Chimera photograph."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "image.png"
ALT_REFERENCE = ROOT / "benchmarks" / "round2" / "references" / "chimera-alt.png"
OUTPUT = CYCLE / "inputs"
EXPECTED_SHA256 = "55ed303da9e7484812f0827922fceb0b07a8bac68ccc1a9c03e39702419eada2"
EXPECTED_SIZE = (600, 900)
EXPECTED_ALT_SHA256 = "28ecd39372be2f3df0a5be657392b31557f8a91fb90136a78722878548bf46f7"
EXPECTED_ALT_SIZE = (736, 414)


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connected_components(
    values: bytearray,
    size: tuple[int, int],
    *,
    foreground: int,
    diagonal: bool,
) -> list[tuple[list[int], bool]]:
    """Return deterministic pixel components and whether each touches the frame."""
    width, height = size
    visited = bytearray(width * height)
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    if diagonal:
        offsets += ((-1, -1), (-1, 1), (1, -1), (1, 1))
    components = []
    for start, value in enumerate(values):
        if value != foreground or visited[start]:
            continue
        queue = deque((start,))
        visited[start] = 1
        pixels = []
        touches_frame = False
        while queue:
            index = queue.popleft()
            pixels.append(index)
            x = index % width
            y = index // width
            touches_frame = touches_frame or x in (0, width - 1) or y in (0, height - 1)
            for offset_x, offset_y in offsets:
                neighbor_x = x + offset_x
                neighbor_y = y + offset_y
                if not (0 <= neighbor_x < width and 0 <= neighbor_y < height):
                    continue
                neighbor = neighbor_y * width + neighbor_x
                if values[neighbor] == foreground and not visited[neighbor]:
                    visited[neighbor] = 1
                    queue.append(neighbor)
        components.append((pixels, touches_frame))
    return components


def alternate_reference_mask(source: Image.Image) -> Image.Image:
    """Extract the pale concept model through a reviewed threshold and ROI."""
    width, height = source.size
    grayscale = source.convert("L")
    values = bytearray(width * height)
    source_values = grayscale.tobytes()
    left, top, right, bottom = (80, 20, 690, 366)
    for y in range(top, bottom):
        row = y * width
        for x in range(left, right):
            if source_values[row + x] >= 60:
                values[row + x] = 1

    cleaned = bytearray(width * height)
    for pixels, _ in connected_components(
        values, source.size, foreground=1, diagonal=True
    ):
        if len(pixels) >= 20:
            for index in pixels:
                cleaned[index] = 1

    # Fill only tiny enclosed paint/detail holes. Larger mechanical negative
    # spaces between the hull and articulated links remain background.
    for pixels, touches_frame in connected_components(
        cleaned, source.size, foreground=0, diagonal=False
    ):
        if not touches_frame and len(pixels) <= 120:
            for index in pixels:
                cleaned[index] = 1
    return Image.frombytes(
        "L", source.size, bytes(255 if value else 0 for value in cleaned)
    )


def main() -> None:
    """Write reviewed masks for both Chimera references."""
    if sha256(REFERENCE) != EXPECTED_SHA256:
        raise ValueError("unexpected Militech Chimera reference hash")
    with Image.open(REFERENCE) as opened:
        source = opened.convert("RGB")
    if source.size != EXPECTED_SIZE:
        raise ValueError(f"unexpected Militech Chimera size: {source.size}")
    if sha256(ALT_REFERENCE) != EXPECTED_ALT_SHA256:
        raise ValueError("unexpected alternate Militech Chimera reference hash")
    with Image.open(ALT_REFERENCE) as opened:
        alternate_source = opened.convert("RGB")
    if alternate_source.size != EXPECTED_ALT_SIZE:
        raise ValueError(f"unexpected alternate Chimera size: {alternate_source.size}")

    mask = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(mask)

    # The photographed feet touch a dark display plinth. These reviewed
    # polygons intentionally describe the machine rather than thresholding the
    # connected floor and its reflections into the benchmark silhouette.
    parts = {
        "upper_armored_cabin": (
            (241, 320), (252, 283), (278, 252), (420, 239), (439, 260),
            (449, 316), (474, 354), (462, 394), (430, 419), (348, 425),
            (285, 410), (231, 383), (224, 349),
        ),
        "lower_hull_and_nose": (
            (183, 384), (219, 350), (301, 326), (363, 343), (421, 350),
            (486, 380), (477, 415), (430, 439), (346, 442), (299, 433),
            (244, 437), (207, 420),
        ),
        "left_rear_hip_armor": (
            (127, 341), (177, 326), (211, 337), (222, 361), (213, 390),
            (178, 408), (143, 404), (130, 382),
        ),
        "viewer_left_upper_link": (
            (224, 364), (195, 376), (169, 395), (149, 411), (119, 414),
            (105, 442), (124, 455), (145, 445), (160, 426), (190, 419),
            (224, 400),
        ),
        "viewer_left_shin_and_foot": (
            (58, 410), (93, 423), (112, 446), (103, 478), (83, 501),
            (58, 520), (28, 533), (4, 518), (12, 489), (31, 458),
        ),
        "center_fore_leg": (
            (341, 383), (388, 396), (417, 418), (418, 447), (405, 472),
            (437, 516), (458, 545), (449, 573), (399, 579), (382, 560),
            (390, 531), (382, 484), (383, 449), (358, 426),
        ),
        "viewer_right_fore_leg": (
            (410, 383), (460, 379), (499, 397), (520, 424), (523, 455),
            (514, 490), (521, 524), (548, 544), (558, 563), (535, 576),
            (505, 570), (498, 544), (506, 519), (504, 483), (492, 445),
            (458, 416), (427, 412),
        ),
        "far_right_leg": (
            (447, 365), (485, 349), (535, 358), (566, 384), (586, 420),
            (585, 449), (570, 469), (561, 493), (537, 495), (520, 470),
            (526, 442), (516, 413), (485, 396), (451, 390),
        ),
    }
    for points in parts.values():
        draw.polygon(points, fill=255)

    # Three thin aerials and the small forward sensor lip are visible identity
    # endpoints that a color threshold would otherwise drop.
    draw.rectangle((295, 214, 299, 255), fill=255)
    draw.rectangle((306, 216, 310, 252), fill=255)
    draw.rectangle((408, 218, 412, 255), fill=255)
    draw.polygon(((182, 381), (202, 367), (217, 370), (207, 394)), fill=255)

    overlay = source.convert("RGBA")
    tint = Image.new("RGBA", source.size, (0, 220, 255, 88))
    overlay = Image.composite(Image.alpha_composite(overlay, tint), overlay, mask)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    mask_path = OUTPUT / "foreground-mask.png"
    overlay_path = OUTPUT / "mask-overlay.png"
    mask.save(mask_path, optimize=True)
    overlay.save(overlay_path, optimize=True)
    alternate_mask = alternate_reference_mask(alternate_source)
    alternate_overlay = alternate_source.convert("RGBA")
    alternate_tint = Image.new("RGBA", alternate_source.size, (255, 184, 38, 92))
    alternate_overlay = Image.composite(
        Image.alpha_composite(alternate_overlay, alternate_tint),
        alternate_overlay,
        alternate_mask,
    )
    alternate_mask_path = OUTPUT / "alternate-foreground-mask.png"
    alternate_overlay_path = OUTPUT / "alternate-mask-overlay.png"
    alternate_mask.save(alternate_mask_path, optimize=True)
    alternate_overlay.save(alternate_overlay_path, optimize=True)
    contract = {
        "schema_version": 1,
        "algorithm": "reviewed-semantic-polygons-v1",
        "coordinate_space": "source pixels; polygon vertices are inclusive",
        "source": {
            "image": "../../../../../image.png",
            "size": list(source.size),
            "sha256": EXPECTED_SHA256,
        },
        "foreground": {
            "image": "foreground-mask.png",
            "sha256": sha256(mask_path),
            "encoding": "8-bit grayscale; >=128 is foreground",
            "reviewed_bbox_pixels": list(mask.getbbox() or ()),
            "parts": {
                name: [list(point) for point in points]
                for name, points in parts.items()
            },
            "limitation": (
                "The single oblique photograph occludes rear joints; the mask "
                "excludes the connected display plinth and cast shadows."
            ),
        },
        "alternate_source": {
            "image": "../../../references/chimera-alt.png",
            "size": list(alternate_source.size),
            "sha256": EXPECTED_ALT_SHA256,
        },
        "alternate_foreground": {
            "algorithm": (
                "reviewed luminance >=60 inside [80,20,690,366], retain 8-connected "
                "components >=20 pixels, fill enclosed holes <=120 pixels"
            ),
            "image": "alternate-foreground-mask.png",
            "sha256": sha256(alternate_mask_path),
            "encoding": "8-bit grayscale; >=128 is foreground",
            "reviewed_bbox_pixels": list(alternate_mask.getbbox() or ()),
            "limitation": (
                "Dark recessed joints are partly ambiguous against the black studio "
                "background; large mechanical negative spaces remain excluded."
            ),
        },
    }
    (OUTPUT / "input-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
