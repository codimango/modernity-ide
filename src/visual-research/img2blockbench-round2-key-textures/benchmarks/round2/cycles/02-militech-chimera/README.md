# Round 2, Cycle 02 — Militech Chimera

This benchmark reconstructs the Militech Chimera as a 174-cuboid native
semantic hexapod. The corrected anatomy has six separate mechanical legs in
front, middle, and rear bilateral pairs. Each leg has four connected links,
three visible hinges, a broad lower-leg shield with two raised armor layers, a
grounded pad, foot armor, and three toes.

The low, deep chassis is built from layered hull plates rather than a flat
reference projection. A 12-piece circular collar supports a wide 38-cuboid
faceted turret assembly with a sloped wedge front. The roof carries a flat
seven-piece radar pod and three antennae. Panel seams, bolts, front optics, and
status lights are authored texture landmarks.

The final atlas now uses calibrated visible-face texture baking at density 4
and 2048px. It embeds 30,225 unquantized source texels across 371 faces
(`8.7349%` of all face texels), selected from both fixed cameras only where the
face is frontmost and inside its reviewed foreground mask. Every other texel is
a flat material-base fallback, so unseen surfaces do not inherit random noise.
The olive photograph and white concept render depict different finishes; that
real source-color discontinuity can remain at face boundaries where their
view coverage meets. `texture-evidence.json` records every source hash, camera,
per-view selection count, and per-face coverage. No generic compiler or
geometry code was changed for this asset.

Two private references constrain the reconstruction: the original olive
photograph and a user-supplied white concept render that makes the six-leg
topology, rectangular shin armor, and broad turret silhouette clearer. Both
remain ignored because redistribution rights were not established. Far-side
articulation, underside equipment, and hidden surface markings are still
conservative symmetric inferences.

Evidence uses two manually frozen perspective cameras and raw source-frame
comparison. There is no runtime camera fitting, geometry deformation,
recentring, or visual-hull claim. The original view reports 0.605818 silhouette
IoU and 0.066869 subject-height mean keypoint error; the alternate view reports
0.632529 and 0.070894H. These are diagnostics, not acceptance gates: the two
references differ in staged pose, color, and view direction, and distorting the
model to clear the provisional 0.65 / 0.06H targets would make the reviewed
geometry less faithful. The prior four-leg grade is invalid; this rebuild is
passed independent visual review against both retained source views.

`render/comparison-sheet.png` retains both references in the general review
sheet. `render/alternate-comparison-sheet.png` places the user-supplied
reference beside the alternate fixed-camera render, top and isometric views,
and dedicated leg-shield and turret/radar closeups. The native depth and stance
audit records six unique roots, six grounded feet, 1.694929 chassis
depth-to-width, and all 191 declared attachments connected.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/02-militech-chimera/prepare-inputs.py
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/02-militech-chimera/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py bake-reference-textures benchmarks/round2/cycles/02-militech-chimera/model-spec.json --views benchmarks/round2/cycles/02-militech-chimera/texture-views.json --texture-density 4 --atlas-size 2048 --output benchmarks/round2/cycles/02-militech-chimera/model-spec.json --audit benchmarks/round2/cycles/02-militech-chimera/texture-evidence.json
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/02-militech-chimera/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/02-militech-chimera/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/02-militech-chimera/model-spec.json --output benchmarks/round2/cycles/02-militech-chimera/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_02_chimera -v
```

The downloaded references, copied build reference, ZIP, and source overlays
remain ignored because redistribution rights were not established. The
tracked manifest and evidence contain hashes, calibration, and coverage but no
redistributed source image pixels outside the generated model artifacts.
