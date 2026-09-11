#!/usr/bin/env python3
"""Generate deterministic atlases for the code-authored entity models.

The hand and grazer use Minecraft's ``CubeListBuilder`` box-UV convention.
Their texture rectangles therefore have to be laid out as one unfolded net per
cuboid; the per-face UV atlas emitted by img2blockbench is intentionally kept
as an authoring artifact and is not suitable for those Java models.
"""

from dataclasses import dataclass
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "main" / "resources" / "assets" / "megalophobia" / "textures" / "entity"
ATLAS_SIZE = 512


@dataclass(frozen=True)
class BoxUv:
    name: str
    u: int
    v: int
    width: float
    height: float
    depth: float
    material: str


HAND_PALETTE = {
    "stone_flesh": ((117, 106, 128, 255), (68, 57, 78, 255), (157, 144, 170, 255)),
    "wound": ((164, 60, 93, 255), (87, 35, 54, 255), (220, 113, 129, 255)),
    "nail": ((32, 25, 35, 255), (12, 9, 16, 255), (73, 57, 78, 255)),
}

GRAZER_PALETTE = {
    "hide": ((125, 105, 94, 255), (75, 58, 54, 255), (165, 142, 125, 255)),
    "pale_hide": ((173, 151, 133, 255), (117, 96, 85, 255), (205, 184, 162, 255)),
    "wound": ((91, 48, 56, 255), (45, 24, 30, 255), (162, 74, 89, 255)),
    "bone": ((214, 194, 166, 255), (145, 125, 105, 255), (238, 224, 196, 255)),
    "hoof": ((46, 39, 40, 255), (20, 16, 18, 255), (84, 72, 73, 255)),
}


HAND_BOXES = (
    BoxUv("palm_core", 4, 4, 26, 22, 9, "stone_flesh"),
    BoxUv("palm_heel", 272, 4, 18, 7, 8, "stone_flesh"),
    BoxUv("fissure_left", 82, 4, 2, 10, 0.7, "wound"),
    BoxUv("fissure_center", 96, 4, 2.2, 13, 0.8, "wound"),
    BoxUv("fissure_right", 112, 4, 1.8, 9, 0.7, "wound"),
    BoxUv("wrist", 464, 4, 14, 9, 9, "stone_flesh"),
    BoxUv("forearm_lower", 144, 52, 16, 13, 10, "stone_flesh"),
    BoxUv("forearm_upper", 336, 52, 13, 13, 9, "stone_flesh"),
    BoxUv("index_proximal", 488, 52, 5, 8, 6, "stone_flesh"),
    BoxUv("index_middle", 78, 82, 4.5, 8, 5.5, "stone_flesh"),
    BoxUv("index_distal", 160, 82, 4, 7, 5, "stone_flesh"),
    BoxUv("index_nail", 236, 82, 3, 3, 2, "nail"),
    BoxUv("middle_proximal", 292, 82, 5, 9, 6, "stone_flesh"),
    BoxUv("middle_middle", 380, 82, 4.5, 9, 5.5, "stone_flesh"),
    BoxUv("middle_distal", 462, 82, 4, 7, 5, "stone_flesh"),
    BoxUv("middle_nail", 28, 104, 3, 3, 2, "nail"),
    BoxUv("ring_proximal", 84, 104, 5, 8.5, 6, "stone_flesh"),
    BoxUv("ring_middle", 172, 104, 4.5, 8.5, 5.5, "stone_flesh"),
    BoxUv("ring_distal", 254, 104, 4, 7, 5, "stone_flesh"),
    BoxUv("ring_nail", 330, 104, 3, 3, 2, "nail"),
    BoxUv("little_proximal", 386, 104, 4.5, 7.5, 5.5, "stone_flesh"),
    BoxUv("little_middle", 468, 104, 4, 7, 5, "stone_flesh"),
    BoxUv("little_distal", 42, 125, 3.5, 6, 4.5, "stone_flesh"),
    BoxUv("little_nail", 112, 125, 2.5, 3, 2, "nail"),
    BoxUv("thumb_proximal", 164, 125, 8, 6, 6, "stone_flesh"),
    BoxUv("thumb_middle", 276, 125, 7, 5.5, 5.5, "stone_flesh"),
    BoxUv("thumb_distal", 378, 125, 6, 5, 5, "stone_flesh"),
    BoxUv("thumb_nail", 470, 125, 3, 3, 2, "nail"),
)


