# Round 2 Cycle 1 — Golden Apple

This cycle deliberately reuses the established ellipsoid and validated branch-graph
capabilities and adds one focused reusable extension: ellipsoid occupancy can now
subtract ellipsoidal negative-space volumes before greedy merging. The result is a
155-cuboid native model: a deep near-spherical apple, an actual viewer-left silhouette
recess, a carved top dimple and crooked stem, and four thick tapered gnarled roots
distributed across all four X/Z quadrants. Exactly 382 occupied voxels are removed;
there is no black proxy solid. Ten small dark overrides paint only exposed cut faces.

The reference PNG remains ignored because redistribution rights were not established.
Its bytes are checked against `benchmarks/round2/references.json` before generation.
The alpha silhouette touches the left, right, and bottom frame edges, so the measured
IoU cannot validate off-frame root continuation; that limitation is explicit in the
evidence report.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/01-golden-apple/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/01-golden-apple/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/01-golden-apple/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/01-golden-apple/model-spec.json --output benchmarks/round2/cycles/01-golden-apple/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_cycle01_golden_apple -v
```

The retained review set contains true front, back, left, right, top, and isometric
renders plus bite, stem, and root-joint closeups. Once the negative-space blocker was
resolved, the model cleared all requested quantitative gates and geometry tuning stopped.
