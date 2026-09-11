# Cycle 5 — Tomato Devil

This cycle replaces one-off appendage placement with reusable connected
semantic chains. `semantic_geometry.py` aims a cuboid exactly between arbitrary
3D joints, fans profiles around a subject, and audits declared joints against
the actual oriented boxes rather than their permissive world-axis bounds. It
now also voxelizes ellipsoids/superellipsoids and greedily merges the exact
occupancy into a deterministic native-cuboid cover.

The benchmark model is fully native and volumetric: 192 purposeful cuboids,
68 semantic bones, a 1,416-voxel 14×16×12 ellipsoid merged into 61 exact
body cuboids, ten multi-cuboid eyes on visible stalks, a pinched five-tooth
mouth, six two-segment crown leaves, and eight long grounded arms with broad
palms and four fingers each. It contains no source-image panel or projected
photographic skin.

Reproduce from the repository root with the environment used by this study:

```bash
PYTHONPATH=skill/img2blockbench/scripts python benchmarks/cycles/05-tomato-devil/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/cycles/05-tomato-devil/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python benchmarks/cycles/05-tomato-devil/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python skill/img2blockbench/scripts/img2blockbench.py build benchmarks/cycles/05-tomato-devil/model-spec.json --output benchmarks/cycles/05-tomato-devil/build
```

The downloaded reference and copied build reference are intentionally ignored
because redistribution rights were not established. The deterministic native
model, atlas, geometry, audit, evidence renders, and metadata are retained.
