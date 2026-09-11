#!/usr/bin/env python3
"""Prepare one observed mask and honest synthetic proxy for Route 5 proof."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "benchmarks" / "references" / "06-scp-173.jpg"
INPUTS = CYCLE / "view-inputs"
EXPECTED_SHA256 = "85d698e25b04dbfc4009a05e1cdbb7dc13c5675d2f7c76e5af8cb5e13f0bd93f"
PIXELS_PER_UNIT = 871 / 48
GROUND_PIXEL = 935


def proxy_point(horizontal: float, vertical: float) -> tuple[int, int]:
    """Project proxy world coordinates into the fixed evidence canvas."""
    return (
        round(375 + horizontal * PIXELS_PER_UNIT),
        round(GROUND_PIXEL - vertical * PIXELS_PER_UNIT),
    )


def ellipse_box(
    center_h: float, center_y: float, radius_h: float, radius_y: float
) -> tuple[int, int, int, int]:
    """Return a PIL ellipse box in calibrated coordinates."""
    left, bottom = proxy_point(center_h - radius_h, center_y - radius_y)
    right, top = proxy_point(center_h + radius_h, center_y + radius_y)
    return left, top, right, bottom


def main() -> None:
    """Write view masks, a synthetic proxy image, and explicit calibration."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected SCP-173 reference hash")
    INPUTS.mkdir(parents=True, exist_ok=True)
    with Image.open(REFERENCE) as opened:
        reference = opened.convert("RGB")
    pixels = np.asarray(reference, dtype=np.int16)
    observed = np.max(
        np.abs(pixels - np.asarray((248, 248, 248), dtype=np.int16)), axis=2
    ) >= 18
    Image.fromarray(observed.astype(np.uint8) * 255, mode="L").save(
        INPUTS / "front-observed-mask.png", optimize=True
    )

    proxy_mask = Image.new("L", reference.size, 0)
    draw = ImageDraw.Draw(proxy_mask)
    # These are explicitly authored conservative depth constraints, not
    # observations. They preserve the measured vertical landmarks while
    # supplying plausible egg, neck, pillar, and stump depths.
    draw.ellipse(ellipse_box(0, 40.2, 4.3, 7.8), fill=255)
    neck_left, neck_bottom = proxy_point(-2.6, 28.4)
    neck_right, neck_top = proxy_point(2.6, 33.4)
    draw.rounded_rectangle(
        (neck_left, neck_top, neck_right, neck_bottom), radius=18, fill=255
    )
    body_left, body_bottom = proxy_point(-3.0, 10.4)
    body_right, body_top = proxy_point(3.0, 31.3)
    draw.rounded_rectangle(
        (body_left, body_top, body_right, body_bottom), radius=24, fill=255
    )
    leg_left, leg_bottom = proxy_point(-1.65, 0)
    leg_right, leg_top = proxy_point(1.65, 12.0)
    draw.rounded_rectangle(
        (leg_left, leg_top, leg_right, leg_bottom), radius=8, fill=255
    )
    # Side-on overlap of the forward bent hands.
    draw.ellipse(ellipse_box(-2.0, 23.5, 1.6, 2.7), fill=255)
    proxy_mask.save(INPUTS / "side-synthetic-mask.png", optimize=True)

    proxy = Image.new("RGB", reference.size, "#f8f8f8")
    proxy_pixels = np.asarray(proxy).copy()
    mask_values = np.asarray(proxy_mask, dtype=np.uint8) >= 128
    rows, columns = np.indices(mask_values.shape)
    noise = ((rows * 17 + columns * 29 + (rows // 9) * 7) % 31) - 15
    base = np.asarray((180, 154, 105), dtype=np.int16)
    shaded = np.clip(base + noise[:, :, None], 0, 255).astype(np.uint8)
    proxy_pixels[mask_values] = shaded[mask_values]
    Image.fromarray(proxy_pixels, mode="RGB").save(
        INPUTS / "side-synthetic.png", optimize=True
    )

    manifest = {
        "schema_version": 1,
        "calibration": {
            "projection": "orthographic-yaw",
            "volume_bounds": [[-10, 0, -5], [10, 50, 5]],
        },
        "reference_view": "front_observed",
        "views": [
            {
                "id": "front_observed",
                "image": "../../../references/06-scp-173.jpg",
                "mask": "front-observed-mask.png",
                "azimuth_degrees": 0,
                "center_px": [347, GROUND_PIXEL],
                "pixels_per_unit": PIXELS_PER_UNIT,
                "evidence_kind": "observed",
            },
            {
                "id": "side_synthetic_proxy",
                "image": "side-synthetic.png",
                "mask": "side-synthetic-mask.png",
                "azimuth_degrees": 90,
                "center_px": [375, GROUND_PIXEL],
                "pixels_per_unit": PIXELS_PER_UNIT,
                "evidence_kind": "synthetic_proxy",
            },
        ],
        "provenance": {
            "front_observed": (
                "thresholded only from the supplied reference against its measured "
                "#f8f8f8 background"
            ),
            "side_synthetic_proxy": (
                "authored depth prior from the semantic proportions; not a "
                "photograph and not hidden-shape evidence"
            ),
            "camera_motion": "not inferred",
        },
    }
    (INPUTS / "views.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
