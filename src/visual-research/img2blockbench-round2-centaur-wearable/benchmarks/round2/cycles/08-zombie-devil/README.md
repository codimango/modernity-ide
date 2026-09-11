# Round 2 Cycle 08 — Zombie Devil

This cycle targets the duplicate-view and cropped-anatomy edge case. The two
provided PNGs are retained as separate provenance inputs, but their normalized
RGB correlation is `0.999919`; they therefore count as one observed camera
axis and do not establish hidden geometry.

Texture transfer intentionally uses only the 513x754 primary reference. It
does not count the near-duplicate crop as a second view. At one texel per model
unit in a 1024px atlas, 8,177 source-observed texels cover 232 frontmost faces
(`6.4265%` of all face texels). The percentage is lower because the model now
contains substantially more honest, unobserved rear surface area. The line art
is prefiltered and reduced to a 16-color grayscale source palette with at most
two sampled colors per semantic material. The source-facing line work stays
monochrome, while the user-selected earlier warm flesh, pink brain, and muted
red-brown viscera palette colors the authored fallback surfaces. This remains
a Minecraft abstraction rather than a claim that the manga supplied color. It
keeps the face, brain, and viscera readable as Minecraft pixel art instead of
turning every ink stroke into photographic noise. Side, rear, and occluded
texels remain flat authored colors, and the one-view limitation remains
explicit in `texture-evidence.json`.

The remediated native model contains 188 cuboids and 24 bones. It reconstructs
one broad fused shoulder/torso field rather than a generic upright biped. The
large face is embedded low in that mass and has a true carved oval scream, six
physical teeth, enlarged bulging eyes, and nine modeled expression folds. A
broad neck blends into the exposed brain and ten raised cerebral fissures. The
two asymmetric arm masses end in enlarged fists and modeled knuckles. To avoid
a billboard result without pretending the duplicate crop is a second camera,
each organic volume is extruded only toward the inferred rear: every observed
positive-Z surface stays fixed. The measured torso depth-to-width ratio is now
0.75, the head 0.833333, the brain 1.166667, and the complete arm field exceeds
0.33. Rear colors remain restrained authored Minecraft blocks rather than
fabricated photographic detail.

Below the torn abdomen, four diagonal tapered organ ribbons are softened by
four overlapping organic swellings. They feed one closed intertwined loop and
two thick continuations. The model deliberately contains no legs or feet.
Those two unknown continuations extend beyond a frozen source camera and are
clipped by the bottom edge; no visible endpoint is presented as observed
anatomy.

Run locally with the ignored `image-10.png` and `image-11.png` at repository
root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/08-zombie-devil/prepare-inputs.py
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/08-zombie-devil/prepare-semantic-model.py
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py bake-reference-textures benchmarks/round2/cycles/08-zombie-devil/model-spec.json --views benchmarks/round2/cycles/08-zombie-devil/texture-views.json --style minecraft --texture-density 1 --palette-size 16 --colors-per-material 2 --atlas-size 1024 --output benchmarks/round2/cycles/08-zombie-devil/model-spec.json --audit benchmarks/round2/cycles/08-zombie-devil/texture-evidence.json
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/08-zombie-devil/model-spec.json --output benchmarks/round2/cycles/08-zombie-devil/build
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/08-zombie-devil/render-evidence.py
```

The fixed source-camera silhouette IoU is `0.645798`. The independently
height-normalized silhouette IoU is `0.644959`, with named-keypoint mean error
`0.069759` source subject-heights. The source camera is recorded and performs
no automatic fit or recentering. These remain single-view diagnostics, not
proof that the inferred rear surfaces are observed.
