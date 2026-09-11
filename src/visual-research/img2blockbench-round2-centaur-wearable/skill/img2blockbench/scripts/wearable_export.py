"""Validation and export helpers for player-wearable model variants."""

from __future__ import annotations

import copy
import re
from typing import Any


ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ATTACHABLE_ID_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float("-inf") < float(value) < float("inf")
    )


def _valid_vector(value: Any, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(_finite_number(item) for item in value)
    )


def validate_wearable(spec: dict[str, Any]) -> list[str]:
    """Validate an optional replaceable-player wearable contract."""
    wearable = spec.get("wearable")
    if wearable is None:
        return []
    if not isinstance(wearable, dict):
        return ["wearable must be an object"]

    errors: list[str] = []
    bone_names = {
        bone.get("name")
        for bone in spec.get("bones", [])
        if isinstance(bone, dict) and isinstance(bone.get("name"), str)
    }
    parent_by_bone = {
        bone["name"]: bone.get("parent")
        for bone in spec.get("bones", [])
        if isinstance(bone, dict) and isinstance(bone.get("name"), str)
    }
    if wearable.get("target") != "minecraft_player":
        errors.append("wearable.target must be minecraft_player")
    if wearable.get("player_variant") not in {"classic", "slim"}:
        errors.append("wearable.player_variant must be classic or slim")
    if wearable.get("occupant_mode") != "replaceable":
        errors.append("wearable.occupant_mode must be replaceable")

    occupant_bones = wearable.get("occupant_bones")
    if not (
        isinstance(occupant_bones, list)
        and bool(occupant_bones)
        and all(isinstance(name, str) for name in occupant_bones)
    ):
        errors.append("wearable.occupant_bones must be a non-empty string array")
        occupant_set: set[str] = set()
    else:
        occupant_set = set(occupant_bones)
        if len(occupant_set) != len(occupant_bones):
            errors.append("wearable.occupant_bones must not contain duplicates")
        missing = sorted(occupant_set - bone_names)
        if missing:
            errors.append(
                "wearable.occupant_bones reference missing bones: " + ", ".join(missing)
            )
        for name, parent in parent_by_bone.items():
            if name not in occupant_set and parent in occupant_set:
                errors.append(
                    f"wearable shell bone {name} cannot be parented to occupant bone {parent}"
                )

    shell_root = wearable.get("shell_root_bone")
    if shell_root not in bone_names:
        errors.append("wearable.shell_root_bone must reference an existing bone")
    elif shell_root in occupant_set:
        errors.append("wearable.shell_root_bone cannot be an occupant bone")

    attachable_id = wearable.get("attachable_identifier")
    if not (
        isinstance(attachable_id, str)
        and bool(ATTACHABLE_ID_RE.fullmatch(attachable_id))
    ):
        errors.append("wearable.attachable_identifier must be a namespaced identifier")

    fit = wearable.get("fit")
    if not isinstance(fit, dict):
        errors.append("wearable.fit must be an object")
    else:
        scale = fit.get("scale")
        if not (_finite_number(scale) and 0 < float(scale) <= 4):
            errors.append("wearable.fit.scale must be within (0, 4]")
        for key in ("offset", "player_anchor"):
            if not _valid_vector(fit.get(key), 3):
                errors.append(f"wearable.fit.{key} must be a 3-number array")
        player_height = fit.get("player_height")
        if not (_finite_number(player_height) and float(player_height) > 0):
            errors.append("wearable.fit.player_height must be positive")
        elif _finite_number(scale):
            fitted_height = float(player_height) * float(scale)
            if not 28.8 <= fitted_height <= 35.2:
                errors.append(
                    "wearable.fit player_height * scale must be within 10% of "
                    "the canonical 32-unit player height"
                )
        if _valid_vector(fit.get("offset"), 3) and _valid_vector(
            fit.get("player_anchor"), 3
        ) and _finite_number(scale):
            transformed_anchor = _transform_point(
                fit["player_anchor"],
                float(scale),
                [float(value) for value in fit["offset"]],
            )
            if transformed_anchor != [0, 0, 0]:
                errors.append(
                    "wearable.fit offset must map player_anchor to [0, 0, 0]"
                )

    collision = wearable.get("collision")
    if not isinstance(collision, dict):
        errors.append("wearable.collision must be an object")
    else:
        for key in ("width", "height", "eye_height"):
            value = collision.get(key)
            if not (_finite_number(value) and float(value) > 0):
                errors.append(f"wearable.collision.{key} must be positive")
        if _finite_number(collision.get("height")) and _finite_number(
            collision.get("eye_height")
        ) and float(collision["eye_height"]) > float(collision["height"]):
            errors.append("wearable.collision.eye_height cannot exceed height")

    for key in ("shell_identity_features", "shell_review_targets"):
        values = wearable.get(key)
        if values is not None and not (
            isinstance(values, list)
            and bool(values)
            and all(isinstance(value, str) and bool(value.strip()) for value in values)
        ):
            errors.append(f"wearable.{key} must be a non-empty string array")

    points = wearable.get("attachment_points")
    if not isinstance(points, list) or not points:
        errors.append("wearable.attachment_points must be a non-empty array")
    else:
        names: set[str] = set()
        for index, point in enumerate(points):
            label = f"wearable.attachment_points[{index}]"
            if not isinstance(point, dict):
                errors.append(f"{label} must be an object")
                continue
            name = point.get("name")
            if not isinstance(name, str) or not ID_RE.fullmatch(name):
                errors.append(f"{label}.name is invalid")
            elif name in names:
                errors.append(f"duplicate wearable attachment point: {name}")
            else:
                names.add(name)
            bone = point.get("bone")
            if bone not in bone_names:
                errors.append(f"{label}.bone must reference an existing bone")
            elif bone in occupant_set:
                errors.append(f"{label}.bone cannot reference an occupant bone")
            if not _valid_vector(point.get("position"), 3):
                errors.append(f"{label}.position must be a 3-number array")
    return errors