GRAZER_BOXES = (
    BoxUv("pelvis", 4, 4, 13, 7, 8, "hide"),
    BoxUv("abdomen", 164, 4, 12, 11, 7, "pale_hide"),
    BoxUv("ribcage", 312, 4, 17, 11, 9, "hide"),
    BoxUv("sternum_rift", 4, 30, 3, 11, 1.5, "wound"),
    BoxUv("neck", 58, 30, 8, 7, 7, "hide"),
    BoxUv("head", 174, 30, 12, 10, 10, "hide"),
    BoxUv("muzzle", 334, 30, 9, 5, 5, "pale_hide"),
    BoxUv("jaw", 450, 30, 8, 3, 5, "wound"),
    BoxUv("left_ear", 58, 56, 4, 6, 2, "hide"),
    BoxUv("right_ear", 122, 56, 4, 6, 2, "hide"),
    BoxUv("left_horn", 186, 56, 3, 6, 3, "bone"),
    BoxUv("right_horn", 246, 56, 3, 7, 3, "bone"),
    BoxUv("left_upper_arm", 306, 56, 6, 11, 7, "hide"),
    BoxUv("left_forearm", 406, 56, 5, 10, 6, "pale_hide"),
    BoxUv("left_hand", 484, 56, 6, 4, 7, "hoof"),
    BoxUv("right_upper_arm", 88, 82, 7, 11, 7, "hide"),
    BoxUv("right_forearm", 196, 82, 6, 10, 6, "pale_hide"),
    BoxUv("right_hand", 292, 82, 6, 4, 7, "hoof"),
    BoxUv("left_thigh", 392, 82, 7, 9, 8, "hide"),
    BoxUv("left_shin", 4, 108, 6, 7, 6, "pale_hide"),
    BoxUv("left_hoof_outer", 100, 108, 3.5, 3, 7, "hoof"),
    BoxUv("left_hoof_inner", 180, 108, 3.5, 3, 7, "hoof"),
    BoxUv("right_thigh", 260, 108, 7, 9, 8, "hide"),
    BoxUv("right_shin", 372, 108, 6, 7, 6, "pale_hide"),
    BoxUv("right_hoof_inner", 468, 108, 3.5, 3, 7, "hoof"),
    BoxUv("right_hoof_outer", 44, 130, 3.5, 3, 7, "hoof"),
    BoxUv("left_scapula_spine", 124, 130, 2, 7, 2, "bone"),
    BoxUv("right_scapula_spine", 172, 130, 2, 9, 2, "bone"),
    BoxUv("lumbar_spine", 220, 130, 2.5, 8, 2.5, "bone"),
    BoxUv("shoulder_growth", 274, 130, 2, 6, 2, "bone"),
)


def box_faces(box):
    """Return the exact UV regions used by ModelPart.Cube in Minecraft 26.2."""
    u0 = box.u
    u1 = u0 + box.depth
    u2 = u1 + box.width
    u22 = u2 + box.width
    u3 = u2 + box.depth
    u4 = u3 + box.width
    v0 = box.v
    v1 = v0 + box.depth
    v2 = v1 + box.height
    return {
        "down": (u1, v0, u2, v1),
        "up": (u2, v0, u22, v1),
        "west": (u0, v1, u1, v2),
        "north": (u1, v1, u2, v2),
        "east": (u2, v1, u3, v2),
        "south": (u3, v1, u4, v2),
    }


def pixel_bounds(rect):
    x0, y0, x1, y1 = rect
    return math.floor(min(x0, x1)), math.floor(min(y0, y1)), math.ceil(max(x0, x1)), math.ceil(max(y0, y1))


def stable_seed(text):
    value = 0x811C9DC5
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value


def paint_region(image, rect, colors, key, face):
    base, shade, highlight = colors
    x0, y0, x1, y1 = pixel_bounds(rect)
    seed = stable_seed(f"{key}:{face}")
    face_bias = {"up": 1, "down": -1, "north": 1, "south": -1}.get(face, 0)
    for y in range(y0, y1):
        for x in range(x0, x1):
            noise = (seed ^ (x * 0x45D9F3B) ^ (y * 0x119DE1F3)) & 0xFFFFFFFF
            if (noise % 17 == 0) or (face_bias > 0 and noise % 13 == 0):
                color = highlight
            elif (noise % 9 == 0) or (face_bias < 0 and noise % 11 == 0):
                color = shade
            else:
                color = base
            image.putpixel((x, y), color)


def paint_box(image, box, palette):
    faces = box_faces(box)
    for face, rect in faces.items():
        paint_region(image, rect, palette[box.material], box.name, face)
    return faces


def validate_layout(label, boxes):
    names = [box.name for box in boxes]
    if len(names) != len(set(names)):
        raise ValueError(f"{label} contains duplicate box names")

    extents = []
    for box in boxes:
        regions = [pixel_bounds(rect) for rect in box_faces(box).values()]
        extent = (
            min(region[0] for region in regions),
            min(region[1] for region in regions),
            max(region[2] for region in regions),
            max(region[3] for region in regions),
        )
        if not (0 <= extent[0] < extent[2] <= ATLAS_SIZE and 0 <= extent[1] < extent[3] <= ATLAS_SIZE):
            raise ValueError(f"{label}:{box.name} exceeds the {ATLAS_SIZE}px atlas: {extent}")
        for other_name, other in extents:
            overlaps = (
                max(extent[0], other[0]) < min(extent[2], other[2])
                and max(extent[1], other[1]) < min(extent[3], other[3])
            )
            if overlaps:
                raise ValueError(f"{label}:{box.name} overlaps {other_name}")
        extents.append((box.name, extent))


