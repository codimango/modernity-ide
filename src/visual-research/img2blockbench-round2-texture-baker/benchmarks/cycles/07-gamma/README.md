# Cycle 7 — Gamma

This cycle adds a reusable atomic branching-geometry builder. Named nodes and
edges compile into a piecewise-cuboid approximation of tapered connected
segments with parented bones and a canonical attachment manifest. It supports branch-from-joint topology and
rejects cycles, duplicate nodes or edges, compiler-invalid generated names,
degenerate/non-finite geometry, multiple parents, and disconnected nodes before
mutating the builder.

The benchmark is a genuine 111-cuboid semantic volume rather than a projected
source panel. It has a deep flared robe, a forward-mounted off-center white
mask, split cranium, vertical chest maw, exactly eight hooked upper mandibles
across three depth layers, two unequal forward silver rings, and exactly four
hinged mechanical leg chains across two depth layers. The upper fan is modeled
as mouth anatomy, and the lower struts are modeled as weight-bearing legs.

Evidence uses the reference PNG's alpha channel, preserves aspect ratio while
normalizing silhouette height, and measures six named semantic keypoints. The
reference touches every frame edge, so the recorded IoU cannot establish
off-frame appendage continuation; that limitation is retained in the report.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python benchmarks/cycles/07-gamma/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/cycles/07-gamma/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python benchmarks/cycles/07-gamma/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python skill/img2blockbench/scripts/img2blockbench.py build benchmarks/cycles/07-gamma/model-spec.json --output benchmarks/cycles/07-gamma/build
```

The downloaded reference and copied build reference are intentionally ignored
because redistribution rights were not established. The native model, atlas,
geometry, audit, evidence renders, and metadata are retained.
