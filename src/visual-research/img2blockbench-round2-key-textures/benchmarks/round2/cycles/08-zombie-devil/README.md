# Round 2 Cycle 08 — Zombie Devil

This cycle targets the duplicate-view and cropped-anatomy edge case. The two
provided PNGs are retained as separate provenance inputs, but their normalized
RGB correlation is `0.999919`; they therefore count as one observed camera
axis and do not establish hidden geometry.

Texture transfer intentionally uses only the 513x754 primary reference. It
does not count the near-duplicate crop as a second view. At density 4 in a
2048px atlas, 111,975 unquantized source texels cover 243 frontmost faces
(`8.5649%` of all face texels). The source ink, brain folds, eyes, mouth, and
viscera replace the former synthetic speckle on observed surfaces. Side, rear,
and occluded texels remain flat material-base colors rather than invented
detail. This makes the source-angle render substantially more literal while
honestly preserving the single-view limitation; `texture-evidence.json`
records the camera, hashes, and per-face coverage.

The remediated native model contains 188 cuboids and 24 bones. It reconstructs
one broad fused shoulder/torso field rather than a generic upright biped. The
large face is embedded low in that mass and has a true carved oval scream, six
physical teeth, enlarged bulging eyes, and nine modeled expression folds. A
broad neck blends into the exposed brain and ten raised cerebral fissures. The
two asymmetric arm masses end in enlarged fists and modeled knuckles.

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
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py bake-reference-textures benchmarks/round2/cycles/08-zombie-devil/model-spec.json --views benchmarks/round2/cycles/08-zombie-devil/texture-views.json --texture-density 4 --atlas-size 2048 --output benchmarks/round2/cycles/08-zombie-devil/model-spec.json --audit benchmarks/round2/cycles/08-zombie-devil/texture-evidence.json
PYTHONPATH=skill/img2blockbench/scripts python3 skill/img2blockbench/scripts/img2blockbench.py build benchmarks/round2/cycles/08-zombie-devil/model-spec.json --output benchmarks/round2/cycles/08-zombie-devil/build
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round2/cycles/08-zombie-devil/render-evidence.py
```

The fixed source-camera silhouette IoU is `0.643458`. The independently
height-normalized silhouette IoU is `0.642441`, with named-keypoint mean error
`0.069759` source subject-heights. The source camera is recorded and performs
no automatic fit or recentering. These remain single-view diagnostics, not
proof that the inferred rear surfaces are observed.
