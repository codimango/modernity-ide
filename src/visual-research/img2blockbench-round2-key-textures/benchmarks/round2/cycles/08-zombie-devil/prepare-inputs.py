#!/usr/bin/env python3
"""Prepare reviewed Zombie Devil masks and duplicate-view evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from view_reconstruction import image_content_similarity


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
PRIMARY = ROOT / "image-11.png"
DUPLICATE = ROOT / "image-10.png"
OUTPUT = CYCLE / "inputs"
PRIMARY_SHA256 = "e3c594bc2fc60a63fa7f510fd6557e761219b731be2654a599fc751d024c96df"
DUPLICATE_SHA256 = "77d658a02c89ce685490832c78b0467f10cc06662548570c2ee9d2497cbe03d6"


def sha256(path: Path) -> str:
    """Return one lowercase SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """Write a semantic subject mask without treating a duplicate crop as depth."""
    if sha256(PRIMARY) != PRIMARY_SHA256 or sha256(DUPLICATE) != DUPLICATE_SHA256:
        raise ValueError("unexpected Zombie Devil reference hash")
    with Image.open(PRIMARY) as opened:
        primary = opened.convert("RGB")
    with Image.open(DUPLICATE) as opened:
        duplicate = opened.convert("RGB")
    if primary.size != (513, 754) or duplicate.size != (369, 542):
        raise ValueError("unexpected Zombie Devil reference dimensions")

    mask = Image.new("L", primary.size, 0)
    draw = ImageDraw.Draw(mask)
    parts = {
        "left_massive_arm": (
            (24, 154), (67, 119), (139, 114), (202, 129), (251, 166),
            (239, 207), (196, 227), (130, 225), (70, 209), (29, 191),
        ),
        "brain_stalk": (
            (205, 195), (240, 157), (281, 126), (329, 128), (393, 153),
            (398, 217), (362, 253), (301, 251), (252, 228),
        ),
        "right_massive_arm": (
            (236, 206), (301, 184), (371, 198), (431, 232), (512, 276),
            (512, 332), (482, 378), (439, 397), (389, 367), (344, 335),
            (290, 315), (254, 283),
        ),
        "torso": (
            (114, 277), (169, 247), (245, 246), (307, 281), (354, 337),
            (365, 424), (331, 502), (286, 548), (183, 554), (123, 516),
            (89, 432), (91, 344),
        ),
    }
    for points in parts.values():
        draw.polygon(points, fill=255)
    draw.ellipse((70, 154, 286, 388), fill=255)
    draw.ellipse((287, 37, 410, 170), fill=255)
    draw.ellipse((98, 382, 213, 632), fill=255)
    draw.ellipse((168, 399, 301, 645), fill=255)
    draw.line(
        ((120, 469), (91, 523), (89, 612), (55, 698), (47, 753)),
        fill=255,
        width=20,
        joint="curve",
    )
    draw.line(
        ((272, 478), (306, 533), (349, 596), (386, 668), (367, 727), (300, 753)),
        fill=255,
        width=18,
        joint="curve",
    )
    draw.line(
        ((178, 512), (215, 576), (243, 660), (237, 753)),
        fill=255,
        width=14,
        joint="curve",
    )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    mask_path = OUTPUT / "foreground-mask.png"
    mask.save(mask_path, optimize=True)
    overlay = primary.convert("RGBA")
    tint = Image.new("RGBA", primary.size, (30, 198, 224, 92))
    overlay = Image.composite(Image.alpha_composite(overlay, tint), overlay, mask)
    overlay.save(OUTPUT / "mask-overlay.png", optimize=True)

    similarity = image_content_similarity(primary, duplicate)
    contract = {
        "schema_version": 1,
        "algorithm": "reviewed-semantic-parts-with-duplicate-view-audit-v1",
        "sources": [
            {
                "image": "../../../../../image-11.png",
                "size": list(primary.size),
                "sha256": PRIMARY_SHA256,
                "role": "primary higher-resolution crop",
            },
            {
                "image": "../../../../../image-10.png",
                "size": list(duplicate.size),
                "sha256": DUPLICATE_SHA256,
                "role": "duplicate lower-resolution crop; provenance only",
            },
        ],
        "view_content_similarity": similarity,
        "observed_camera_axes": 1,
        "hidden_geometry_established_from_observed_views": False,
        "foreground": {
            "image": "foreground-mask.png",
            "sha256": sha256(mask_path),
            "encoding": "8-bit grayscale; >=128 is foreground",
            "reviewed_bbox_pixels": list(mask.getbbox() or ()),
            "polygon_parts": {
                name: [list(point) for point in points]
                for name, points in parts.items()
            },
            "limitation": (
                "The crop intersects the bottom frame and other manga figures occlude "
                "the lowest anatomy. The mask includes only the visible Devil silhouette."
            ),
        },
    }
    (OUTPUT / "input-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
