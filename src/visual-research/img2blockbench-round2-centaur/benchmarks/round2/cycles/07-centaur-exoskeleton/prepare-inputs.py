#!/usr/bin/env python3
"""Prepare conservative foreground masks for the three Centaur references."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[4]
CYCLE = Path(__file__).resolve().parent
OUTPUT = CYCLE / "inputs"
REFERENCES = {
    "source-6": (ROOT / "image-6.png", "4182ef6f34f6c701322d39b3ca07e5acf824a5b0b2804a48c6e2182c1698bf92"),
    "source-7": (ROOT / "image-7.png", "c1286f3eb14a6a4642d1c55c73e0edaf3c59f9f3c7b264469d3c8e0d1997f799"),
    "source-8": (ROOT / "image-8.png", "fa98828914ac3d04907d2452ff5627511ce877608c8273c007f7ae167723411c"),
}


def sha256(path: Path) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep the largest four-connected foreground component."""
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best: list[tuple[int, int]] = []
    for start_y, start_x in zip(*np.where(mask & ~seen)):
        if seen[start_y, start_x]:
            continue
        queue: deque[tuple[int, int]] = deque([(int(start_y), int(start_x))])
        seen[start_y, start_x] = True
        component: list[tuple[int, int]] = []
        while queue:
            y_value, x_value = queue.popleft()
            component.append((y_value, x_value))
            for next_y, next_x in (
                (y_value - 1, x_value), (y_value + 1, x_value),
                (y_value, x_value - 1), (y_value, x_value + 1),
            ):
                if (
                    0 <= next_y < height
                    and 0 <= next_x < width
                    and mask[next_y, next_x]
                    and not seen[next_y, next_x]
                ):
                    seen[next_y, next_x] = True
                    queue.append((next_y, next_x))
        if len(component) > len(best):
            best = component
    result = np.zeros_like(mask, dtype=bool)
    if best:
        rows, columns = zip(*best)
        result[np.asarray(rows), np.asarray(columns)] = True
    return result


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill background holes enclosed by the selected silhouette."""
    inverse = ~mask
    height, width = mask.shape
    exterior = np.zeros_like(mask, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for x_value in range(width):
        for y_value in (0, height - 1):
            if inverse[y_value, x_value] and not exterior[y_value, x_value]:
                exterior[y_value, x_value] = True
                queue.append((y_value, x_value))
    for y_value in range(height):
        for x_value in (0, width - 1):
            if inverse[y_value, x_value] and not exterior[y_value, x_value]:
                exterior[y_value, x_value] = True
                queue.append((y_value, x_value))
    while queue:
        y_value, x_value = queue.popleft()
        for next_y, next_x in (
            (y_value - 1, x_value), (y_value + 1, x_value),
            (y_value, x_value - 1), (y_value, x_value + 1),
        ):
            if (
                0 <= next_y < height
                and 0 <= next_x < width
                and inverse[next_y, next_x]
                and not exterior[next_y, next_x]
            ):
                exterior[next_y, next_x] = True
                queue.append((next_y, next_x))
    return ~exterior


def reviewed_mask(source: Image.Image, name: str) -> Image.Image:
    """Separate the dark-teal studio field with conservative hand-reviewed bounds."""
    pixels = np.asarray(source.convert("RGB"), dtype=np.int16)
    red, green, blue = (pixels[:, :, index] for index in range(3))
    light = np.maximum.reduce((red, green, blue))
    chroma = np.maximum.reduce((red, green, blue)) - np.minimum.reduce((red, green, blue))
    # Background samples are dark teal. Metal edges, flesh, the orange shield,
    # and blue cloth depart in brightness or chroma; closing then fills bounded
    # black machinery without claiming cast shadows as subject geometry.
    foreground = (light >= 42) | (chroma >= 20) | ((red >= 30) & (red > green + 5))
    mask = Image.fromarray(np.where(foreground, 255, 0).astype(np.uint8), mode="L")
    mask = mask.filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.MinFilter(9))

    allowed = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(allowed)
    if name == "source-6":
        draw.polygon(
            ((45, 145), (285, 55), (430, 38), (470, 0), (760, 0), (970, 255),
             (975, 620), (820, 770), (800, 985), (575, 1000), (410, 930),
             (300, 1000), (105, 985), (90, 740), (55, 470)), fill=255,
        )
    elif name == "source-7":
        draw.polygon(
            ((150, 0), (450, 0), (585, 50), (780, 40), (920, 185), (920, 490),
             (805, 650), (735, 985), (420, 995), (335, 870), (305, 700),
             (170, 545)), fill=255,
        )
    else:
        draw.polygon(
            ((80, 30), (385, 0), (540, 70), (830, 90), (915, 290), (900, 560),
             (835, 760), (855, 985), (600, 995), (515, 900), (440, 995),
             (245, 980), (225, 800), (75, 585)), fill=255,
        )
    clipped = np.minimum(np.asarray(mask, dtype=np.uint8), np.asarray(allowed, dtype=np.uint8))
    component = largest_component(clipped >= 128)
    filled = fill_holes(component)
    yy, xx = np.indices(component.shape)
    if name == "source-6":
        # Do not let the horizontal studio-floor highlight bridge the feet.
        lower_keep = ((xx >= 120) & (xx <= 275)) | ((xx >= 565) & (xx <= 775))
        filled[(yy >= 910) & ~lower_keep] = False
        filled[yy >= 1003] = False
    elif name == "source-7":
        # The side view has a large triangular floor reflection below the knee.
        filled[yy >= 680] = component[yy >= 680]
        strict_lower = (
            (light >= 55)
            | (chroma >= 28)
            | ((red >= 35) & (red > green + 7))
        )
        strict_image = Image.fromarray(
            np.where(strict_lower, 255, 0).astype(np.uint8), mode="L"
        ).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(5))
        filled[yy >= 680] &= np.asarray(strict_image, dtype=np.uint8)[yy >= 680] >= 128
        lower_keep = (
            ((yy < 800) & (xx >= 360) & (xx <= 760))
            | ((yy >= 800) & (yy < 900) & (xx >= 430) & (xx <= 735))
            | ((yy >= 900) & (xx >= 465) & (xx <= 735))
        )
        filled[(yy >= 680) & ~lower_keep] = False
    else:
        filled[yy >= 880] = component[yy >= 880]
        lower_keep = ((xx >= 260) & (xx <= 465)) | ((xx >= 630) & (xx <= 870))
        filled[(yy >= 880) & ~lower_keep] = False
    return Image.fromarray(filled.astype(np.uint8) * 255, mode="L")


def main() -> None:
    """Write masks, private overlays, and a tracked evidence contract."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records: dict[str, Any] = {}
    for name, (path, expected_hash) in REFERENCES.items():
        if sha256(path) != expected_hash:
            raise ValueError(f"unexpected reference hash: {path.name}")
        with Image.open(path) as opened:
            source = opened.convert("RGB")
        mask = reviewed_mask(source, name)
        mask_path = OUTPUT / f"{name}-mask.png"
        overlay_path = OUTPUT / f"{name}-mask-overlay.png"
        mask.save(mask_path, optimize=True)
        tint = Image.new("RGBA", source.size, (0, 210, 255, 75))
        rgba = source.convert("RGBA")
        Image.composite(Image.alpha_composite(rgba, tint), rgba, mask).save(
            overlay_path, optimize=True
        )
        records[name] = {
            "source": path.name,
            "source_sha256": expected_hash,
            "mask": mask_path.name,
            "mask_sha256": sha256(mask_path),
            "bbox": list(mask.getbbox() or ()),
            "touches_frame_edges": {
                "left": bool(mask.crop((0, 0, 1, 1023)).getbbox()),
                "top": bool(mask.crop((0, 0, 1000, 1)).getbbox()),
                "right": bool(mask.crop((999, 0, 1000, 1023)).getbbox()),
                "bottom": bool(mask.crop((0, 1022, 1000, 1023)).getbbox()),
            },
        }
    contract = {
        "schema_version": 1,
        "method": "dark-studio-separation-plus-hand-reviewed-bounds-v1",
        "coordinate_space": "raw 1000x1023 source pixels; no crop, scale, or recentering",
        "rights": "unknown; private ignored benchmark references only",
        "views": records,
        "limitation": (
            "Masks exclude floor shadows and corner logos. Dark cavities enclosed by visible "
            "metal edges are filled, but these silhouettes do not establish hidden geometry."
        ),
    }
    (OUTPUT / "input-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
