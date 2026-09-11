# Cycle 01 — American goldfinch

This private benchmark now reconstructs the photographed bird as a native,
bilateral 3D Blockbench model. It contains no source-image skin or billboard.
The yellow breast and pale belly are rounded greedy cuboid volumes; the smaller
head carries a black breeding cap, paired eyes, and a tapered two-part bill.
Separate folded wings have white covert bars, the black tail tapers through a
connected chain, and both short legs end in three gripping toes with dark claws.

The final artifact has 98 semantic cuboids on 40 bones. Every one of the 33
declared wing, bill, tail, leg, and toe joints intersects both adjacent oriented
cuboids after compiler snapping. The source-angle body comparison is deliberately
clipped where the photograph clips the tail and occludes the feet: it measures
0.8094 silhouette IoU, 0.9220 recall, and 0.8689 precision with 1.28% aspect error.
This metric does not claim to validate hidden depth. Left/right head silhouettes
are exactly bilateral, while complete front, back, side, top, and isometric
renders provide the actual depth evidence.

## Reproduce

From the repository root, with the package and semantic-evidence dependencies
installed:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 \
  benchmarks/cycles/01-goldfinch/prepare-semantic-model.py

python3 skill/img2blockbench/scripts/img2blockbench.py validate \
  benchmarks/cycles/01-goldfinch/model-spec.json --strict

PYTHONPATH=skill/img2blockbench/scripts python3 \
  benchmarks/cycles/01-goldfinch/render-evidence.py

python3 skill/img2blockbench/scripts/img2blockbench.py build \
  benchmarks/cycles/01-goldfinch/model-spec.json \
  --output benchmarks/cycles/01-goldfinch/build
```

Inspect `render/comparison-sheet.png`; a clean structural audit alone is not a
visual approval. `render/evaluation.json` records the attachment, feature,
bilateral, and source-profile evidence and states the profile comparison's
scope explicitly.

## Rights and scope

The reference URL is National Geographic Kids imagery credited on the source
page to Brian E. Kushner/Shutterstock. Its SHA-256 is recorded in
`provenance.json`. The downloaded reference, model, and source-derived renders
are retained only for this local/private evaluation and are not offered for
redistribution. The downloaded reference and delivery ZIP/reference copy are
intentionally ignored by Git.

## Remaining uncertainty

Only one cropped side photograph was supplied. Far-side markings are mirrored
conservatively, and the complete tail and hidden-side depth are semantic
inference. Those inferred surfaces are reviewed in the orthographic evidence;
they are not described as observed source geometry.
