#!/usr/bin/env python3
"""Generate crisp Minecraft-native concept sheets for the model compiler.

These are intentionally schematic cuboid turnarounds, not final textures.  The
deterministic source makes the reconstruction inputs reproducible even when an
external image generator is unavailable.
"""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "model_work" / "references"
SCALE = 4
SIZE = 192


def rect(draw, box, fill, outline="#16121c", width=1):
    draw.rectangle(box, fill=fill, outline=outline, width=width)


def line(draw, points, fill, width=1):
    draw.line(points, fill=fill, width=width, joint="curve")


def hand_reference():
    image = Image.new("RGB", (SIZE, SIZE), "#130c20")
    d = ImageDraw.Draw(image)

    # Rift: stepped, deliberately pixel-native concentric portal.
    for inset, color in ((0, "#120e18"), (3, "#492461"), (6, "#8c3ec0"), (9, "#251334")):
        d.ellipse((43 + inset, 4 + inset // 2, 149 - inset, 43 - inset // 2), fill=color)
    rect(d, (60, 16, 132, 30), "#08060d", "#ad5be2", 2)

    # Segmented forearm and palm, seen at a readable three-quarter angle.
    rect(d, (83, 24, 111, 62), "#665b72")
    rect(d, (79, 56, 116, 79), "#82768c")
    rect(d, (65, 73, 126, 119), "#76677f", "#211827", 2)
    rect(d, (72, 81, 119, 111), "#92849d")
    rect(d, (77, 88, 86, 102), "#bd5368")
    rect(d, (91, 83, 100, 101), "#a43c5d")
    rect(d, (105, 88, 114, 103), "#c06170")

    # Four long fingers with visible joints and hooked black nails.
    xs = (59, 77, 96, 115)
    lengths = (43, 55, 59, 47)
    for index, (x, length) in enumerate(zip(xs, lengths)):
        y = 114 + (index % 2) * 2
        rect(d, (x, y, x + 12, y + 18), "#71627a")
        rect(d, (x - 1, y + 17, x + 11, y + 33), "#8a778f")
        rect(d, (x - 3, y + 31, x + 9, y + length), "#63536d")
        rect(d, (x - 4, y + length - 2, x + 7, y + length + 7), "#211924")

    # Thumb reaches across the foreground as an independent articulated chain.
    rect(d, (120, 91, 139, 105), "#85738d")
    rect(d, (135, 97, 153, 111), "#6b5b74")
    rect(d, (149, 103, 161, 119), "#4e4257")
    rect(d, (155, 114, 164, 124), "#1d1721")

    # Seams make the body read as eroded stone/flesh rather than a flat glove.
    line(d, [(67, 95), (78, 91), (87, 94)], "#3d3047", 2)
    line(d, [(102, 109), (112, 104), (124, 107)], "#3d3047", 2)
    line(d, [(88, 57), (97, 62), (106, 55)], "#b597b4", 1)

    image.resize((SIZE * SCALE, SIZE * SCALE), Image.Resampling.NEAREST).save(
        OUT / "colossal_rift_hand_concept.png"
    )


def grazer_reference():
    image = Image.new("RGB", (SIZE, SIZE), "#141819")
    d = ImageDraw.Draw(image)

    # Hunched, full-body neutral pose with all appendages visually separated.
    rect(d, (75, 25, 117, 56), "#8b7769", "#251b1a", 2)  # head
    rect(d, (83, 49, 112, 66), "#a38975")  # muzzle
    rect(d, (86, 58, 111, 68), "#3e282a")  # hanging jaw
    rect(d, (78, 21, 88, 31), "#57463c")
    rect(d, (108, 20, 119, 31), "#57463c")
    rect(d, (70, 28, 78, 40), "#59483d")
    rect(d, (117, 28, 125, 41), "#59483d")
    rect(d, (85, 35, 91, 42), "#e8cf63")
    rect(d, (104, 35, 110, 42), "#e8cf63")

    rect(d, (82, 63, 111, 78), "#5d4b43")  # neck
    rect(d, (68, 74, 124, 119), "#705f55", "#251b1a", 2)
    rect(d, (78, 79, 114, 114), "#9a8475")
    rect(d, (88, 84, 104, 116), "#bba18c")
    rect(d, (91, 78, 98, 113), "#522d35")  # exposed seam

    # Long humanlike arms, mismatched animal forelimb hands.
    rect(d, (54, 77, 69, 110), "#776359")
    rect(d, (46, 106, 59, 141), "#8f7869")
    rect(d, (43, 137, 60, 148), "#302827")
    rect(d, (123, 78, 138, 111), "#776359")
    rect(d, (135, 107, 148, 141), "#8f7869")
    rect(d, (134, 138, 151, 149), "#302827")

    # Split pelvis and digitigrade legs keep a readable humanoid/ungulate mix.
    rect(d, (74, 116, 118, 132), "#5e4e48")
    rect(d, (76, 128, 93, 156), "#806b5e")
    rect(d, (103, 128, 120, 156), "#806b5e")
    rect(d, (70, 153, 87, 175), "#66534d")
    rect(d, (109, 153, 126, 175), "#66534d")
    rect(d, (63, 171, 87, 182), "#282224")
    rect(d, (109, 171, 133, 182), "#282224")

    # Bone spines and asymmetrical growths establish the mutation silhouette.
    for x, y in ((72, 70), (67, 83), (121, 67), (126, 91), (113, 117)):
        d.polygon([(x, y), (x - 6, y - 10), (x + 2, y - 3)], fill="#d8c4aa", outline="#3a2e2a")
    line(d, [(84, 92), (93, 96), (105, 91), (116, 97)], "#492d32", 2)

    image.resize((SIZE * SCALE, SIZE * SCALE), Image.Resampling.NEAREST).save(
        OUT / "warped_grazer_concept.png"
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    hand_reference()
    grazer_reference()
