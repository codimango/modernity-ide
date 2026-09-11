# Minecraft model specification

## Contents

1. [Top-level contract](#top-level-contract)
2. [Bones](#bones)
3. [Cuboids](#cuboids)
4. [Materials and faces](#materials-and-faces)
5. [Landmarks](#landmarks)
6. [Quality contract](#quality-contract)
7. [Coordinate system](#coordinate-system)

## Top-level contract

Use schema version `1`.

```json
{
  "schema_version": 1,
  "id": "red_panda",
  "reference": {
    "image": "reference.png",
    "sha256": "64 lowercase hexadecimal characters",
    "width": 1024,
    "height": 1024
  },
  "subject": {
    "type": "mob",
    "description": "A compact red panda in a neutral standing pose",
    "symmetry": "bilateral",
    "uncertainties": ["The far-side rear paw is partially hidden"]
  },
  "quality_contract": {
    "complexity": "moderate",
    "target_cuboids": [15, 35],
    "identity_features": ["striped tail", "white cheek patches"],
    "required_views": ["front", "back", "left", "right", "isometric"],
    "review_targets": ["silhouette", "face", "joints", "texture"]
  },
  "texture": {
    "density": 2,
    "palette_size": 24,
    "gutter": 2,
    "atlas_size": 128
  },
  "geometry": {
    "precision": 32
  },
  "materials": {},
  "bones": [],
  "cubes": [],
  "landmarks": [],
  "collision": {
    "width": 1.0,
    "height": 1.4,
    "eye_height": 1.15
  }
}
```

`geometry.precision` is optional and means coordinate subdivisions per model
unit. It controls exported cuboid bounds, while `texture.density` controls
texels per model unit. The compiler snaps shared bounds with geometry precision
before deriving UV sizes, so thin pieces remain nonzero without forcing a
larger atlas. Specifications that omit `geometry` retain legacy behavior and
use texture density for coordinate snapping.

## Bones

Each bone has a unique name, one parent, and a pivot.

```json
{"name": "head", "parent": "neck", "pivot": [0, 14, 7]}
```

Exactly one bone has `parent: null`. Keep articulated chains semantic:

```text
root → body → chest → neck → head
root → body → tail_base → tail_tip
body → thigh_left → shin_left → foot_left
```

## Cuboids

Every cube belongs to a bone and carries an anatomical role.

```json
{
  "name": "head",
  "bone": "head",
  "center": [0, 15, 7],
  "size": [6, 6, 6],
  "rotation": [0, 0, 0],
  "origin": [0, 14, 7],
  "role": "head",
  "material": "orange_fur",
  "faces": {
    "south": {"material": "cream_fur"},
    "east": {"flip_x": true}
  }
}
```

Valid faces are `north`, `east`, `south`, `west`, `up`, and `down`.

Use cuboids for volumes, appendages, horns, wings, and accessories. Do not use
geometry for flat paint.

## Materials and faces

Materials produce deterministic Minecraft-style pixel patches.

```json
{
  "orange_fur": {
    "base": "#b95f32",
    "shade": "#7d3526",
    "highlight": "#dd8a55",
    "pattern": "dither",
    "pattern_scale": 3
  }
}
```

Patterns are `solid`, `dither`, `stripes`, `spots`, and `gradient`.
`pattern_scale` is an integer from 1–16.

Face overrides can select another material and toggle UV direction:

```json
{"material": "cream_fur", "flip_x": true, "flip_y": false}
```

Photo-relief faces may select a normalized top-left-origin rectangle from a
material's embedded source texture without repeating the image data:

```json
{
  "material": "reference_photo",
  "source_region": [0.125, 0.25, 0.5, 0.75]
}
```

All values must be within `0..1`, with left less than right and top less than
bottom.

Photo depth-field specifications may also carry an audited `generation`
record. `generation.segmentation.input_mask` identifies the exact-resolution
foreground evidence and `generation.relief.depth_map` identifies an optional
grayscale thickness pass. A symmetric pass keeps every cube centered on `Z=0`
and increases cube depth at successive thresholds; this is suitable for
orthographic ray-hit evidence from a mesh. The compiler tolerates this metadata
but the reconstruction command, not hand editing, is responsible for keeping
its hashes and dimensions consistent.

An oriented photo-relief record additionally carries the measured image-space
principal-axis angle, inverse affine transforms, rectified frame dimensions,
coverage threshold, and final model Z rotation. All cuboids in this global
mode share the same origin and rotation, preserving adjacency after the frame
is rotated back. This is intentionally a single-axis contract; do not describe
independently branching parts as recovered anatomy.

A Route 1 ray-voxel specification carries auditable mesh metadata under
`generation.mesh`, including its relative path, SHA-256, format, geometry and
triangle counts, and watertight status. `generation.voxelization` records the
ray grid, six-direction hit evidence, resolved fill mode, and true
6-neighbor-component cleanup. `generation.source_mesh_overlap` records 3D
voxel precision/coverage, one-voxel-tolerant surface F1, orthographic
silhouette IoU, and bidirectional depth error. These fields are evidence, not
a schema-version change and not proof of semantic rigging.

Blockbench reverses the apparent direction of some side faces. Verify both
sides in rendered head close-ups and toggle `flip_x` when needed.

## Landmarks

Use landmarks for eyes, pupils, nostrils, mouth marks, stripes, and other
identity-defining texture pixels.

```json
{
  "name": "left_eye",
  "cube": "head",
  "face": "east",
  "center_uv": [0.62, 0.42],
  "size": [2, 2],
  "color": "#191514",
  "center_color": "#d9c878"
}
```

`center_uv` is normalized from 0–1 inside that face. Landmark sizes are atlas
pixels after texel-density calculation.

## Quality contract

Strict validation requires:

- non-empty identity features;
- declared required views and review targets;
- a cuboid count compatible with the target range;
- recorded uncertainty, even when the value is `"none identified"`;
- all material, bone, cube, landmark, and collision references to be valid.

The contract is a gate, not a visual score.

## Coordinate system

- `X`: left/right.
- `Y`: vertical.
- `Z`: back/front, with positive Z toward the face or nose.
- Ground: normally `Y = 0`.
- Rotations: Euler XYZ degrees.

For a segment between joints `a` and `b`, place the pivot at the parent joint,
center the cuboid between them, and overlap neighboring segments slightly.
