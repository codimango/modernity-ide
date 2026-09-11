# Round 2, Cycle 07 — Militech Centaur Exoskeleton

This cycle reconstructs the Militech Centaur as what the references and
gameplay footage actually show: a wearable, open-frame powered exoskeleton—not
an autonomous robot. The 192-cuboid source-comparison model keeps one augmented
operator in a removable seven-bone subtree. A normal build also emits a
168-cuboid, 21-bone shell with that proxy completely removed and the remaining
machine scaled around a canonical Minecraft player.

The interpretation was checked against the official-style front/right/left/back
gallery renders, Ben Andrews' occupied/empty concept sheet, Ovidiu Voica's
final render, and gameplay footage at 1:23, 1:27, and 2:08. Exact URLs, local
hashes, and timestamps are recorded in `research-sources.json`. Those views
establish the waist controls, player boot stirrups, powered hip/knee/ankle
assemblies, shoulder arches, external spine power unit, left ballistic shield,
and right thermal weapon.

Each powered leg carries a massive hip housing, broad armored thigh beam,
ten-unit knee core with a projecting three-piece U guard, deep shin armor and
rear brace, hydraulic piston, heavy segmented ankle, broad grounded foot, and
three separated claw toes. Minimum cross-sections for both powered chains are
audited in `render/evaluation.json`; this prevents the weapon and shield mass
from visually reducing the lower chassis to spindly rails. The pilot's
lighter-blue cloth legs sit inward of those structures with visible negative
gaps, and brass restraint bars make two audited boot-to-powered-ankle contacts.
They are not modeled as a second free-standing pair of legs. The shield
has two independently audited contacts: an overhead three-link boom and a
separate lower hydraulic actuator. All 191 structural-tree links, both shield
contacts, both pilot/ankle retention contacts, and both ground contacts pass.

The wearable contract maps the authored player anchor to `[0, 0, 0]`, resolves
the authored wearer to 34 units against the canonical 32-unit classic player,
and exposes six transformed interfaces: waist harness, back harness, two hand
controls, and two boot stirrups. The build includes shell-only `.bbmodel`,
`.geo.json`, `.png`, `.model-spec.json`, `.audit.json`, and Bedrock
`.attachable.json` files. The fit renders use a visibly separate classic-player
proxy; that proxy is not present in the wearable artifacts. Runtime locomotion
animation and item registration remain integration work for the consuming mod.

The three 1000×1023 studio renders are uncalibrated perspective views. Each is
measured in its full original frame using one declared, manually frozen camera;
the evidence code performs no runtime fitting, crop, scale, translation, or
recentering. Raw fixed-frame silhouette IoU is 0.603863, 0.475590, and 0.542573
for sources 6, 7, and 8. Mean semantic keypoint error is 0.061311H, 0.079810H,
and 0.073091H. The difficult side view uses a disclosed 0.45 IoU diagnostic
threshold after removing a studio-floor reflection from its mask; the other
views retain 0.50. These scores are not proof of hidden geometry.

Texture is no longer generic generated speckle or a photographic collage. A
fixed-camera, foreground-mask, frontmost-face bake contributes 14,749
source-observed texels to 486 visible cuboid faces at one texel per model unit.
The observations are prefiltered and reduced to a shared 24-color palette with
at most four colors per semantic material. The remaining 56,003 texels use
explicit authored solid colors; no hidden texture is claimed and no material
uses random dither. The exact unseen right-side cable routing and several
occluded control interfaces remain conservative inference. No animation was
authored.

Reproduce from the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/07-centaur-exoskeleton/prepare-inputs.py
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/07-centaur-exoskeleton/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py bake-reference-textures benchmarks/round2/cycles/07-centaur-exoskeleton/model-spec.json --views benchmarks/round2/cycles/07-centaur-exoskeleton/texture-views.json --style minecraft --texture-density 1 --palette-size 24 --colors-per-material 4 --atlas-size 1024 --output benchmarks/round2/cycles/07-centaur-exoskeleton/model-spec.json --audit benchmarks/round2/cycles/07-centaur-exoskeleton/texture-evidence.json
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py validate benchmarks/round2/cycles/07-centaur-exoskeleton/model-spec.json --strict
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/07-centaur-exoskeleton/render-evidence.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/07-centaur-exoskeleton/model-spec.json --output benchmarks/round2/cycles/07-centaur-exoskeleton/build
PYTHONPATH=skill/img2blockbench/scripts python3 -m unittest tests.test_round2_07_centaur -v
```

The three source images, mask overlays, copied build reference, and ZIP remain
ignored because redistribution rights were not established.
