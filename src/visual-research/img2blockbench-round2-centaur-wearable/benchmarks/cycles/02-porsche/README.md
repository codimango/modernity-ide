# Cycle 02 — Porsche 911 Turbo (930)

This correction replaces the original symmetric depth-field relief with a
complete native Blockbench vehicle. The deliverable has 97 purposeful cuboids
on 13 semantic bones: overlapping front/middle/rear body masses, a deep closed
underbody, four separate seven-cuboid wheel assemblies, three-part wheel
arches, a low stepped roof with strongly raked glass, mirrors, alpha-masked
round headlamps, rear lamps, bumpers, wide Turbo haunches, and a thin connected
whale-tail spoiler.

The red-white side graphic is a tiny deterministic authored pixel texture. It
does not copy source pixels. There are no source-region projections or
source-skin panels anywhere in the model. Unseen surfaces are conservative
single-view Porsche 930 priors and are disclosed in the specification.

## Reproduce

The copyrighted benchmark reference remains ignored and must exist at
`benchmarks/references/02-porsche-911.png`.

```bash
export PYTHONPATH=skill/img2blockbench/scripts
python benchmarks/cycles/02-porsche/prepare-semantic-model.py
python skill/img2blockbench/scripts/img2blockbench.py validate \
  benchmarks/cycles/02-porsche/model-spec.json --strict
python skill/img2blockbench/scripts/img2blockbench.py build \
  benchmarks/cycles/02-porsche/model-spec.json \
  --output benchmarks/cycles/02-porsche/build
python benchmarks/cycles/02-porsche/render-evidence.py
```

Inspect `render/comparison-sheet.png`. It includes the observed reference,
one fixed low three-quarter render, true front and rear, both sides, top,
isometric, and close-ups of the wheel assembly, greenhouse/livery, and front
lamps. The fixed source-angle silhouette IoU is 0.710780. That metric evaluates
only the observed outline; the orthographic views are required to judge the
inferred volume.

All 16 declared axle/wheel and rear-deck/spoiler connections pass compiled
oriented-cuboid containment. Four wheel ground heights agree within 0.009 model
units. Two complete generator/build/render runs produced byte-identical model
specification, `.bbmodel`, texture atlas, and comparison sheet.

## Rights and scope

The reference is a Cyberpunk 2077 vehicle render retrieved from the linked
Cyberpunk Wiki asset. No redistribution license was identified. The downloaded
reference and generated bundle copy remain ignored and local.

## Known limits

Only one low three-quarter view was observed. The opposite-side paint,
underbody, exact wheel depth, canonical front/rear surfaces, and roof curvature
are inferred rather than measured. Cuboids intentionally give the result a
Minecraft-native stepped finish rather than pretending to recover smooth CAD
surfaces.
