# Round 3 Cycle 01 — Biblically Accurate Angel

This cycle turns the supplied frontal painterly angel into a native Minecraft/Blockbench
asset while directly targeting the pancake failure. The accepted revision has a stepped,
deep central shell; 21 geometric eyes distributed across front, rear, sides, top, and wings;
three bilateral wing pairs; 18 three-stage primary feathers; and 12 three-stage broad overlap
vanes. Every distal assembly narrows twice into a small terminal cap instead of ending as a
large square slab. Rear and side anatomy is explicitly inferred because the benchmark provides only one
observed view.

The ignored source is identified by hash in `provenance.json`; no source pixels are projected
into the texture atlas. All authored materials use deterministic solid Minecraft swatches.
The unrelated YouTube thumbnail listed in provenance was contextual inspiration only and was
not treated as a calibrated second camera or an identity match.

## Rebuild

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/01-biblical-angel/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 -m img2blockbench validate benchmarks/round3/cycles/01-biblical-angel/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/01-biblical-angel/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 -m img2blockbench preview-threejs benchmarks/round3/cycles/01-biblical-angel/model-spec.json --output benchmarks/round3/cycles/01-biblical-angel/createModel.ts
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/01-biblical-angel/build-release.py
```

`build-release.py` invokes the normal deterministic compiler, removes its private reference
copy, marks that source as `private-optional` and unbundled in both metadata files, keeps the
compiled spec pointed at the ignored local source for reproducible local validation, re-hashes
the retained artifacts, and rebuilds a source-free ZIP. The `.bbmodel`, `.geo.json`,
atlas PNG, audit, manifest, and compiled model specification are therefore self-consistent
shareable native deliverables without committing private pixels.

## Holistic gates

- full depth/width: `0.474180` (minimum `0.40`)
- central body depth/width: `0.955629` (minimum `0.85`)
- wing-layer depth span: `30.0` units (minimum `30.0`)
- rear/middle/front-lower sector sweeps: `42.709° / 21.038° / 40.101°`
- nonzero Y yaw: `108 / 108` wing-shape cuboids
- side/front silhouette area: `0.673758` on both sides (minimum `0.60`)
- side/front silhouette width: `0.547170` on both sides (minimum `0.50`)
- back/front, top/front, and bottom/front silhouette area:
  `0.981761 / 0.750201 / 0.750201`
- distal taper profiles: `30`, all three-stage with maximum `1.4 × 1.0` caps;
  terminal lengths are staggered across 15 values and capped at `5.933271`
- wrapped crown: eight structural segments including four angled corners and two side temples
- front, middle, and rear depth occupancy: at least 20 cuboids in every band
- all seven axis/isometric renders are pixel-distinct, including bottom
- every one of the 14 required model-only renders has a recomputed SHA-256 in
  `render/render-hashes.json`
- every one of the 188 structural links is physically connected

The committed `render/all-angle-sheet.png` contains model-only evidence. The comparison that
includes the private source lives only under the ignored
`round3-inputs/local-review/01-biblical-angel/` directory. Structural metrics are safeguards,
not a substitute for the recorded visual review.
