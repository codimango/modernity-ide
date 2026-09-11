#!/usr/bin/env python3
"""Prepare reviewed foreground masks for the three Aegis X2 references."""

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
    "source-3": (
        ROOT / "image-3.png",
        "31bb69536ce0f26540034096402cebc6e006ee9cb7ec56b38deb5bf04afb2e23",
    ),
    "source-4": (
        ROOT / "image-4.png",
        "d53b51bd62a7f64f1a4c792f1bd1005de204ed1ba0475ca4fb527784163ade4b",
    ),
    "source-5": (
        ROOT / "image-5.png",
        "83f83385de5d68c3b4b1f8bc7d371dc086780f4388754a8414b07f0294cfe7a6",
    ),
}


def sha256(path: Path) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep the largest four-connected foreground component."""
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    best: list[tuple[int, int]] = []
    for start_y, start_x in zip(*np.where(mask & ~visited)):
        if visited[start_y, start_x]:
            continue
        queue: deque[tuple[int, int]] = deque([(int(start_y), int(start_x))])
        visited[start_y, start_x] = True
        component: list[tuple[int, int]] = []
        while queue:
            y_value, x_value = queue.popleft()
            component.append((y_value, x_value))
            for next_y, next_x in (
                (y_value - 1, x_value),
                (y_value + 1, x_value),
                (y_value, x_value - 1),
                (y_value, x_value + 1),
            ):
                if (
                    0 <= next_y < height
                    and 0 <= next_x < width
                    and mask[next_y, next_x]
                    and not visited[next_y, next_x]
                ):
                    visited[next_y, next_x] = True
                    queue.append((next_y, next_x))
        if len(component) > len(best):
            best = component
    result = np.zeros_like(mask, dtype=bool)
    if best:
        rows, columns = zip(*best)
        result[np.asarray(rows), np.asarray(columns)] = True
    return result


def fill_internal_holes(mask: Image.Image) -> Image.Image:
    """Fill holes without extending the exterior silhouette."""
    inverse = Image.eval(mask.convert("L"), lambda value: 255 - value)
    exterior = Image.new("L", mask.size, 0)
    source = np.asarray(inverse, dtype=np.uint8) >= 128
    height, width = source.shape
    queue: deque[tuple[int, int]] = deque()
    seen = np.zeros_like(source, dtype=bool)
    for x_value in range(width):
        for y_value in (0, height - 1):
            if source[y_value, x_value] and not seen[y_value, x_value]:
                seen[y_value, x_value] = True
                queue.append((y_value, x_value))
    for y_value in range(height):
        for x_value in (0, width - 1):
            if source[y_value, x_value] and not seen[y_value, x_value]:
                seen[y_value, x_value] = True
                queue.append((y_value, x_value))
    while queue:
        y_value, x_value = queue.popleft()
        for next_y, next_x in (
            (y_value - 1, x_value),
            (y_value + 1, x_value),
            (y_value, x_value - 1),
            (y_value, x_value + 1),
        ):
            if (
                0 <= next_y < height
                and 0 <= next_x < width
                and source[next_y, next_x]
                and not seen[next_y, next_x]
            ):
                seen[next_y, next_x] = True
                queue.append((next_y, next_x))
    exterior_pixels = np.where(seen, 255, 0).astype(np.uint8)
    exterior = Image.fromarray(exterior_pixels, mode="L")
    holes = Image.eval(exterior, lambda value: 255 - value)
    return Image.fromarray(
        np.maximum(np.asarray(mask.convert("L")), np.asarray(holes)), mode="L"
    )


def initial_mask(source: Image.Image, name: str) -> Image.Image:
    """Separate neutral machinery from the dark or red studio backgrounds."""
    pixels = np.asarray(source.convert("RGB"), dtype=np.int16)
    red = pixels[:, :, 0]
    green = pixels[:, :, 1]
    blue = pixels[:, :, 2]
    light = np.maximum.reduce((red, green, blue))
    red_dominance = red - np.maximum(green, blue)
    yy, xx = np.indices(red.shape)
    if name == "source-3":
        region = (xx >= 150) & (xx <= 900) & (yy >= 65)
        foreground = region & (light >= 27)
        # Preserve the dark receiver and pedestal interiors enclosed by metal edges.
        close_size = 11
    elif name == "source-4":
        region = (xx >= 65) & (xx <= 930) & (yy >= 35) & (yy <= 965)
        foreground = region & (light >= 18) & (red_dominance <= 5)
        close_size = 13
    else:
        region = (xx >= 65) & (xx <= 970) & (yy >= 55) & (yy <= 965)
        foreground = region & (light >= 18) & (red_dominance <= 5)
        close_size = 13
    mask = Image.fromarray(np.where(foreground, 255, 0).astype(np.uint8), mode="L")
    mask = mask.filter(ImageFilter.MaxFilter(close_size))
    mask = mask.filter(ImageFilter.MinFilter(close_size - 2))
    component = largest_component(np.asarray(mask, dtype=np.uint8) >= 128)
    return Image.fromarray(np.where(component, 255, 0).astype(np.uint8), mode="L")


def review_mask(source: Image.Image, name: str) -> Image.Image:
    """Apply deterministic hand-reviewed inclusions and logo/floor exclusions."""
    mask = initial_mask(source, name)
    allowed = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(allowed)
    if name == "source-3":
        # The portrait is clipped at the lower edge. The allowed regions reject
        # the brightened black backdrop adjoining the thin cannon barrel.
        draw.polygon(
            ((160, 180), (390, 65), (615, 65), (710, 155), (720, 225),
             (875, 225), (875, 305), (710, 315), (675, 420), (610, 515),
             (420, 525), (315, 405), (160, 345)),
            fill=255,
        )
        draw.rectangle((285, 330, 710, 860), fill=255)
        draw.polygon(((255, 555), (415, 555), (410, 1000), (250, 1000)), fill=255)
        draw.polygon(((520, 555), (755, 555), (750, 1000), (520, 1000)), fill=255)
    elif name == "source-4":
        draw.polygon(
            ((80, 420), (500, 75), (625, 45), (670, 95), (755, 45),
             (910, 95), (900, 175), (775, 255), (765, 430), (700, 570),
             (555, 680), (285, 680), (90, 610)),
            fill=255,
        )
        draw.polygon(((235, 545), (370, 535), (385, 665), (335, 805),
                      (245, 805), (210, 690)), fill=255)
        draw.polygon(((430, 570), (560, 560), (565, 720), (535, 960),
                      (445, 960), (425, 720)), fill=255)
        draw.polygon(((630, 500), (780, 485), (850, 665), (815, 790),
                      (700, 785), (655, 665)), fill=255)
        draw.polygon(((310, 560), (470, 550), (455, 755), (335, 770)), fill=255)
    else:
        draw.polygon(
            ((75, 105), (210, 105), (235, 125), (325, 185), (420, 80),
             (555, 75), (610, 150), (690, 245), (790, 245), (970, 385),
             (970, 520), (790, 520), (715, 625), (535, 695), (280, 675),
             (175, 555), (205, 330)),
            fill=255,
        )
        draw.polygon(((145, 525), (310, 515), (360, 650), (310, 800),
                      (165, 810), (130, 660)), fill=255)
        draw.polygon(((430, 560), (590, 545), (605, 720), (575, 965),
                      (465, 965), (435, 730)), fill=255)
        draw.polygon(((675, 455), (835, 440), (890, 635), (850, 785),
                      (720, 775), (680, 625)), fill=255)
        draw.polygon(((285, 525), (455, 520), (465, 735), (330, 755)), fill=255)
    mask = Image.fromarray(
        np.minimum(np.asarray(mask, dtype=np.uint8), np.asarray(allowed, dtype=np.uint8)),
        mode="L",
    )
    if name == "source-3":
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon(
            ((620, 55), (900, 55), (900, 160), (710, 160), (710, 205), (635, 205)),
            fill=0,
        )
        mask_draw.rectangle((690, 320, 735, 555), fill=0)
        # Dark lower machinery is visibly bounded by the bright support frame
        # but falls below the luminance threshold used for the black backdrop.
        mask_draw.polygon(
            ((393, 720), (576, 720), (576, 846), (525, 846), (525, 1000),
             (405, 1000), (405, 852), (393, 852)),
            fill=255,
        )
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
    return fill_internal_holes(mask)


def main() -> None:
    """Write reviewed masks, overlays and a provenance contract."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records: dict[str, object] = {}
    for name, (path, expected_hash) in REFERENCES.items():
        if sha256(path) != expected_hash:
            raise ValueError(f"unexpected Aegis reference hash: {path.name}")
        with Image.open(path) as opened:
            source = opened.convert("RGB")
        if source.size != (1000, 1000):
            raise ValueError(f"unexpected Aegis reference size: {path.name} {source.size}")
        mask = review_mask(source, name)
        mask_path = OUTPUT / f"{name}-mask.png"
        overlay_path = OUTPUT / f"{name}-mask-overlay.png"
        mask.save(mask_path, optimize=True)
        tint = Image.new("RGBA", source.size, (0, 215, 255, 82))
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
                "left": bool(mask.crop((0, 0, 1, 1000)).getbbox()),
                "top": bool(mask.crop((0, 0, 1000, 1)).getbbox()),
                "right": bool(mask.crop((999, 0, 1000, 1000)).getbbox()),
                "bottom": bool(mask.crop((0, 999, 1000, 1000)).getbbox()),
            },
        }
    contract = {
        "schema_version": 1,
        "method": "reviewed-background-separation-with-semantic-inclusions-v1",
        "rights": "unknown; private ignored benchmark references only",
        "coordinate_space": "raw 1000x1000 source pixels; no crop or recentering",
        "views": records,
        "limitation": (
            "Masks exclude studio floors, cast shadows, reflections, and corner logos. "
            "Dark cavities and thin cables are conservatively joined where their source "
            "edges are visually continuous; masks do not establish hidden geometry."
        ),
    }
    (OUTPUT / "input-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
