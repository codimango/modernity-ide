#!/usr/bin/env python3
"""Prepare deterministic foreground and ray-depth evidence for cycle 02."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "benchmarks" / "references" / "02-porsche-911.png"
OUTPUT = Path(__file__).resolve().parent / "inputs"
EXPECTED_SIZE = (1859, 609)


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """Write a reviewed silhouette mask and normalized thickness map."""
    with Image.open(REFERENCE) as opened:
        source = opened.convert("RGB")
    if source.size != EXPECTED_SIZE:
        raise ValueError(f"unexpected reference size: {source.size}")

    mask = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(
        (
            (448, 405),
            (465, 370),
            (493, 345),
            (574, 320),
            (710, 306),
            (760, 252),
            (792, 234),
            (913, 224),
            (1008, 239),
            (1080, 272),
            (1126, 307),
            (1180, 308),
            (1192, 302),
            (1235, 306),
            (1239, 316),
            (1197, 332),
            (1208, 350),
            (1236, 365),
            (1242, 397),
            (1253, 401),
            (1252, 450),
            (1212, 465),
            (1190, 476),
            (1115, 474),
            (1078, 468),
            (867, 480),
            (845, 493),
            (735, 493),
            (699, 481),
            (535, 480),
            (511, 470),
            (466, 460),
            (449, 440),
        ),
        fill=255,
    )
    draw.ellipse((714, 357, 860, 516), fill=255)
    draw.ellipse((1084, 350, 1221, 498), fill=255)
    draw.rectangle((451, 396, 478, 456), fill=255)
    draw.polygon(((1180, 309), (1190, 299), (1237, 304), (1238, 318)), fill=255)

    depth = Image.new("L", source.size, 0)
    depth_draw = ImageDraw.Draw(depth)
    depth_draw.bitmap((0, 0), mask, fill=48)
    depth_draw.polygon(
        (
            (472, 382),
            (522, 345),
            (706, 317),
            (765, 266),
            (801, 244),
            (906, 234),
            (999, 249),
            (1080, 283),
            (1125, 319),
            (1197, 337),
            (1228, 376),
            (1229, 445),
            (1183, 458),
            (1080, 454),
            (874, 463),
            (690, 462),
            (520, 456),
            (478, 438),
        ),
        fill=112,
    )
    depth_draw.polygon(
        (
            (508, 375),
            (616, 333),
            (724, 321),
            (776, 273),
            (817, 249),
            (911, 241),
            (996, 254),
            (1071, 290),
            (1115, 325),
            (1168, 346),
            (1197, 380),
            (1197, 434),
            (1060, 439),
            (879, 448),
            (690, 446),
            (536, 432),
        ),
        fill=176,
    )
    depth_draw.ellipse((721, 363, 854, 507), fill=240)
    depth_draw.ellipse((1090, 356, 1216, 492), fill=240)
    depth_draw.rectangle((604, 360, 1080, 427), fill=220)
    depth = ImageChops.multiply(depth, mask)

    overlay = source.convert("RGBA")
    tint = Image.new("RGBA", source.size, (0, 220, 255, 90))
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
        "coordinate_space": "source pixels; left/top inclusive, right/bottom exclusive",
        "source_size": list(source.size),
        "foreground": {
            "image": "foreground-mask.png",
            "sha256": sha256(mask_path),
            "encoding": "8-bit grayscale; >=128 is foreground",
            "reviewed_bbox_pixels": [448, 224, 1254, 517],
        },
        "depth": {
            "image": "depth-map.png",
            "sha256": sha256(depth_path),
            "encoding": "8-bit grayscale symmetric thickness; 0 is background, 255 is maximum",
            "source": "manually reviewed proxy for a mesh ray-hit thickness pass",
        },
    }
    (OUTPUT / "input-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
