#!/usr/bin/env python3
"""Author the Cycle 3 native volumetric Excalibur benchmark."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from semantic_geometry import SemanticModelBuilder, segment_cube


ROOT = Path(__file__).resolve().parents[3]
CYCLE = Path(__file__).resolve().parent
REFERENCE = ROOT / "benchmarks" / "references" / "03-excalibur.png"
OUTPUT = CYCLE / "model-spec.json"
EXPECTED_SHA256 = "c4cda78a427ac1d2704df6ec8bde6a755361cbcf73628871fe60cfa97f726fcd"


def material(
    base: str,
    shade: str,
    highlight: str,
    pattern: str = "solid",
    scale: int = 1,
) -> dict[str, Any]:
    """Create one deterministic pixel material."""
    return {
        "base": base,
        "shade": shade,
        "highlight": highlight,
        "pattern": pattern,
        "pattern_scale": scale,
    }


def embedded_texture(image: Image.Image) -> dict[str, Any]:
    """Encode an authored image as a deterministic embedded PNG texture."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return {
        "data_uri": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "repeat": [1, 1],
        "offset": [0, 0],
        "center": [0, 0],
        "rotation": 0,
        "wrap": [1001, 1001],
        "flip_y": True,
    }


def blade_texture(*, runes: bool = False, reverse: bool = False) -> dict[str, Any]:
    """Draw an ivory blade face with bevel light and optional legible runes."""
    image = Image.new("RGBA", (32, 96), "#eee9cf")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 2, 95), fill="#c9bb83")
    draw.rectangle((3, 0, 5, 95), fill="#ded3a8")
    draw.rectangle((27, 0, 29, 95), fill="#fffdf0")
    draw.rectangle((30, 0, 31, 95), fill="#baa96e")
    draw.line((17, 0, 19, 95), fill="#fffef6", width=2)
    draw.line((20, 0, 20, 95), fill="#e3d8ae", width=1)
    if runes:
        ink = "#98793c" if not reverse else "#18255f"
        glow = "#c6a956"
        glyphs = (
            ((10, 14), (16, 8), (21, 14), (16, 20), (10, 14)),
            ((11, 28), (21, 28), (15, 34), (21, 40)),
            ((10, 47), (21, 47), (10, 57), (21, 57)),
            ((11, 65), (16, 60), (21, 65), (16, 70), (16, 78)),
            ((10, 85), (16, 80), (22, 85), (16, 91), (10, 85)),
        )
        for index, points in enumerate(glyphs):
            if reverse and index % 2:
                points = tuple((31 - x, y) for x, y in points)
            draw.line(points, fill=glow, width=3, joint="curve")
            draw.line(points, fill=ink, width=1, joint="curve")
    return embedded_texture(image)


def grip_texture(*, reverse: bool = False) -> dict[str, Any]:
    """Draw the blue leather grip and its diagonal wrapped bands."""
    image = Image.new("RGBA", (24, 96), "#172d73")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 4, 95), fill="#0b1742")
    draw.rectangle((17, 0, 23, 95), fill="#294eae")
    draw.rectangle((14, 0, 16, 95), fill="#5575d1")
    offset = 14 if reverse else -10
    for y in range(offset, 112, 16):
        draw.line((0, y, 23, y + (10 if not reverse else -10)), fill="#6e88d8", width=3)
        draw.line((0, y + 3, 23, y + (13 if not reverse else -7)), fill="#0a163f", width=1)
    return embedded_texture(image)


