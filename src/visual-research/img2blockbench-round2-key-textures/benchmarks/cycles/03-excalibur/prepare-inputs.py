#!/usr/bin/env python3
"""Prepare deterministic silhouette and thickness evidence for cycle 03."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "benchmarks" / "references" / "03-excalibur.png"
OUTPUT = Path(__file__).resolve().parent / "inputs"
EXPECTED_SIZE = (800, 600)
EXPECTED_SHA256 = "c4cda78a427ac1d2704df6ec8bde6a755361cbcf73628871fe60cfa97f726fcd"

BLADE = (
    (124, 24),
    (151, 40),
    (486, 367),
    (524, 418),
    (503, 440),
    (459, 391),
    (137, 70),
)
UPPER_GUARD = (
    (516, 431),
    (548, 410),
    (571, 370),
    (604, 380),
    (590, 425),
    (557, 460),
)
LOWER_GUARD = (
    (526, 441),
    (504, 469),
    (470, 474),
    (480, 506),
    (519, 489),
    (551, 457),
)
GUARD_CORE = ((500, 424), (529, 414), (568, 449), (547, 474), (515, 454))
GRIP = ((548, 452), (569, 460), (664, 554), (651, 568), (541, 464))


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def draw_subject(draw: ImageDraw.ImageDraw, fill: int) -> None:
    """Draw the reviewed connected silhouette in back-to-front part order."""
    draw.polygon(BLADE, fill=fill)
    draw.polygon(UPPER_GUARD, fill=fill)
    draw.polygon(LOWER_GUARD, fill=fill)
    draw.polygon(GUARD_CORE, fill=fill)
    draw.polygon(GRIP, fill=fill)
    draw.ellipse((647, 549, 668, 571), fill=fill)


def main() -> None:
    """Write reviewed mask, thickness map, overlay, and a hashed input contract."""
    if sha256(REFERENCE) != EXPECTED_SHA256:
        raise ValueError("unexpected Excalibur reference hash")
    with Image.open(REFERENCE) as opened:
        source = opened.convert("RGB")
    if source.size != EXPECTED_SIZE:
        raise ValueError(f"unexpected reference size: {source.size}")

    mask = Image.new("L", source.size, 0)
    draw_subject(ImageDraw.Draw(mask), 255)

    depth = Image.new("L", source.size, 0)
    depth_draw = ImageDraw.Draw(depth)
    draw_subject(depth_draw, 76)
    depth_draw.polygon(BLADE, fill=112)
    depth_draw.polygon(
        ((132, 31), (148, 45), (491, 383), (511, 416), (493, 421), (144, 68)),
        fill=150,
    )
    depth_draw.polygon(GRIP, fill=164)
    depth_draw.polygon(UPPER_GUARD, fill=224)
    depth_draw.polygon(LOWER_GUARD, fill=224)
    depth_draw.polygon(GUARD_CORE, fill=240)
    depth_draw.ellipse((647, 549, 668, 571), fill=255)
    depth = ImageChops.multiply(depth, mask)

    overlay = source.convert("RGBA")
    tint = Image.new("RGBA", source.size, (0, 220, 255, 86))
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
        "algorithm": "reviewed-semantic-polygons-v1",
        "coordinate_space": "source pixels; polygon vertices are inclusive",
        "source": {
            "image": "../../../references/03-excalibur.png",
            "size": list(source.size),
            "sha256": EXPECTED_SHA256,
        },
        "foreground": {
            "image": "foreground-mask.png",
            "sha256": sha256(mask_path),
            "encoding": "8-bit grayscale; >=128 is foreground",
            "reviewed_bbox_pixels": list(mask.getbbox() or ()),
            "parts": {
                "blade": [list(point) for point in BLADE],
                "upper_guard": [list(point) for point in UPPER_GUARD],
                "lower_guard": [list(point) for point in LOWER_GUARD],
                "guard_core": [list(point) for point in GUARD_CORE],
                "grip": [list(point) for point in GRIP],
                "pommel_ellipse": [647, 549, 668, 571],
            },
        },
        "depth": {
            "image": "depth-map.png",
            "sha256": sha256(depth_path),
            "encoding": "8-bit grayscale symmetric thickness; 0 is background",
            "levels": {
                "silhouette_base": 76,
                "blade": 112,
                "blade_bevel": 150,
                "grip": 164,
                "guard": 224,
                "guard_core": 240,
                "pommel": 255,
            },
            "source": "reviewed semantic proxy for an orthographic ray-thickness pass",
        },
    }
    (OUTPUT / "input-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