def colossal_rift_hand():
    image = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (0, 0, 0, 0))
    regions = {box.name: paint_box(image, box, HAND_PALETTE) for box in HAND_BOXES}
    draw = ImageDraw.Draw(image)

    # The Java hand faces -Z, so its readable palm is the vanilla north face.
    palm = regions["palm_core"]["north"]
    x0, y0, x1, y1 = pixel_bounds(palm)
    dark = HAND_PALETTE["wound"][1]
    bright = HAND_PALETTE["wound"][2]
    for fraction, length, bend in ((0.27, 13, -2), (0.50, 16, 2), (0.73, 12, -1)):
        x = x0 + round((x1 - x0 - 1) * fraction)
        top = y0 + 3
        bottom = min(y1 - 2, top + length)
        draw.line((x, top, x, bottom), fill=dark, width=2)
        draw.line((x, top + 1, x + bend, top + 5), fill=bright, width=1)
        draw.line((x, top + 7, x - bend, min(bottom, top + 11)), fill=bright, width=1)

    # Black nail faces get a sharp violet ridge that remains visible at scale.
    for box in HAND_BOXES:
        if box.material != "nail":
            continue
        nail = box_faces(box)["north"]
        nx0, ny0, nx1, _ = pixel_bounds(nail)
        draw.line((nx0, ny0, nx1 - 1, ny0), fill=HAND_PALETTE["nail"][2], width=1)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / "colossal_rift_hand.png", optimize=False, compress_level=9)


def warped_grazer():
    image = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (0, 0, 0, 0))
    regions = {box.name: paint_box(image, box, GRAZER_PALETTE) for box in GRAZER_BOXES}
    draw = ImageDraw.Draw(image)

    # +Z in the authored spec becomes -Z in the Java model: features belong on north.
    head = regions["head"]["north"]
    hx0, hy0, hx1, _ = pixel_bounds(head)
    socket = (44, 34, 25, 255)
    iris = (240, 217, 104, 255)
    pupil = (9, 7, 8, 255)
    eye_y = hy0 + 3
    for eye_x in (hx0 + 3, hx1 - 4):
        draw.rectangle((eye_x - 1, eye_y - 1, eye_x + 1, eye_y + 1), fill=socket)
        draw.point((eye_x, eye_y), fill=iris)
        if eye_x == hx1 - 4:
            draw.point((eye_x, eye_y + 1), fill=pupil)

    muzzle = regions["muzzle"]["north"]
    mx0, my0, mx1, my1 = pixel_bounds(muzzle)
    for nostril_x in (mx0 + 2, mx1 - 3):
        draw.rectangle((nostril_x, my0 + 2, nostril_x + 1, min(my1 - 1, my0 + 3)), fill=pupil)

    jaw = regions["jaw"]["north"]
    jx0, jy0, jx1, jy1 = pixel_bounds(jaw)
    tooth = GRAZER_PALETTE["bone"][2]
    for x in range(jx0 + 1, jx1 - 1, 2):
        draw.line((x, jy0, x, min(jy1 - 1, jy0 + 1)), fill=tooth, width=1)

    # Rib-like pale slashes frame the protruding sternum wound.
    chest = regions["ribcage"]["north"]
    cx0, cy0, cx1, cy1 = pixel_bounds(chest)
    rib = GRAZER_PALETTE["pale_hide"][2]
    middle = (cx0 + cx1) // 2
    for offset, y in ((3, cy0 + 3), (5, cy0 + 6), (7, cy0 + 9)):
        if y < cy1:
            draw.line((middle - offset, y, middle - 1, y + 1), fill=rib, width=1)
            draw.line((middle + 1, y + 1, middle + offset, y), fill=rib, width=1)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / "warped_grazer.png", optimize=False, compress_level=9)


def watching_eye():
    image = Image.new("RGBA", (64, 64), (215, 195, 177, 255))
    draw = ImageDraw.Draw(image)
    randomizer = random.Random(0xE1E5)

    # 32x32 quadrants: sclera, iris, lid, pupil. Cube UVs select one region.
    draw.rectangle((32, 0, 63, 31), fill=(74, 126, 111, 255))
    draw.rectangle((0, 32, 31, 63), fill=(82, 36, 45, 255))
    draw.rectangle((32, 32, 63, 63), fill=(11, 8, 13, 255))
    for _ in range(28):
        x = randomizer.randrange(1, 30)
        y = randomizer.randrange(1, 30)
        length = randomizer.randrange(2, 7)
        draw.line((x, y, min(30, x + length), y + randomizer.choice((-1, 0, 1))), fill=(155, 65, 73, 255))
    for y in range(1, 31, 3):
        draw.point((32 + (y * 7) % 30, y), fill=(128, 190, 154, 255))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / "watching_eye.png")


if __name__ == "__main__":
    validate_layout("colossal_rift_hand", HAND_BOXES)
    validate_layout("warped_grazer", GRAZER_BOXES)
    colossal_rift_hand()
    warped_grazer()
    watching_eye()
