---
name: img2blockbench
description: Reconstruct a Minecraft-style creature, character, prop, or vehicle concept as a native Blockbench model using an optional provider-selected 3D mesh, agent vision, and deterministic compilation. Use when Codex should turn PNG, JPEG, or WebP artwork, optionally accompanied by a textured GLB or GLTF from any image-to-3D generator, into an anatomy-driven `.bbmodel`, pixel texture atlas, Bedrock `geo.json`, bones, pivots, collision metadata, and audit bundle.
---

# img2blockbench

Build Minecraft geometry from a reference image, optionally using a
provider-selected source mesh as measured shape and texture evidence. Treat the
agent as the 3D reasoner and the bundled compiler as the file-format authority.

## Route selection

- Prefer Route 1 when a source mesh is supplied or organic depth is ambiguous.
  Accept a textured GLB or GLTF from any generator; do not require Trellis.
- Prefer Route 2 when the image already has clear Minecraft-native cuboid
  anatomy and no source mesh is needed.
- Use Route 3 only for an official img2threejs procedural scene.
- Prefer Route 5 when two or more silhouette masks have explicit orthographic
  yaw calibration, or when a clip has caller-supplied frame timestamps and
  azimuths. Never infer camera motion in this deterministic route.
- Use Route 4 for a photograph, painting, or arbitrary image when a faithful
  source-facing native relief is useful and no source mesh is available.

For Route 1, record the generator name, model/version, source hash, and
applicable license in provenance. The generator is user-selected and remains
outside the deterministic compiler.

## Required references

- Read [references/model-spec.md](references/model-spec.md) before authoring or
  correcting a model specification.
- Read [references/quality-rubric.md](references/quality-rubric.md) before
  approving geometry, textures, rigging, or final output.

## Workflow

1. Resolve the repository root containing `pyproject.toml`. Install it once with
   `pip install -e '.[all]'` when the `img2blockbench` command is unavailable.
   The full workflow uses NumPy for multiview and mandatory seven-angle review,
   while mesh reconstruction additionally uses trimesh.
2. Run `img2blockbench probe IMAGE --output WORKSPACE/reference.json`.
3. Inspect the image directly. For Routes 1–3, require Minecraft-native cuboid
   forms, crisp square-pixel materials, a full-body neutral pose, and separated
   appendages. For a photo or smooth illustration without a mesh, choose Route
   4 and explicitly record that hidden-side depth remains uncertain. Record
   subject type, pose, proportions, palette, identity features, hidden-side
   uncertainty, and intended runtime.
   For a named production asset or mechanically ambiguous subject, search
   official galleries, artist turnarounds, and gameplay/video before deciding
   its topology. Record exact URLs, source roles, and useful video timestamps
   in `research-sources.json`. If a missing view changes limb count, wearer
   relationships, or attachment topology, request another perspective instead
   of guessing.
4. Run `img2blockbench new IMAGE --id MODEL_ID --output WORKSPACE/model-spec.json`.
5. Replace the starter body with an anatomy-driven model specification. Prefer
   15–35 cuboids for a medium mob. Use fewer only when the subject is genuinely
   simple.
6. Run `img2blockbench validate WORKSPACE/model-spec.json --strict`.
7. Run `img2blockbench preview-threejs WORKSPACE/model-spec.json --output
   WORKSPACE/createModel.ts`. Render the procedural group beside the reference
   and correct silhouette, proportions, attachments, and identity features.
   This is a Route 2 preview generated from the cuboid spec, not a
   Three.js-first Route 3 source.
8. When faithful reference materials are requested and fixed cameras plus
   masks are available, run `img2blockbench bake-reference-textures` with a
   calibrated view manifest. Inspect its observed/fallback coverage and never
   describe fallback texels as recovered source detail.
   Prefer its `minecraft` style: one texel per model unit, a bounded shared
   source palette, small per-material ramps, and no dithering. Use literal
   `source` style only when the user explicitly wants photographic projection.
   Use solid material color on unobserved faces; do not add random dither as a
   generic realism, grime, or weathering pass.
9. Run `img2blockbench review WORKSPACE/model-spec.json --output
   WORKSPACE/review` and inspect its model-only front, back, left, right, top,
   bottom, and isometric evidence. Hashes prove reproducibility, not likeness.
10. Open the emitted `.bbmodel` in Blockbench when available and capture any
    identity close-ups or animation evidence the generic review cannot show.
11. Correct the specification and re-render until the quality rubric passes.
    Then run `img2blockbench build WORKSPACE/model-spec.json --output
    WORKSPACE/build --review-manifest WORKSPACE/review/model-review.json`.
    Add `--reference-policy external` when the standalone source image must not
    be bundled. This does not strip source pixels deliberately transferred into
    textures. Do not patch generated `.bbmodel` JSON by hand.
12. Deliver the bundle ZIP and its individual `.bbmodel`, PNG, `geo.json`,
    audit, review, and manifest files.

For Route 5, run `img2blockbench from-views MANIFEST` with at least two
non-parallel yaw axes. Inspect every source/model silhouette comparison and
the isometric output. Treat the result as a silhouette visual hull: do not
claim hidden concavities, unseen texture, top/bottom detail, anatomy, or
articulation from yaw masks alone. Label every view `observed` or
`synthetic_proxy`; proxy views may constrain the output but do not establish
hidden geometry as observed evidence.