def _normalized(value: float) -> int | float:
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded


def _transform_point(
    values: list[Any], scale: float, offset: list[float]
) -> list[int | float]:
    return [
        _normalized(float(values[index]) * scale + offset[index])
        for index in range(3)
    ]


def _transform_size(values: list[Any], scale: float) -> list[int | float]:
    return [_normalized(float(value) * scale) for value in values]


def make_wearable_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return an exoskeleton-only, player-fitted derivative of a valid spec."""
    errors = validate_wearable(spec)
    if errors:
        raise ValueError("invalid wearable contract:\n" + "\n".join(errors))
    wearable = spec["wearable"]
    occupant_bones = set(wearable["occupant_bones"])
    scale = float(wearable["fit"]["scale"])
    offset = [float(value) for value in wearable["fit"]["offset"]]

    shell = copy.deepcopy(spec)
    source_id = str(spec["id"])
    shell["id"] = f"{source_id[:55]}_wearable"
    shell["subject"]["description"] = (
        f"Player-wearable shell derived from {source_id}; the authored pilot proxy is removed"
    )
    shell["subject"]["type"] = "wearable"
    shell["subject"]["uncertainties"] = list(
        dict.fromkeys(
            [
                *shell["subject"].get("uncertainties", []),
                "Locomotion and player-render binding require target runtime integration",
            ]
        )
    )
    shell["bones"] = [
        bone for bone in shell["bones"] if bone["name"] not in occupant_bones
    ]
    shell["cubes"] = [
        cube for cube in shell["cubes"] if cube["bone"] not in occupant_bones
    ]
    retained_cubes = {cube["name"] for cube in shell["cubes"]}
    shell["landmarks"] = [
        landmark
        for landmark in shell["landmarks"]
        if landmark["cube"] in retained_cubes
    ]

    for bone in shell["bones"]:
        bone["pivot"] = _transform_point(bone["pivot"], scale, offset)
    for cube in shell["cubes"]:
        cube["center"] = _transform_point(cube["center"], scale, offset)
        cube["origin"] = _transform_point(cube["origin"], scale, offset)
        cube["size"] = _transform_size(cube["size"], scale)

    shell["collision"] = copy.deepcopy(wearable["collision"])
    quality = shell["quality_contract"]
    quality["identity_features"] = copy.deepcopy(
        wearable.get(
            "shell_identity_features",
            [
                "open player cavity with no baked-in occupant",
                "named waist, control, and foot interfaces around the player",
            ],
        )
    )
    quality["review_targets"] = copy.deepcopy(
        wearable.get(
            "shell_review_targets",
            ["player clearance", "attachment alignment", "shell silhouette", "texture"],
        )
    )
    quality["required_views"] = [
        "front",
        "back",
        "left",
        "right",
        "isometric",
        "wearable-fit-front",
        "wearable-fit-isometric",
    ]
    target = quality["target_cuboids"]
    target[0] = min(int(target[0]), len(shell["cubes"]))
    target[1] = max(int(target[1]), len(shell["cubes"]))
    source_generation = shell.get("generation", {})
    provenance_keys = {
        "anatomical_axis",
        "hidden_geometry_established",
        "lane",
        "single_view_hidden_geometry",
        "source_mesh",
        "source_projection",
        "source_skin_cuboids",
        "texture_transfer",
        "view_count",
        "view_limitations",
        "visual_hull_used",
    }
    generation = {
        key: copy.deepcopy(value)
        for key, value in source_generation.items()
        if key in provenance_keys
    }
    generation["algorithm"] = "replaceable-player-wearable-shell-v1"
    if isinstance(source_generation.get("algorithm"), str):
        generation["source_model_algorithm"] = source_generation["algorithm"]
    transformed_points = []
    for point in wearable["attachment_points"]:
        transformed_points.append(
            {
                **copy.deepcopy(point),
                "authored_position": copy.deepcopy(point["position"]),
                "position": _transform_point(point["position"], scale, offset),
            }
        )
    generation["wearable_export"] = {
        "source_model_id": source_id,
        "target": wearable["target"],
        "player_variant": wearable["player_variant"],
        "occupant_mode": wearable["occupant_mode"],
        "removed_occupant_bones": sorted(occupant_bones),
        "fit": copy.deepcopy(wearable["fit"]),
        "player_anchor_after_fit": _transform_point(
            wearable["fit"]["player_anchor"], scale, offset
        ),
        "fitted_player_height": _normalized(
            float(wearable["fit"]["player_height"]) * scale
        ),
        "attachment_points": transformed_points,
    }
    shell["generation"] = generation
    shell.pop("wearable", None)
    return shell


def make_bedrock_attachable(
    source_spec: dict[str, Any], wearable_spec: dict[str, Any]
) -> dict[str, Any]:
    """Emit a deterministic Bedrock attachable descriptor for a wearable shell."""
    wearable = source_spec["wearable"]
    model_id = wearable_spec["id"]
    return {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": wearable["attachable_identifier"],
                "materials": {"default": "entity_alphatest"},
                "textures": {"default": f"textures/entity/{model_id}"},
                "geometry": {"default": f"geometry.{model_id}"},
                "render_controllers": ["controller.render.default"],
            }
        },
    }
