#!/usr/bin/env python3
"""Prepare reviewed silhouette and symmetric thickness evidence for Nian."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from photo_reconstruction import PhotoReconstructionOptions, segment_foreground


ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "benchmarks" / "references" / "04-nian.jpg"
OUTPUT = Path(__file__).resolve().parent / "inputs"
EXPECTED_SIZE = (640, 480)
EXPECTED_SHA256 = "644faf9b0d58763d91daa70a6819c269451fa0e021852356556453758fc23d99"


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fill_small_holes(mask: Image.Image, maximum_area: int = 1600) -> Image.Image:
    """Fill enclosed low-saturation gaps without closing spaces between legs."""
    output = mask.convert("L")
    pixels = output.load()
    visited: set[tuple[int, int]] = set()
    for start_y in range(output.height):
        for start_x in range(output.width):
            start = (start_x, start_y)
            if pixels[start] >= 128 or start in visited:
                continue
            queue = deque([start])
            visited.add(start)
            component: list[tuple[int, int]] = []
            border = False
            while queue:
                x, y = queue.popleft()
                component.append((x, y))
                border = border or x in {0, output.width - 1} or y in {
                    0,
                    output.height - 1,
                }
                for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if (
                        0 <= neighbor[0] < output.width
                        and 0 <= neighbor[1] < output.height
                        and pixels[neighbor] < 128
                        and neighbor not in visited
                    ):
                        visited.add(neighbor)
                        queue.append(neighbor)
            if not border and len(component) <= maximum_area:
                for point in component:
                    pixels[point] = 255
    return output


def main() -> None:
    """Write reviewed foreground and semantic orthographic-thickness evidence."""
    if sha256(REFERENCE) != EXPECTED_SHA256:
        raise ValueError("unexpected Nian reference hash")
    with Image.open(REFERENCE) as opened:
        source = opened.convert("RGB")
    if source.size != EXPECTED_SIZE:
        raise ValueError(f"unexpected reference size: {source.size}")

    segmentation = segment_foreground(
        source.convert("RGBA"),
        PhotoReconstructionOptions(
            analysis_size=256,
            background_mode="auto",
        ),
    )
    automatic_mask = segmentation.mask.point(lambda value: 255 if value >= 128 else 0)
    mask = Image.new("L", source.size, 0)
    source_pixels = source.load()
    automatic_pixels = automatic_mask.load()
    mask_pixels = mask.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue = source_pixels[x, y]
            chroma = max(red, green, blue) - min(red, green, blue)
            if automatic_pixels[x, y] >= 128 and (
                chroma >= 26 or max(red, green, blue) >= 185 or min(red, green, blue) <= 72
            ):
                mask_pixels[x, y] = 255
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    ImageDraw.Draw(mask).polygon(
        (
            (225, 270),
            (397, 262),
            (402, 319),
            (373, 349),
            (356, 334),
            (346, 351),
            (331, 337),
            (318, 353),
            (303, 337),
            (278, 354),
            (249, 345),
            (225, 320),
        ),
        fill=255,
    )
    mask = ImageChops.multiply(fill_small_holes(mask), automatic_mask)

    depth = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(depth)
    draw.bitmap((0, 0), mask, fill=52)
    draw.ellipse((137, 166, 353, 376), fill=154)
    draw.ellipse((223, 102, 463, 404), fill=198)
    draw.ellipse((375, 88, 521, 268), fill=176)
    draw.ellipse((283, 78, 470, 313), fill=142)
    draw.polygon(
        ((214, 210), (303, 201), (337, 443), (259, 456), (231, 358)),
        fill=226,
    )
    draw.polygon(
        ((397, 215), (474, 209), (463, 398), (397, 408), (377, 321)),
        fill=218,
    )
    draw.polygon(
        ((133, 268), (223, 258), (223, 386), (156, 399)),
        fill=162,
    )
    draw.polygon(
        ((205, 248), (286, 246), (268, 384), (206, 390)),
        fill=174,
    )
    draw.ellipse((401, 138, 505, 260), fill=205)
    draw.polygon(
        ((374, 91), (419, 69), (462, 91), (478, 175), (424, 205), (383, 156)),
        fill=116,
    )
    draw.polygon(
        ((424, 81), (505, 79), (578, 120), (563, 170), (493, 138)),
        fill=88,
    )
    depth = ImageChops.multiply(depth, mask)

    overlay = source.convert("RGBA")
    tint = Image.new("RGBA", source.size, (0, 220, 255, 82))
    overlay = Image.composite(Image.alpha_composite(overlay, tint), overlay, mask)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    mask_path = OUTPUT / "foreground-mask.png"
    depth_path = OUTPUT / "depth-map.png"
    overlay_path = OUTPUT / "mask-overlay.png"
    mask.save(mask_path, optimize=True)
    depth.save(depth_path, optimize=True)
    overlay.save(overlay_path, optimize=True)
    contract = {
        "schema_version": 1,
        "algorithm": "reviewed-border-segmentation-and-semantic-depth-v1",
        "coordinate_space": "source pixels; right and bottom bounds are exclusive",
        "source": {
            "image": "../../../references/04-nian.jpg",
            "size": list(source.size),
            "sha256": EXPECTED_SHA256,
            "source_page": "https://www.cadnav.com/3d-models/model-40150.html",
        },
        "foreground": {
            "image": mask_path.name,
            "sha256": sha256(mask_path),
            "encoding": "8-bit grayscale; >=128 is foreground",
            "method": f"{segmentation.method}+reviewed-chroma-shadow-rejection",
            "reviewed_bbox_pixels": list(mask.getbbox() or ()),
            "foreground_fraction": round(
                sum(value >= 128 for value in mask.get_flattened_data())
                / (mask.width * mask.height),
                6,
            ),
        },
        "depth": {
            "image": depth_path.name,
            "sha256": sha256(depth_path),
            "encoding": "8-bit grayscale symmetric thickness; 0 is background",
            "source": "reviewed semantic proxy for an orthographic ray-thickness pass",
            "levels": {
                "silhouette": 52,
                "horns_and_mane": [88, 142],
                "hindquarters": 154,
                "rear_legs": [162, 174],
                "head": [176, 205],
                "torso": 198,
                "forelegs": [218, 226],
            },
        },
    }
    (OUTPUT / "input-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
