#!/usr/bin/env python3
"""Build a redistributable real-video proof for the calibrated clip route."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIR = ROOT / "skill" / "img2blockbench" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import img2blockbench  # noqa: E402
from view_reconstruction import (  # noqa: E402
    ViewReconstructionOptions,
    extract_clip_view_manifest,
    reconstruct_view_spec,
)

HERE = Path(__file__).resolve().parent


def _frame(path: Path, bounds: tuple[int, int, int, int], color: str) -> None:
    image = Image.new("RGB", (96, 96), "#101820")
    draw = ImageDraw.Draw(image)
    draw.rectangle(bounds, fill=color)
    draw.rectangle((bounds[0] + 4, bounds[1] + 5, bounds[2] - 4, bounds[3] - 5), outline="#f2d16b", width=2)
    image.save(path)


def _mask(path: Path, bounds: tuple[int, int, int, int]) -> None:
    image = Image.new("L", (96, 96), 0)
    ImageDraw.Draw(image).rectangle(bounds, fill=255)
    image.save(path)


def main() -> int:
    """Generate a two-frame clip, extract it with ffmpeg, and compile its hull."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is required to regenerate this proof")

    front_bounds = (30, 31, 66, 73)
    side_bounds = (38, 31, 58, 73)
    _frame(HERE / "source-00.png", front_bounds, "#c74b42")
    _frame(HERE / "source-01.png", side_bounds, "#4167bd")
    _mask(HERE / "front-mask.png", front_bounds)
    _mask(HERE / "side-mask.png", side_bounds)

    clip = HERE / "turntable.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "1",
            "-i",
            str(HERE / "source-%02d.png"),
            "-c:v",
            "libx264",
            "-g",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )

    request = {
        "schema_version": 1,
        "calibration": {
            "projection": "orthographic-yaw",
            "volume_bounds": [[-1, 0, -1], [1, 2, 1]],
        },
        "reference_view": "front",
        "samples": [
            {
                "id": "front",
                "timestamp_seconds": 0,
                "azimuth_degrees": 0,
                "center_px": [48, 80],
                "pixels_per_unit": 28,
                "mask": "front-mask.png",
                "evidence_kind": "observed",
            },
            {
                "id": "side",
                "timestamp_seconds": 1,
                "azimuth_degrees": 90,
                "center_px": [48, 80],
                "pixels_per_unit": 28,
                "mask": "side-mask.png",
                "evidence_kind": "observed",
            },
        ],
    }
    request_path = HERE / "samples.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    extracted = HERE / "extracted" / "views.json"
    extract_clip_view_manifest(
        clip,
        request_path,
        extracted,
        HERE / "extracted" / "frames",
        ffmpeg,
    )
    spec_path = HERE / "model-spec.json"
    spec, evidence = reconstruct_view_spec(
        extracted,
        spec_path,
        "clip_visual_hull_proof",
        "Redistributable two-observed-view clip proof",
        "object",
        ViewReconstructionOptions(
            resolution=20,
            max_cuboids=16,
            target_size=32,
            palette_size=8,
        ),
    )
    errors = img2blockbench.validate_spec(spec, strict=True)
    if errors:
        raise SystemExit("strict validation failed: " + "; ".join(errors))
    img2blockbench.write_json(spec_path, spec)
    (HERE / "evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    build = img2blockbench.build_model(spec_path, HERE / "compiled")
    if not build["audit"]["ok"]:
        raise SystemExit("compiled proof audit failed")
    version = subprocess.run(
        [ffmpeg, "-version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    result = {
        "schema_version": 1,
        "ffmpeg_version": version,
        "two_observed_axes": True,
        "hidden_geometry_established_from_observed_views": evidence[
            "hidden_geometry_established_from_observed_views"
        ],
        "cuboids": len(spec["cubes"]),
        "audit_ok": True,
        "per_view_silhouette": evidence["per_view_silhouette"],
    }
    (HERE / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
