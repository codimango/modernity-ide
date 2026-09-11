# Round 2, Cycle 03 — Greta

This benchmark reconstructs Greta as a 72-cuboid native Blockbench model. The
result is a deep, asymmetric humanoid rig rather than a textured image plane:
a broad suit and grounded legs carry a yawed tapered shark head, chef hat,
dorsal fin, articulated rear tail, forked caudal fin, and a held butcher axe.

Greta's identity contract is deliberately exact. There are four—and only
four—toothed mouth assemblies: the main jaw, the right hand, one pendant tail
lobe, and the main tail. Each has its own cavity cuboid and two texture-atlas
tooth rows. The red eye, blue shoulder tattoo, shirt, tie, and buttons are
texture landmarks; the anatomy, tail, fin, hands, and axe are real volumes.
The snout, arms, legs, dorsal fin, and six-edge tail graph use reusable semantic
chain/branch helpers and remain separately boned for editing and animation.

The source is one transparent illustration. Its alpha does not touch the image
frame, so the 0.684950 height-normalized alpha IoU is a real complete-silhouette
gate rather than a clipped-frame proxy. Ten named landmarks have 0.029263 mean
error in subject-height units. Canonical views verify the hidden dimension:
torso depth/body width is 0.660870 and head depth/body width is 0.592076. Rear
surface treatment and the tail root hidden behind the legs remain conservative
single-view inference.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/03-greta/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/03-greta/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/03-greta/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/03-greta/model-spec.json --output benchmarks/round2/cycles/03-greta/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_03_greta -v
```

The user-supplied reference and generated ZIP remain ignored because reference
redistribution rights were not established.
