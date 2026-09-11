#!/usr/bin/env python3
"""Render orthographic audit sheets directly from img2blockbench model specs."""

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FACES = (
    (0, 1, 2, 3),
    (4, 7, 6, 5),
    (0, 4, 5, 1),
    (1, 5, 6, 2),
    (2, 6, 7, 3),
    (3, 7, 4, 0),
)


def vadd(a, b):
    return tuple(a[i] + b[i] for i in range(3))


def vsub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def vmul(a, amount):
    return tuple(value * amount for value in a)


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def unit(a):
    length = math.sqrt(dot(a, a)) or 1.0
    return vmul(a, 1.0 / length)


def rotate_xyz(point, rotation, origin):
    x, y, z = vsub(point, origin)
    rx, ry, rz = (math.radians(value) for value in rotation)
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return vadd((x, y, z), origin)


def cube_vertices(cube):
    center = cube["center"]
    half = [value / 2 for value in cube["size"]]
    points = []
    for x, y, z in (
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ):
        raw = (center[0] + x * half[0], center[1] + y * half[1], center[2] + z * half[2])
        points.append(rotate_xyz(raw, cube["rotation"], cube["origin"]))
    return points


def camera(yaw, pitch):
    yaw, pitch = math.radians(yaw), math.radians(pitch)
    forward = unit((math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch)))
    right = unit(cross((0, 1, 0), forward))
    up = unit(cross(forward, right))
    return right, up, forward


def shade(hex_color, amount):
    rgb = tuple(int(hex_color[index:index + 2], 16) for index in (1, 3, 5))
    return tuple(max(0, min(255, int(channel * amount))) for channel in rgb)


def render(spec, yaw, pitch, selected=None, size=420):
    right, up, forward = camera(yaw, pitch)
    cubes = [cube for cube in spec["cubes"] if selected is None or cube["name"] in selected]
    vertices = [(cube, cube_vertices(cube)) for cube in cubes]
    projected = [
        (dot(point, right), dot(point, up))
        for _, points in vertices
        for point in points
    ]
    min_x = min(x for x, _ in projected)
    max_x = max(x for x, _ in projected)
    min_y = min(y for _, y in projected)
    max_y = max(y for _, y in projected)
    scale = (size - 48) / max(max_x - min_x, max_y - min_y, 1)
    cx = size / 2 - (min_x + max_x) * scale / 2
    cy = size / 2 + (min_y + max_y) * scale / 2

    faces = []
    for cube, points in vertices:
        for indices in FACES:
            face = [points[index] for index in indices]
            normal = unit(cross(vsub(face[1], face[0]), vsub(face[2], face[0])))
            # Cull faces pointing away from the camera.
            if dot(normal, forward) >= -0.001:
                continue
            depth = sum(dot(point, forward) for point in face) / 4
            light = max(0.45, min(1.22, 0.78 + dot(normal, unit((-0.4, 0.8, 0.5))) * 0.30))
            color = shade(spec["materials"][cube["material"]]["base"], light)
            poly = [(cx + dot(point, right) * scale, cy - dot(point, up) * scale) for point in face]
            faces.append((depth, poly, color))

    image = Image.new("RGB", (size, size), "#100d16")
    draw = ImageDraw.Draw(image)
    for _, poly, color in sorted(faces, key=lambda item: item[0], reverse=True):
        draw.polygon(poly, fill=color, outline="#211a27", width=2)
    return image


def audit_sheet(spec_path, output_path):
    spec = json.loads(spec_path.read_text())
    reference = Image.open((spec_path.parent / spec["reference"]["image"]).resolve()).convert("RGB")
    reference.thumbnail((420, 420), Image.Resampling.NEAREST)
    views = [
        ("REFERENCE", reference),
        ("FRONT", render(spec, 0, 0)),
        ("BACK", render(spec, 180, 0)),
        ("LEFT", render(spec, -90, 0)),
        ("RIGHT", render(spec, 90, 0)),
        ("ISOMETRIC", render(spec, 38, 22)),
    ]
    sheet = Image.new("RGB", (3 * 440, 2 * 455), "#09070d")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for index, (label, view) in enumerate(views):
        x = (index % 3) * 440 + 10
        y = (index // 3) * 455 + 28
        sheet.paste(view, (x, y))
        draw.text((x, 5 + (index // 3) * 455), label, fill="#d8cce6", font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)

    if spec["id"] == "warped_grazer":
        focus = {name for name in (
            "head", "muzzle", "jaw", "left_ear", "right_ear", "left_horn", "right_horn"
        )}
        close = Image.new("RGB", (840, 420), "#09070d")
        close.paste(render(spec, -55, 5, focus), (0, 0))
        close.paste(render(spec, 55, 5, focus), (420, 0))
        close.save(output_path.with_name(output_path.stem + "-head-closeups.png"))
    else:
        focus = {cube["name"] for cube in spec["cubes"] if "forearm" not in cube["name"]}
        close = Image.new("RGB", (840, 420), "#09070d")
        close.paste(render(spec, -42, 18, focus), (0, 0))
        close.paste(render(spec, 42, 18, focus), (420, 0))
        close.save(output_path.with_name(output_path.stem + "-joint-closeups.png"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit_sheet(args.spec.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
