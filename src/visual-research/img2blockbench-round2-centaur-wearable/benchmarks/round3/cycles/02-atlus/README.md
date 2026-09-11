# Round 3, Cycle 02 — Zetatech Atlus

This cycle reconstructs the white, teal, and red Trauma Team Atlus as a
165-cuboid native Blockbench vehicle. It is constrained by the user screenshot
plus independent front-quarter, front, side, rear, and top references. The
model therefore has authored geometry on every visible exterior axis rather
than a detailed front face extruded into a thin side.

The long central fuselage, paired full-depth teal hover nacelles, broad rescue
doors, front louver bank, two clustered four-barrel nose weapons, rear drive
machinery and layered pod exhausts, four ventral support/hover modules, roof
ports, emergency light rails, and three aerials are separate semantic
assemblies. Twenty-eight texture landmarks supply bilateral, roof, and rear
medical markings and bounded vent pixels. All materials are solid Minecraft
panel colors; there is no procedural noise, dithering, or source-photo collage.

`render/evaluation.json` records three-axis extents of `37.483459 × 24.745358 ×
61.5625`, a central-hull length/width ratio above `2.5`, side-pod coverage of
more than `72%` of total length, four zero-height support contacts, and distinct
front/back and top/underside views. All 46 declared connections are audited in
compiled oriented-cuboid space. The central hidden underside remains a clearly
disclosed conservative inference; the five references establish the exterior
but do not expose every internal vent or suspension surface.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/02-atlus/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round3/cycles/02-atlus/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/02-atlus/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/02-atlus/build-release.py
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round3_02_atlus -v
```

The ignored references remain local because redistribution rights were not
established. Source-containing sheets are generated only under ignored
`round3-inputs/local-review/02-atlus/`; the committed `render/all-angle-sheet.png`
contains model pixels only. Neither source sheet is a calibrated-camera or
visual-hull claim. Each of the five observed directions has a hash-bound
silhouette or key-proportion gate in the evaluation report, while every required
model-only render has a committed SHA-256 map that the focused test recomputes.

`build-release.py` invokes the deterministic compiler, deletes its temporary
private reference copy, marks that source `private-optional` and unbundled in
both delivery metadata files, re-hashes every retained artifact, and rebuilds a
source-free deterministic ZIP. The `.bbmodel`, Bedrock geometry, atlas, audit,
manifest, and compiled specification therefore remain portable on a clean
checkout without dangling manifest entries.
