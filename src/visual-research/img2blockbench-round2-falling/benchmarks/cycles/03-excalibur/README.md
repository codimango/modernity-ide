# Cycle 03 — Excalibur semantic rebuild

The release gate rejected the original 96-cuboid single-view depth field: it
preserved the diagonal photograph but produced a stair-stepped slab, weak
inscription, and no credible reverse or hilt evidence. This rebuild is a
purpose-authored native sword with 30 cuboids and 19 bones.

The blade is modeled upright along `+Y` and uses four long overlapping masses,
two converging cutting-edge pieces, and a central tip spine. Its physical depth
is `0.028184` of the full sword length: clearly visible in profile without
turning the weapon into a board. The asymmetric gold quillons are connected
chains with separate navy inlays. Front and reverse faces have independent
authored rune and crest textures; neither uses a crop from the reference.

## Reproduce

The source is ignored by Git and must exist at
`benchmarks/references/03-excalibur.png` with the hash in `provenance.json`.

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 \
  benchmarks/cycles/03-excalibur/prepare-semantic-model.py

PYTHONPATH=skill/img2blockbench/scripts python3 \
  skill/img2blockbench/scripts/img2blockbench.py validate \
  benchmarks/cycles/03-excalibur/model-spec.json --strict

PYTHONPATH=skill/img2blockbench/scripts python3 \
  skill/img2blockbench/scripts/img2blockbench.py build \
  benchmarks/cycles/03-excalibur/model-spec.json \
  --output benchmarks/cycles/03-excalibur/build

PYTHONPATH=skill/img2blockbench/scripts python3 \
  benchmarks/cycles/03-excalibur/render-evidence.py

PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest \
  tests.test_cycle03_excalibur -v
```

Review `render/comparison-sheet.png`. It includes the source, a rolled
reference-angle render, native front/back/profile/top/isometric views, and
hilt/emblem closeups. The reviewed source-mask comparison scores `0.515895`
IoU with only `1.618621°` major-axis error. This intentionally strict metric
does not fit individual parts or hide Blockbench stylization.

The exact compiled-cuboid attachment audit covers all 30 cuboids across 31
declared links; every link is connected and the minimum margin is `0.005`.
Strict compilation reports no errors or warnings.

## Limits and rights

Only one presentation image is available. Reverse heraldry, blade bevel, and
profile thickness are coherent prop-design inference rather than observed
facts. The source is Type-Moon artwork linked through its community wiki; no
redistribution license was identified. The source copy and build bundle remain
local and ignored.
