# Round 3 — Holistic 3D reconstruction

Round 3 targets the pancake failure mode: a model may resemble one source
frame while collapsing or becoming uninformative from the side, rear, or top.
Passing now requires evidence across the whole volume rather than a strong
front render alone.

## Benchmarks

1. Biblically accurate angel — single-image semantic reconstruction with a
   many-eyed central body, layered wings, and explicitly inferred rear depth.
2. Zetatech Atlus — multi-view semantic reconstruction using the supplied
   Trauma Team image plus public front, front-quarter, side, rear, and top
   reference views.
3. Minecraft-style off-road truck — provider-neutral GLB ray reconstruction.
4. Meshy Minecraft hovercraft — provider-neutral GLB ray reconstruction.

The private inputs live in ignored `round3-inputs/`. Their hashes and source
metadata belong in each cycle's committed input contract; the source media do
not.

## Holistic gate

- Mesh inputs are sampled by bidirectional rays on all three axes, preserving
  six-connected components and mesh color evidence.
- The source mesh and fitted cuboids are rendered from front, back, left,
  right, top, bottom, and at least one oblique view.
- Per-axis silhouette overlap and bidirectional depth error compare the fitted
  volume to the source volume. Anti-pancake thresholds are relative to the
  source mesh, so legitimately thin subjects are not rejected.
- Image-only reconstructions declare which depth is observed and which is an
  agentic prior. Their required side, rear, top, and isometric renders must
  expose meaningful component separation and physical attachment depth.
- A clean structural audit is necessary but not sufficient. A separate
  read-only grader must inspect all required views before an asset passes.

The output remains Minecraft-native: semantic cuboids, bounded palettes,
nearest-neighbor textures, no random noise, and no literal photographic skin.
