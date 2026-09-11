# Round 2, Cycle 06 — Falling Devil

This cycle reconstructs the Falling Devil as a 78-cuboid native Blockbench
character. The asset preserves the source's headless chef-body composition,
tall fluted toque, white double-breasted jacket, deep blue-black apron, and all
six visible arm pairs. Those twelve arms are independent three-segment chains:
two bare pairs support the detached head, one bare pair sits behind the chest,
two black-sleeved pairs overlap in front, and one bare pair passes behind the
lower body. The four head-support hands make four audited physical contacts.

The peach form crossing the apron is explicitly an independent six-segment
waist tendril, not a seventh arm. Six named arm layers span 16.966112 model
units in Z, with a minimum pair-center separation of 1.930865. The selected
torso volumes have depth/width 0.564583, and side, top, and isometric renders
show that the character is not a frontal relief. Every one of the model's 77
structural links passes the compiler-snapped oriented-cuboid contact audit.

The retained source-camera render uses one recorded perspective camera and raw
399x501 pixel coordinates: it does not crop, scale, translate, or recenter
either silhouette during scoring. It reaches 0.700233 IoU and 0.018635 mean
keypoint error in source-subject heights. The source mask touches the bottom
edge, so neither this score nor the model claims to recover the cropped shoes.

Only one frontal illustration is observed. Rear materials and the exact hidden
ordering of several overlapping arm roots are conservative semantic inference,
not reconstructed facts. The source is never projected onto geometry, and its
redistribution rights are unknown, so the private reference and copied build
reference remain ignored.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/06-falling-devil/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/06-falling-devil/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/06-falling-devil/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/06-falling-devil/model-spec.json --output benchmarks/round2/cycles/06-falling-devil/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_06_falling_devil -v
```

The review set contains front, back, left, right, top, isometric, fixed source
camera, head-support, arm-layer, tendril, and body-depth renders, plus a raw
fixed-frame silhouette overlay and comparison sheet.