def crest_texture(*, reverse: bool = False) -> dict[str, Any]:
    """Draw a transparent gold-and-navy heraldic crest."""
    image = Image.new("RGBA", (48, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    gold = "#e2c86f"
    dark_gold = "#8f7330"
    navy = "#111d61"
    outline = ((24, 2), (41, 9), (38, 43), (24, 61), (10, 43), (7, 9))
    inner = ((24, 6), (37, 12), (34, 40), (24, 55), (14, 40), (11, 12))
    draw.polygon(outline, fill=dark_gold)
    draw.polygon(inner, fill=gold)
    if reverse:
        draw.polygon(((24, 11), (33, 22), (27, 27), (35, 37), (25, 49), (13, 36), (21, 28), (15, 20)), fill=navy)
        draw.rectangle((22, 14, 26, 45), fill="#31468e")
    else:
        draw.polygon(((23, 10), (33, 17), (28, 28), (38, 35), (30, 45), (23, 38), (17, 50), (10, 41), (18, 30), (12, 20)), fill=navy)
        draw.polygon(((24, 17), (29, 24), (24, 31), (19, 24)), fill="#4b5dab")
    draw.line(outline + (outline[0],), fill="#fff0a2", width=1)
    return embedded_texture(image)


def box(
    name: str,
    bone: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    role: str,
    material_name: str,
    *,
    rotation: tuple[float, float, float] = (0, 0, 0),
    origin: tuple[float, float, float] | None = None,
    faces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one named semantic cuboid."""
    return {
        "name": name,
        "bone": bone,
        "center": list(center),
        "size": list(size),
        "rotation": list(rotation),
        "origin": list(origin or center),
        "role": role,
        "material": material_name,
        "faces": dict(faces or {}),
    }


def main() -> None:
    """Write the complete clean sword specification."""
    if hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("unexpected Excalibur reference hash")
    with Image.open(REFERENCE) as opened:
        if opened.size != (800, 600):
            raise ValueError(f"unexpected Excalibur reference size: {opened.size}")

    materials = {
        "blade_ivory": material("#eee9cf", "#bcae76", "#fffdf1", "gradient", 3),
        "blade_face": {**material("#eee9cf", "#c5b77e", "#fffdf1"), "source_texture": blade_texture()},
        "rune_face": {**material("#eee9cf", "#bcae76", "#fffdf1"), "source_texture": blade_texture(runes=True)},
        "rune_reverse": {**material("#eee9cf", "#bcae76", "#fffdf1"), "source_texture": blade_texture(runes=True, reverse=True)},
        "edge_metal": material("#ddd5b5", "#9c8d58", "#fffef2", "gradient", 2),
        "gold": material("#d6ba58", "#745b1d", "#fff0a1", "gradient", 2),
        "gold_dark": material("#9d7b2e", "#4c3510", "#dec56e", "dither", 2),
        "navy": material("#152263", "#080d30", "#5365b8", "gradient", 2),
        "grip_blue": material("#173276", "#09143d", "#5a79d0", "gradient", 2),
        "grip_front": {**material("#173276", "#09143d", "#5a79d0"), "source_texture": grip_texture()},
        "grip_back": {**material("#173276", "#09143d", "#5a79d0"), "source_texture": grip_texture(reverse=True)},
        "crest_front": {**material("#d6ba58", "#745b1d", "#fff0a1"), "source_texture": crest_texture()},
        "crest_back": {**material("#d6ba58", "#745b1d", "#fff0a1"), "source_texture": crest_texture(reverse=True)},
    }

    builder = SemanticModelBuilder()
    for name, parent, pivot in (
        ("sword", "root", (0, 14.5, 0)),
        ("blade", "sword", (0, 14.5, 0)),
        ("crest", "blade", (0, 19.25, 0)),
        ("guard", "sword", (0, 14.25, 0)),
        ("grip", "sword", (0, 13.0, 0)),
        ("pommel", "grip", (0, 1.15, 0)),
    ):
        builder.add_bone(name, parent, pivot)

    attachments: list[tuple[str, str, tuple[float, float, float]]] = []

    # Broad but very slender blade. Four long masses establish a clean taper;
    # only the final point uses converging edge pieces, avoiding a voxel stair.
    blade_cubes = (
        box(
            "blade_ricasso",
            "blade",
            (0, 19.0, 0),
            (4.8, 9.4, 1.7),
            "broad ivory ricasso carrying the heraldic crest",
            "blade_ivory",
            faces={"south": {"material": "blade_face"}, "north": {"material": "blade_face", "flip_x": True}},
        ),
        box(
            "blade_rune_field",
            "blade",
            (0, 29.2, 0),
            (4.35, 12.0, 1.58),
            "long lower blade with readable authored rune column",
            "blade_ivory",
            faces={"south": {"material": "rune_face"}, "north": {"material": "rune_reverse"}},
        ),
        box(
            "blade_middle",
            "blade",
            (0, 40.3, 0),
            (3.72, 10.8, 1.46),
            "long gently narrowing blade middle",
            "blade_ivory",
            faces={"south": {"material": "blade_face"}, "north": {"material": "blade_face", "flip_x": True}},
        ),
        box(
            "blade_upper",
            "blade",
            (0, 49.4, 0),
            (3.08, 7.8, 1.34),
            "slender upper blade before the converging point",
            "blade_ivory",
            faces={"south": {"material": "blade_face"}, "north": {"material": "blade_face", "flip_x": True}},
        ),
        box(
            "blade_tip_spine",
            "blade",
            (0, 56.1, 0),
            (1.08, 6.5, 1.16),
            "narrow central spine ending in the blade point",
            "blade_face",
        ),
    )
    for cube in blade_cubes:
        builder.add_cube(cube)
    for first, second, joint in (
        ("blade_ricasso", "blade_rune_field", (0, 23.4, 0)),
        ("blade_rune_field", "blade_middle", (0, 35.0, 0)),
        ("blade_middle", "blade_upper", (0, 45.6, 0)),
        ("blade_upper", "blade_tip_spine", (0, 53.0, 0)),
    ):
        attachments.append((first, second, joint))

    for side, sign in (("left", -1), ("right", 1)):
        edge = segment_cube(
            f"blade_tip_{side}_edge",
            "blade",
            (sign * 1.28, 52.95, 0),
            (sign * 0.34, 58.75, 0),
            (1.0, 1.18),
            f"converging {side} cutting edge forming a geometric point",
            "edge_metal",
            overlap=0.24,
        )
        builder.add_cube(edge)
        attachments.append(("blade_upper", edge["name"], (sign * 1.28, 52.95, 0)))
        attachments.append((edge["name"], "blade_tip_spine", (sign * 0.34, 58.75, 0)))

    # Both sides receive distinct authored heraldry. These are thin native
    # overlays, not crops or projected source pixels.
    crest_front = box(
        "raised_front_crest",
        "crest",
        (0, 19.35, 0.91),
        (3.85, 6.05, 0.18),
        "raised transparent gold shield and navy flower crest on observed face",
        "crest_front",
    )
    crest_back = box(
        "raised_back_crest",
        "crest",
        (0, 19.35, -0.91),
        (3.85, 6.05, 0.18),
        "authored gold shield and navy rune crest on inferred reverse face",
        "crest_back",
    )
    front_gem = box(
        "front_crest_gem",
        "crest",
        (0, 20.0, 1.08),
        (0.92, 1.65, 0.22),
        "physical navy lozenge at the center of the front crest",
        "navy",
        rotation=(0, 0, 28),
    )
    for cube in (crest_front, crest_back, front_gem):
        builder.add_cube(cube)
    attachments.extend(
        [
            ("blade_ricasso", "raised_front_crest", (0, 19.35, 0.83)),
            ("blade_ricasso", "raised_back_crest", (0, 19.35, -0.83)),
            ("raised_front_crest", "front_crest_gem", (0, 20.0, 0.99)),
        ]
    )

    # Gold asymmetric guard: the reference's right quillon rises more steeply
    # than the left. Each dark inlay is an independent front-surface chain.
    guard_hub = box(
        "guard_hub",
        "guard",
        (0, 14.35, 0),
        (4.5, 2.75, 2.8),
        "thick gold hilt junction joining blade guard and grip",
        "gold",
        rotation=(0, 0, 4),
    )
    guard_gem = box(
        "guard_hub_gem",
        "guard",
        (0, 14.55, 1.5),
        (1.35, 1.35, 0.24),
        "navy diamond at the structural hilt junction",
        "navy",
        rotation=(0, 0, 45),
    )
    builder.add_cube(guard_hub)
    builder.add_cube(guard_gem)
    attachments.append(("guard_hub", "guard_hub_gem", (0, 14.55, 1.38)))

    left_guard = builder.add_chain(
        "left_quillon",
        "guard",
        ((-1.45, 14.7, 0), (-3.85, 15.05, 0), (-5.75, 16.35, 0), (-6.85, 18.7, 0)),
        (2.75, 2.35, 1.72),
        ("gold", "gold", "gold"),
        "broad left swept gold quillon",
        overlap=0.34,
        depths=(2.55, 2.42, 2.15),
    )
    right_guard = builder.add_chain(
        "right_quillon",
        "guard",
        ((1.4, 14.75, 0), (3.75, 15.55, 0), (5.55, 17.45, 0), (6.45, 20.25, 0)),
        (2.55, 2.15, 1.62),
        ("gold", "gold", "gold"),
        "steeper asymmetric right swept gold quillon",
        overlap=0.34,
        depths=(2.5, 2.35, 2.08),
    )
    attachments.extend(
        [
            ("guard_hub", left_guard.cubes[0], left_guard.joints[0]),
            ("guard_hub", right_guard.cubes[0], right_guard.joints[0]),
            *left_guard.attachments,
            *right_guard.attachments,
        ]
    )

    left_inlay = builder.add_chain(
        "left_quillon_inlay",
        "guard",
        ((-1.45, 14.7, 1.22), (-3.85, 15.05, 1.22), (-5.75, 16.35, 1.22), (-6.85, 18.7, 1.02)),
        (0.42, 0.38, 0.32),
        ("navy", "navy", "navy"),
        "navy front groove following the left quillon",
        overlap=0.18,
        depths=(0.22, 0.22, 0.2),
    )
    right_inlay = builder.add_chain(
        "right_quillon_inlay",
        "guard",
        ((1.4, 14.75, 1.22), (3.75, 15.55, 1.22), (5.55, 17.45, 1.14), (6.45, 20.25, 0.95)),
        (0.42, 0.38, 0.32),
        ("navy", "navy", "navy"),
        "navy front groove following the asymmetric right quillon",
        overlap=0.18,
        depths=(0.22, 0.22, 0.2),
    )
    attachments.extend(
        [
            (left_guard.cubes[0], left_inlay.cubes[0], left_inlay.joints[0]),
            (right_guard.cubes[0], right_inlay.cubes[0], right_inlay.joints[0]),
            *left_inlay.attachments,
            *right_inlay.attachments,
        ]
    )

    # Fully enclosed blue leather grip and two collars. The same authored wrap
    # treatment exists on front and reverse, so inspection never exposes a blank slab.
    grip_core = box(
        "grip_core",
        "grip",
        (0, 7.2, 0),
        (2.2, 11.8, 2.08),
        "substantial blue leather grip with two-sided diagonal wrap",
        "grip_blue",
        faces={"south": {"material": "grip_front"}, "north": {"material": "grip_back"}},
    )
    top_collar = box(
        "grip_top_collar",
        "grip",
        (0, 13.15, 0),
        (2.85, 0.9, 2.55),
        "gold upper collar locked into the guard hub",
        "gold_dark",
    )
    bottom_collar = box(
        "grip_bottom_collar",
        "grip",
        (0, 1.25, 0),
        (2.72, 0.72, 2.48),
        "gold lower collar locked into the pommel",
        "gold_dark",
    )
    pommel_core = box(
        "pommel_core",
        "pommel",
        (0, 0.45, 0),
        (3.05, 1.35, 2.85),
        "weighty gold oval-block pommel",
        "gold",
    )
    pommel_cap = box(
        "pommel_cap",
        "pommel",
        (0, -0.25, 0),
        (2.35, 0.55, 2.25),
        "dark gold terminal cap",
        "gold_dark",
    )
    pommel_gem = box(
        "pommel_gem",
        "pommel",
        (0, 0.48, 1.46),
        (1.0, 0.72, 0.2),
        "small blue pommel jewel visible from the front",
        "navy",
    )
    for cube in (grip_core, top_collar, bottom_collar, pommel_core, pommel_cap, pommel_gem):
        builder.add_cube(cube)
    attachments.extend(
        [
            ("blade_ricasso", "guard_hub", (0, 15.0, 0)),
            ("guard_hub", "grip_top_collar", (0, 13.3, 0)),
            ("grip_top_collar", "grip_core", (0, 12.95, 0)),
            ("grip_core", "grip_bottom_collar", (0, 1.4, 0)),
            ("grip_bottom_collar", "pommel_core", (0, 1.05, 0)),
            ("pommel_core", "pommel_cap", (0, -0.05, 0)),
            ("pommel_core", "pommel_gem", (0, 0.48, 1.39)),
        ]
    )

    names = [cube["name"] for cube in builder.cubes]
    feature_inventory = {
        "blade_main_volumes": sum(name.startswith("blade_") and "tip_" not in name for name in names),
        "tip_volumes": sum(name.startswith("blade_tip_") for name in names),
        "crest_surfaces": sum("crest" in name and name != "front_crest_gem" for name in names),
        "physical_crest_gems": sum(name in {"front_crest_gem", "guard_hub_gem", "pommel_gem"} for name in names),
        "main_quillon_segments": sum(name.startswith(("left_quillon_", "right_quillon_")) and "inlay" not in name for name in names),
        "quillon_inlay_segments": sum("quillon_inlay" in name for name in names),
        "grip_volumes": sum(name.startswith("grip_") for name in names),
        "pommel_volumes": sum(name.startswith("pommel_") for name in names),
        "authored_texture_images": 7,
        "source_projected_faces": 0,
    }

    spec = {
        "schema_version": 1,
        "id": "excalibur",
        "reference": {
            "image": "../../references/03-excalibur.png",
            "sha256": EXPECTED_SHA256,
            "width": 800,
            "height": 600,
        },
        "subject": {
            "type": "sword",
            "description": (
                "Native volumetric Excalibur with a long ivory runed blade, raised navy-gold crest, "
                "asymmetric swept gold guard, blue wrapped grip, and gold pommel"
            ),
            "symmetry": "asymmetric",
            "uncertainties": [
                "The supplied artwork is a single oblique presentation; reverse heraldry is authored rather than observed",
                "The reference glow is represented by bright pixel bevels rather than emissive geometry",
                "No source pixels, silhouette skin, or depth-field relief cuboids are used",
            ],
        },
        "quality_contract": {
            "complexity": "complex",
            "target_cuboids": [30, 55],
            "identity_features": [
                "clean long ivory blade with a geometric point and substantial thin profile",
                "readable five-glyph rune column on the observed face and distinct reverse inscription",
                "raised gold-and-navy heraldic crest above the guard",
                "connected ornate asymmetric swept gold quillons with navy inlay",
                "fully enclosed blue diagonally wrapped grip",
                "gold collars and gemmed pommel",
            ],
            "required_views": [
                "front", "back", "profile", "top", "isometric", "reference-angle",
                "hilt-junction-closeup", "emblem-closeup",
            ],
            "review_targets": [
                "blade taper", "rune readability", "front and reverse finish", "crest identity",
                "guard asymmetry", "hilt attachment", "nonzero profile thickness",
            ],
        },
        "geometry": {"precision": 32},
        "texture": {
            "density": 4,
            "palette_size": 48,
            "gutter": 1,
            "atlas_size": 512,
            "quantize_source": False,
        },
        "materials": materials,
        "bones": builder.bones,
        "cubes": builder.cubes,
        "landmarks": [],
        "collision": {"width": 0.45, "height": 3.75, "eye_height": 3.0},
        "generation": {
            "lane": "agent-authored-semantic-volume",
            "algorithm": "purpose-built-tapered-hard-surface-sword-v1",
            "source_mesh": None,
            "source_skin_cuboids": 0,
            "source_projection": False,
            "anatomical_axis": "+Y blade tip, +Z observed/front face, X guard span",
            "single_view_hidden_geometry": (
                "Reverse blade bevel, rune order, crest, and guard finish are conservative authored inference; "
                "profile thickness is a coherent prop-design prior."
            ),
            "reference_roll_degrees": 44.244512,
            "feature_inventory": feature_inventory,
            "procedural_textures": {
                "source_reference_pixels": False,
                "blade_bevel": True,
                "front_rune_glyphs": 5,
                "reverse_rune_glyphs": 5,
                "front_crest": True,
                "reverse_crest": True,
                "two_sided_grip_wrap": True,
            },
            "declared_attachments": [
                {"first": first, "second": second, "joint": list(joint)}
                for first, second, joint in attachments
            ],
        },
    }
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
