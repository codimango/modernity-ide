# Cycle 04 — Nian and executable mesh reconstruction

This cycle turns Route 1 into an executable textured-mesh pipeline while also
adding the cumulative Nian visual gate. The new `from-mesh` command loads all
transformed GLB/GLTF scene nodes, casts deterministic orthographic rays on
three axes (six directions), transfers UV/vertex/face/material colors, removes
noise with true 6-neighbor components, and adaptively partitions the retained
3D evidence into no more than 96 native Blockbench cuboids. NumPy and trimesh
remain lazy optional dependencies; the ray implementation does not need
`rtree`, SciPy, or Embree.

The Nian source page does **not** provide a usable GLB. It advertises a
non-commercial proprietary `.max` download (868 polygons / 647 vertices), so
this benchmark does not mislabel that asset as input to the generic mesh
route. An initial symmetric depth-field attempt failed blind review because it
read as stacked screen-depth walls. A later semantic-plus-skin attempt fixed
volume but still failed because the skin read as photographic panels. The
final correction is explicitly agent-authored: 79 cuboids are semantic
anatomy volumes and one 0.1-unit fur-matched surface decal carries a flush
pixel spiral. After later cumulative reviews still found the body too long,
the legs pillar-like, and one hind ankle visually detached, the anatomy was
rebuilt around a 16.5-unit rising trunk wedge, a 13.8-unit shoulder-to-rump
height step, two load-bearing bent forelimb chains, smaller connected crouched
hindquarters, a compressed fanged face, 22 mane/beard volumes, and paired
forward five-segment horn curls. There is no screen-aligned skin geometry.

## Reproduce Nian

The reference is intentionally ignored by Git. It must exist at
`benchmarks/references/04-nian.jpg` with SHA-256
`644faf9b0d58763d91daa70a6819c269451fa0e021852356556453758fc23d99`.

```bash
python3 benchmarks/cycles/04-nian/prepare-inputs.py
python3 benchmarks/cycles/04-nian/prepare-semantic-model.py
img2blockbench build benchmarks/cycles/04-nian/model-spec.json \
  --output benchmarks/cycles/04-nian/build
python3 benchmarks/cycles/04-nian/render-semantic-evidence.py
```

Inspect `render/comparison-sheet.png`, `reference_angle.png`, the true side
`profile.png`, both head closeups, `joint-closeup.png`, both rear-joint
closeups, and the red/green/blue silhouette overlaps. Uniform-scale/translation
comparisons—without nonuniform warping or mask-generated geometry—score
`0.753290` IoU, `0.849493` precision, and `0.869311` recall at the fixed source
angle. Strict profile IoU is `0.661169`. Opposite full-body renders score
`0.972976` mirrored silhouette IoU; the head closeups score `1.0`. Every
required chain has zero measured AABB gap, including `0.689163` units of near
rear ankle vertical overlap. The 80-cuboid, 32-bone native model has
width-to-length ratio `0.752396` and a zero-error audit.

The deterministic evidence renderer consumes compiler-snapped bounds and
compiler face-UV orientation. It produces front, back, left, right, top,
isometric, source-profile, bilateral head, and joint views with a textured
orthographic z-buffer. The earlier 65-cuboid candidate, first 79-cuboid
correction, and a later detached-hind-foot candidate all failed cumulative
review. Raised cream relief pieces then passed anatomy review but failed
material review because they read as plaques. The final v8 model removes those
pieces: a delivered-resolution cream C curl is embedded on the flush rump
decal and a tapered three-prong flame is embedded directly on the near foreleg
face. A separate strict reviewer gave the exact final sheet
(`36d07e366a345e70…`) scores of 4/5 for silhouette, proportions, identity, and
materials and 3/5 for topology and 3D coherence, with no visible detachment or
decal edge. No final cumulative pass is self-assigned here; the next
independent cumulative gate remains pending.

## Reproduce the generic mesh proof

The separate proof uses the already licensed-in repository chimpanzee fixture,
not the unavailable Nian `.max` file:

```bash
pip install -e '.[mesh-reconstruction]'
img2blockbench from-mesh examples/chimpanzee/lane2/source.glb \
  --id chimpanzee_ray_voxel \
  --description "Static ray-voxel reconstruction of the bundled textured chimpanzee source mesh" \
  --subject-type mob \
  --output benchmarks/cycles/04-nian/mesh-proof/model-spec.json \
  --evidence benchmarks/cycles/04-nian/mesh-proof/mesh-evidence.json \
  --build-output benchmarks/cycles/04-nian/mesh-proof/output \
  --resolution 28 --max-cuboids 72 --palette-size 16 \
  --fill-mode surface --surface-thickness 1 --min-component-voxels 2 \
  --provider Trellis --provider-model unrecorded --source-license unrecorded \
  --canonical-transform 40 0 0 0 0 37 0 12.55 0 0 -27 -3.5 0 0 0 1

img2blockbench-overlap \
  --source examples/chimpanzee/lane2/source.glb \
  --spec benchmarks/cycles/04-nian/mesh-proof/overlap-transform.json \
  --bbmodel benchmarks/cycles/04-nian/mesh-proof/output/chimpanzee_ray_voxel.bbmodel \
  --json benchmarks/cycles/04-nian/mesh-proof/triangle-overlap.json \
  --sheet benchmarks/cycles/04-nian/mesh-proof/triangle-overlap.png \
  --resolution 384
```

The source mesh is open/non-watertight, so the command conservatively retains
its surface rather than inventing parity-filled interior. All 1,946 retained
voxels are covered, one-voxel-tolerant surface F1 is `0.935582`, and internal
orthographic mean silhouette IoU is `0.956008`. The independent triangle
raster audit—including isometric view—measures `0.8191` mean IoU and `0.9992`
source coverage. The compiler produces 72 cuboids and a zero-error native
audit.

## Cumulative regression and limits

Fresh rebuilds with the Cycle 3 baseline code and this branch match
byte-for-byte for every generated build and render file in Cycles 1–3. The
checked-in prior-cycle trees are untouched. Exact selected hashes and the
comparison method are in `regression.json`.

The Nian's unseen markings are conservative palette-matched inferences, and its
angular horns and stepped mane remain Minecraft abstractions. The generic mesh
output is static and uses one nonsemantic root bone; animation still requires
an anatomy pass. Voxel/cuboid overlap and semantic-profile alignment are
objective evidence, not substitutes for multi-view visual review.