For Route 1, replace steps 2–8 with:

```bash
pip install -e '.[mesh-reconstruction]'
img2blockbench from-mesh SOURCE.glb --reference IMAGE \
  --id MODEL_ID --description DESCRIPTION --subject-type TYPE \
  --output WORKSPACE/model-spec.json \
  --evidence WORKSPACE/mesh-evidence.json \
  --build-output WORKSPACE/build \
  --reference-policy external
```

Supply `--canonical-transform` when the source is not already Y-up, centered,
and facing positive Z. Preserve the provider, model/version, license, mesh
hash, and transform in provenance. The command casts orthographic rays on all
three axes (six directions), cleans surface evidence with true 6-neighbor
components, transfers UV/vertex/material color, and adaptively fits at most 96
native cuboids. It fails instead of dropping a retained component when that
minimum representation exceeds the cuboid budget. Inspect the evidence's
retained components, tolerant surface F1, per-axis thickness profiles,
source-relative anti-pancake gate, per-axis model precision/depth inflation,
one-to-one fitted connectivity, per-view silhouette IoU, and bidirectional
depth error. Then inspect every hashed artifact in the generated front, back,
left, right, top, bottom, and isometric review manifest. A subsequent build
must package those verified artifacts and localize the delivered spec's review
paths. The generated one-bone mesh is a static reconstruction, not a semantic
animation rig.

For Route 4, replace steps 4–8 with:

```bash
img2blockbench from-image IMAGE --id MODEL_ID --description DESCRIPTION \
  --subject-type TYPE --output WORKSPACE/model-spec.json \
  --diagnostics WORKSPACE/segmentation
img2blockbench build WORKSPACE/model-spec.json --output WORKSPACE/build
img2blockbench render-relief WORKSPACE/model-spec.json \
  --output WORKSPACE/render
```

Inspect the foreground mask and both rendered views. Tune the cuboid budget or
background mode when the mask drops identity-defining features. A clean audit
or high source-facing texture score does not establish hidden-view fidelity.
For a complex opaque background, prefer an exact-resolution external mask via
`--foreground-mask`; `--subject-bbox LEFT TOP RIGHT BOTTOM` clips that mask or
limits automatic segmentation to an ROI. For a hard-surface object or a mesh
ray-hit pass, add an exact-resolution grayscale `--depth-map`, `--depth-mode
symmetric`, and `--decomposition adaptive`. Preserve those evidence files and
their generated hashes. Never approve a small high-PSNR fragment: compare mask
coverage and the complete subject silhouette too.

For one long diagonal subject, use `--decomposition oriented`. The compiler
rectifies the complete reviewed mask to its global PCA axis, retains cells at
or above `--mask-coverage`, decomposes in that frame, and rotates the native
cuboids back around one shared pivot. Inspect endpoint retention and the
perpendicular features; global PCA is not a substitute for semantic part
orientation on a branching subject. Use `--geometry-precision` when small
coordinate increments are needed and tune `--texture-density` independently.
The former controls geometry subdivisions per unit; the latter controls only
atlas texels per unit. Omitted geometry precision preserves legacy snapping.

## Modeling rules

- Use one rotated cuboid per anatomical segment whenever possible.
- Keep paired anatomy symmetric unless the image clearly requires asymmetry.
- Put pivots at shared joints. Overlap adjacent segments slightly.
- Use texture pixels for eyes, nostrils, markings, seams, and flat details.
- Never split geometry because a color changes.
- Never build dense voxel soup. Route 1 may use a bounded ray-voxel
  intermediate only when it is adaptively decomposed to at most 96 cuboids and
  retains objective source-mesh overlap evidence.
- Keep one texel density across the model.
- Infer unseen surfaces conservatively. Request another view when identity
  depends on hidden geometry.
- For a wearable exoskeleton, keep the reference pilot in a removable occupant
  bone subtree and declare the `wearable` contract. Inspect both the occupied
  source-comparison model and the generated shell-only player-fit variant.
- Treat static-model and animation approval as separate decisions.
- For one-sided photo reliefs, keep projected front faces coplanar. For a
  symmetric depth field, project each visible depth shell and mirror thickness
  around the center plane. Share one source texture through normalized face
  regions and disclose the single-view limit in either case.
- For oriented photo reliefs, retain one shared rotation and pivot across the
  rectified cuboids so local adjacency survives. Require a profile render,
  silhouette IoU/recall, and a seam-free isometric review in addition to PSNR.
- For mesh reconstruction, preserve every meaningful 6-connected component;
  do not let cleanup discard a detached horn, wheel, weapon, or accessory.
  Treat low tolerant surface F1, high depth error, or a color-transfer source
  other than UV/vertex/material evidence as a review failure.

## Direct Route 2 boundary

Do not call Meshy, Modly, Trellis, Tripo, Hunyuan, or another image-to-mesh
provider in this route. If a textured GLB or GLTF is intentionally supplied,
use Route 1 instead.

## Compiler boundary

The compiler validates and deterministically emits model files. It does not
invent anatomy or judge resemblance. The agent must author the bones, cuboids,
materials, face overrides, landmarks, uncertainties, and review targets.

Never claim success from a clean audit alone. Inspect real renders.
