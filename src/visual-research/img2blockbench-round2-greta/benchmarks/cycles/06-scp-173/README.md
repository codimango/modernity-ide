# Cycle 6 — SCP-173

The supplied URL was labeled “SCP-174”, but the pictured legacy concrete
sculpture is SCP-173. This benchmark uses the correct asset name throughout.
The reference is kept local and excluded from distribution: the depicted
Izumi Kato artwork is not Creative Commons licensed.

This cycle adds Route 5, deterministic calibrated multi-view visual-hull
reconstruction. `from-views` accepts explicit orthographic-yaw calibration,
full-resolution masks, and an `observed` or `synthetic_proxy` evidence label
for every view. It intersects every silhouette on a common voxel grid,
retains six-connected components, greedily fits native cuboids, fuses colors
only from visible samples, and reports per-view silhouette fidelity. Input
order cannot affect the result.

The proof deliberately combines one observed front view with one authored
side proxy. Its all-view horizontal rank is two, while its observed-only rank
is one, so the evidence correctly records that hidden geometry was **not**
established from observations. The semantic deliverable is a separately
reviewed true volume: a deep oval head, pillar body, open leg split, connected
asymmetric arms, and a complete procedural painted face mapped flush across
the stepped head surface. The single decal is original pixel art; no source
pixels are projected into its texture and no facial plate projects from the
head.

Reproduce the cycle with the repository environment:

```bash
export PYTHONPATH=skill/img2blockbench/scripts
python benchmarks/cycles/06-scp-173/prepare-semantic-model.py
python benchmarks/cycles/06-scp-173/prepare-view-inputs.py
python skill/img2blockbench/scripts/img2blockbench.py from-views \
  benchmarks/cycles/06-scp-173/view-inputs/views.json \
  --id scp_173_visual_hull_proof \
  --description "SCP-173 calibrated front plus disclosed synthetic side proxy" \
  --subject-type character \
  --output benchmarks/cycles/06-scp-173/view-proof/model-spec.json \
  --evidence benchmarks/cycles/06-scp-173/view-proof/evidence.json \
  --build-output benchmarks/cycles/06-scp-173/view-proof/build \
  --resolution 40 --max-cuboids 72 --target-size 32 \
  --palette-size 16 --geometry-precision 64 --texture-density 2
python skill/img2blockbench/scripts/img2blockbench.py build \
  benchmarks/cycles/06-scp-173/model-spec.json \
  --output benchmarks/cycles/06-scp-173/build
python benchmarks/cycles/06-scp-173/render-evidence.py
```

The standard semantic evidence includes front, reference-angle, back, both
sides, top, isometric, face close-up, bilateral head close-ups, and a
connected-arm close-up. The front silhouette score is explicitly single-view
evidence; it is not used to claim unseen profile or back accuracy.
