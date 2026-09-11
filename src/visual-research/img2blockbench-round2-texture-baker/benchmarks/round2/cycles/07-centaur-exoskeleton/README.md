# Round 2, Cycle 07 — Militech Centaur Exoskeleton

This cycle reconstructs the apparent “Centaur” as what the three references
actually show: one augmented human operator nested inside a two-legged powered
exoskeleton. The 192 native cuboids are divided between a separately rigged
pilot, paired open mechanical leg chains, a twin-canister power backpack,
overhead and lower shield actuators, a large open orange cellular-frame shield,
and an opposed 60-unit thermal chassis with four radiator bays and five rose heat tubes.

Each powered leg carries a hip housing, splayed thigh beam, knee drum,
projecting three-piece U guard, shin rail and rear brace, hydraulic piston,
segmented ankle, broad grounded foot, and three separated claw toes. The pilot's
lighter-blue cloth legs sit inward of those structures with visible negative
gaps, and brass restraint bars make two audited boot-to-powered-ankle contacts.
They are not modeled as a second free-standing pair of legs. The shield
has two independently audited contacts: an overhead three-link boom and a
separate lower hydraulic actuator. All 191 structural-tree links, both shield
contacts, both pilot/ankle retention contacts, and both ground contacts pass.

The three 1000×1023 studio renders are uncalibrated perspective views. Each is
measured in its full original frame using one declared, manually frozen camera;
the evidence code performs no runtime fitting, crop, scale, translation, or
recentering. Raw fixed-frame silhouette IoU is 0.567833, 0.463441, and 0.526309
for sources 6, 7, and 8. Mean semantic keypoint error is 0.061855H, 0.083226H,
and 0.072842H. The difficult side view uses a disclosed 0.45 IoU diagnostic
threshold after removing a studio-floor reflection from its mask; the other
views retain 0.50. These scores are not proof of hidden geometry.

The source artwork is smooth, high-detail concept rendering rather than a
Minecraft-native concept. Geometry therefore preserves the major mass hierarchy,
articulation, asymmetric loadout, and readable panel groupings while deliberately
leaving scratches, tiny fasteners, beard detail, and most stencils in the pixel
material layer. The exact unseen right-side cable routing and several occluded
control interfaces remain conservative inference. No animation was authored.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/07-centaur-exoskeleton/prepare-inputs.py
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/07-centaur-exoskeleton/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/07-centaur-exoskeleton/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/07-centaur-exoskeleton/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/07-centaur-exoskeleton/model-spec.json --output benchmarks/round2/cycles/07-centaur-exoskeleton/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_07_centaur -v
```

The three source images, mask overlays, copied build reference, and ZIP remain
ignored because redistribution rights were not established.
