# Round 2, Cycle 04 — False Apple

This cycle reconstructs the False Apple as a 189-cuboid native semantic model.
It is a low, asymmetric root creature rather than a humanoid: a carved domed
skull and deep lower jaw occupy the viewer-left end, a thick arched trunk carries
the body across the frame, and a deep red apple lure grows from a fleshy central
junction. Twelve irregular teeth line two gum rails. Four root limbs include a
large foreground hand and a tall rear arch, with two roots in a near Z layer and
two in a far Z layer.

The maw is genuine negative space. Ellipsoid CSG removes 78 skull voxels before
greedy native-cuboid merging, and dark material is assigned only to exposed cut
faces; there is no black proxy solid. The apple is a separate 32-cuboid ellipsoid
with 24 units of depth over 32 units of width, a top dimple, a torn lower notch,
three flesh drips, and a connected crooked stem. Every one of the model's 188
declared links passes the compiler-snapped oriented-cuboid contact audit.

The first recognizable volumetric render passed the requested gates, so geometry
tuning stopped there: alpha IoU is 0.638953, mean keypoint error is 0.029835
subject-heights, apple depth/width is 0.75, head/maw depth/height is 0.583333, and
the measured near/far root-layer center separation is 28.734837 model units.
`render/evaluation.json` records explicit selected-cuboid world bounds for each
part; no new reusable depth API was necessary.

Only one flattened illustration is observed. Rear surfaces and exact limb order
are therefore conservative inferences, not recovered geometry. The alpha mask
touches the left, right, top, and bottom edges, so silhouette IoU cannot establish
how any clipped root or stem continues outside the frame. The source is never
projected onto geometry.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/04-false-apple/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/04-false-apple/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/04-false-apple/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/04-false-apple/model-spec.json --output benchmarks/round2/cycles/04-false-apple/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_04_false_apple -v
```

The retained review set contains true front, back, left, right, top, and isometric
renders plus maw, apple, near-root, and far-root closeups. The private source,
copied build reference, and ZIP remain ignored because redistribution rights were
not established.
