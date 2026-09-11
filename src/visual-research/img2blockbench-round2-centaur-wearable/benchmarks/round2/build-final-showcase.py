#!/usr/bin/env python3
"""Build a four-asset source-versus-Blockbench Round 2 review sheet."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "final-showcase.png"
MANIFEST = Path(__file__).resolve().parent / "final-showcase.json"
TILE = (520, 390)
HEADER = 42
GAP = 10
BACKGROUND = (9, 18, 28, 255)
PANEL = (231, 233, 233, 255)
ACCENT = (255, 204, 38, 255)

PAIRS = (
    (
        "Militech Chimera: olive camouflage reference",
        ROOT / "image.png",
        ROOT / "benchmarks" / "round2" / "cycles" / "02-militech-chimera" / "render" / "source-perspective.png",
        2,
    ),
    (
        "Aegis X2: oblique reference",
        ROOT / "image-4.png",
        ROOT / "benchmarks" / "round2" / "cycles" / "05-aegis-x2" / "render" / "source-4-perspective.png",
        5,
    ),
    (
        "Militech Centaur: front reference",
        ROOT / "image-6.png",
        ROOT / "benchmarks" / "round2" / "cycles" / "07-centaur-exoskeleton" / "render" / "source-6-perspective.png",
        7,
    ),
    (
        "Zombie Devil: single independent view",
        ROOT / "image-11.png",
        ROOT / "benchmarks" / "round2" / "cycles" / "08-zombie-devil" / "render" / "reference-angle.png",
        8,
    ),
)


def sha256(path: Path) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fitted_panel(path: Path) -> Image.Image:
    """Place one unmodified image in a fixed review tile."""
    with Image.open(path) as opened:
        fitted = ImageOps.contain(opened.convert("RGBA"), TILE, Image.Resampling.LANCZOS)
    panel = Image.new("RGBA", TILE, PANEL)
    panel.alpha_composite(
        fitted,
        ((TILE[0] - fitted.width) // 2, (TILE[1] - fitted.height) // 2),
    )
    return panel


def main() -> None:
    """Compose four source/model rows and pin every input hash."""
    font = ImageFont.load_default(size=18)
    row_height = HEADER + TILE[1]
    sheet = Image.new(
        "RGBA",
        (TILE[0] * 2 + GAP * 3, row_height * len(PAIRS) + GAP * (len(PAIRS) + 1)),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    records = []
    for index, (label, source_path, render_path, cycle) in enumerate(PAIRS):
        if not source_path.is_file() or not render_path.is_file():
            raise ValueError(f"missing final showcase input for {label}")
        top = GAP + index * (row_height + GAP)
        draw.text((GAP, top + 10), f"{label} - SOURCE", fill=ACCENT, font=font)
        draw.text(
            (GAP * 2 + TILE[0], top + 10),
            f"{label} - GENERATED",
            fill=ACCENT,
            font=font,
        )
        sheet.alpha_composite(fitted_panel(source_path), (GAP, top + HEADER))
        sheet.alpha_composite(
            fitted_panel(render_path),
            (GAP * 2 + TILE[0], top + HEADER),
        )
        records.append(
            {
                "cycle": cycle,
                "label": label,
                "source": source_path.relative_to(ROOT).as_posix(),
                "source_sha256": sha256(source_path),
                "render": render_path.relative_to(ROOT).as_posix(),
                "render_sha256": sha256(render_path),
            }
        )
    sheet.save(OUTPUT, optimize=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "four rows; source left, generated fixed-camera render right",
                "post_render_alignment": False,
                "pairs": records,
                "output_sha256": sha256(OUTPUT),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
