# Autoresearch cycle design history

## How to read this document

This is the chronological engineering record for all three img2blockbench
autoresearch rounds. Each cycle records the failure being tested, the reusable
capability added, the design decision, representative measurements, and the
regression gate.

Measurements and visual judgments are deliberately separated. Round 1 used a
six-category five-point visual rubric. Rounds 2 and 3 used six four-point
categories. Camera and alignment protocols also evolved, so raw scores should
not be compared across cycles without their method. See
[Metrics and regression design](METRICS_AND_REGRESSIONS.md).

The `benchmarks/` tree retains the current assets and most historical evidence.
Those paths exist only in the full research checkout; the compact platform
release intentionally omits the media-heavy benchmark tree. Some original
Cycle 1–4 artifacts were overwritten by later semantic replacements and are
recoverable from gate commits `97e2584`, `cce0b17`, `ed09970`, and `e7bde80`.
When a later cycle replaced an earlier representation, both are described
below; the later cumulative gate is the current result.

## Round 1 — establish complementary reconstruction routes

Round 1 began with single-image relief and progressively added semantic,
mesh, multiview, and clip-based routes. Every gate included all previously
accepted assets.

| Cycle | Asset | Main platform improvement | Cumulative result |
| --- | --- | --- | --- |
| 01 | American Goldfinch | Deterministic single-image relief | 1/1 pass |
| 02 | Porsche 911 Turbo | Masks, depth fields, adaptive cuboids | 2/2 pass |
| 03 | Excalibur | PCA-oriented thin-object reconstruction | 3/3 pass |
| 04 | Nian plus mesh proof | Six-direction mesh ray voxelization | 4/4 pass |
| 05 | Tomato Devil | Semantic chains and exact rounded volumes | 5/5 pass |
| 06 | SCP-173 | Calibrated multiview and clip ingestion | 6/6 pass |
| 07 | Gamma | Atomic tapered branch graphs and final jury | 7/7 pass |

### Round 1 Cycle 01 — American Goldfinch

Problem: the original system needed a deterministic path for an arbitrary
image even when no semantic model or mesh existed.

Implementation:

- added border-palette foreground segmentation;
- retained the strongest connected foreground and filled small holes;
- converted silhouette distance bands into depth layers;
- covered rows with native cuboids;
- mapped normalized source regions into one deterministic texture;
- emitted front, isometric, reprojection, PSNR, and MAE evidence.

Decision: this route was explicitly labeled 2.5D. A source-facing match was
useful, but hidden anatomy was not claimed.

Gate-time relief measurements:

- 69 cuboids, two bones, shell counts `25 / 23 / 21`;
- 96×96 analysis, foreground fraction `0.267687`;
- reprojection PSNR `20.8953 dB`, MAE `12.9361`, frame fraction `0.266356`;
- deterministic rebuild and a clean audit except for the expected high-count
  warning;
- standardized six-category record `3.95/5`; a separate explicitly
  independent grader recorded `8.0/10`.

Later regression decision: Cycle 6 replaced the relief with a real bilateral
semantic bird because compressed legs, tail, and layered side edges remained.
The current model has 98 cuboids, 40 bones, 33/33 connected joints, profile IoU
`0.809408`, recall `0.922049`, precision `0.868862`, and aspect error
`0.012784`. Its Cycle 7 visual score is `4.17/5`. The old PSNR and new
silhouette metric measure different representations and are not an
apples-to-apples gain.

Evidence: `benchmarks/cycles/01-goldfinch/`,
`benchmarks/grades/cycle-01.json`.

### Round 1 Cycle 02 — Porsche 911 Turbo (930)

Problem: a foreground silhouette alone could not represent a vehicle’s
greenhouse, wheels, underbody, and front/rear volume.

Implementation:

- added exact-resolution external masks and hash/dimension validation;
- treated subject bounds as a segmentation ROI or mask clip, never a solid
  replacement mask;
- added grayscale depth maps and symmetric depth around a center plane;
- added adaptive rectangle decomposition over depth layers;
- tracked retained subject coverage alongside pixel error.

Gate-time relief measurements:

- full 96-cuboid budget, four shell levels `27 / 28 / 27 / 14`;
- grid `54×20`, foreground fraction `0.138765`;
- PSNR `17.3936 dB`, MAE `19.8963`, reprojected fraction `0.136512`;
- Goldfinch’s prior reconstruction remained byte-identical;
- both assets passed at `3.83/5`.

Later regression decision: Cycle 6 replaced the symmetric relief with a
complete semantic vehicle. The 97-cuboid, 13-bone result adds four independent
seven-cuboid wheels, underbody, raked greenhouse, lamps, mirrors, Turbo
haunches, exhausts, and a connected whale-tail spoiler. Fixed source-angle IoU
improved from `0.690875` in semantic V1 to `0.710780` in V2; all 16 declared
links connect and wheel-ground heights differ by less than `0.009` units. The
final score reached `4.17/5` through better identity and topology, not source
pixel copying.

Evidence: `benchmarks/cycles/02-porsche/`,
`benchmarks/grades/cycle-02.json`.

### Round 1 Cycle 03 — Excalibur

Problem: scanline cuboids waste budget and stair-step a long diagonal blade.

Implementation:

- computed one global principal axis from the reviewed mask;
- rectified the mask, retained partially covered thin cells, decomposed it,
  and rotated all cuboids back around one pivot;
- separated geometry precision from texture density;
- kept precision opt-in so legacy models remained byte-identical.

Gate-time PCA relief measurements:

- angle `-44.244512°`, principal-axis ratio `75.556578`;
- 96 cuboids on grid `122×28`, shell counts `24 / 25 / 29 / 18`;
- depth/length `0.0375`;
- aligned silhouette IoU `0.959239`, recall `0.984562`, precision `0.973887`;
- texture PSNR `17.9004 dB`, MAE `13.3359`;
- all Cycle 1–2 artifacts rebuilt byte-for-byte;
- Excalibur scored `4.40/5`.

Regression decision: the release gate later rejected this apparently excellent
IoU because the object still read as a stair-stepped mask with weak hilt and
reverse-side evidence. Cycle 6 replaced it with 30 semantic cuboids on 19
bones, independent front/reverse runes and crests, and 31 connected links. The
different semantic source-view IoU is only `0.515895`, while the major-axis
error is `1.618621°` and physical depth/length is `0.028184`. Cycle 6 recorded
`4.67/5`; Cycle 7 recorded `4.17/5` for the unchanged semantic artifact. Both
passed, but their different review records should not be treated as a measured
score increase. This is the clearest Round 1 decision to prefer correct
topology and two-sided design over optimizing one silhouette metric.

Evidence: `benchmarks/cycles/03-excalibur/`,
`benchmarks/grades/cycle-03.json`.

### Round 1 Cycle 04 — Nian and executable mesh reconstruction

Problem: a complex creature exposed both the pancake limitation and the lack
of a general mesh-to-cuboid path.

Mesh capability:

- loaded every transformed GLB/GLTF scene node;
- cast deterministic rays on all three axes and retained six signed views;
- sampled UV, vertex, face, or material color at barycentric hits;
- used six-neighbor component cleanup;
- used parity fill only for watertight meshes and conservative surface fill for
  open meshes;
- adaptively fit at most 96 native cuboids;
- kept NumPy/trimesh optional and avoided `rtree`, SciPy, and Embree.

Evidence integrity decision: the Nian page exposed a proprietary `.max`, not
a usable GLB. It was never mislabeled as mesh evidence. The generic route was
proved separately on the bundled topologically open/non-watertight chimpanzee
GLB. Its provider and license remained recorded as `unrecorded`.

Nian iterations:

1. symmetric relief failed at `2.93/5` because it read as depth walls;
2. semantic volume plus source-skin panels failed at `3.67/5` because the skin
   hid weak anatomy and looked photographic;
3. an all-semantic 65-cuboid model passed the cycle at `4.1667/5`.

Mesh proof measurements:

- 6,272 vertices, 7,942 triangles, 2,123 unique ray lines, 4,246 signed rays,
  and 2,518 intersections;
- 1,946 retained voxels, none removed, fitted by 72 cuboids;
- source coverage `1.0`, voxel IoU `0.507035`;
- tolerant surface F1 `0.935582`;
- internal orthographic mean IoU `0.956008`;
- independent triangle-raster mean IoU `0.8191`, coverage `0.9992`, precision
  `0.8196`;
- 14 freshly generated files for each of Cycles 1–3 matched byte-for-byte.

Later regression work: stricter Cycle 5 review rejected the passed Nian for a
long, level torso, weak forequarters, and pillar-like legs. A later compact
79-cuboid candidate improved reference/profile IoU to
`0.759237`/`0.688077`, but introduced a visible `0.406516` hind-ankle gap and
was rejected. The final 80-cuboid, 32-bone model accepts slightly lower IoU
(`0.753290` reference, `0.661169` profile) for connected crouched
hindquarters, ankle overlaps `0.689163` and `0.696333`, a width/length ratio
of `0.752396`, and flush pixel motifs without plaque edges. Final Cycle 7
score: `4.33/5`.

Evidence: `benchmarks/cycles/04-nian/`, especially `mesh-proof/` and the two
failed-attempt review records.

### Round 1 Cycle 05 — Tomato Devil

Problem: one-off appendage placement did not generalize to a round body with
many eyes, radial leaves, and eight grounded arms.

Implementation:

- added arbitrary-3D chains with shared pivots and parented bones;
- added local-Z blade chains, radial profiles, and outward-normal orientation;
- audited joints against compiler-snapped oriented cuboids rather than loose
  world-axis bounds;
- added exact ellipsoid/superellipsoid voxelization;
- merged exact occupancy using deterministic multiple-strategy cuboid fitting;
- enforced a hard cuboid budget;
- raised the reviewed semantic model ceiling to 192 while keeping automated
  mesh budgets separate.

Iteration metrics:

- initial 94-cuboid model: body depth/width `0.755495`, eye RMS `0.015555`;
- radial 128-cuboid model: body depth/width `0.932217`, but eye RMS regressed to
  `0.042555`;
- final 192-cuboid model: exact 1,416-voxel `14×16×12` ellipsoid merged into 61
  body cuboids, depth/width `0.992556`, width/height `0.982927`, eye RMS
  `0.012680`.

Final gates: 68 bones, 121/121 links, minimum joint margin `0.072155`, eight
grounded arm endpoints, arm span/body width `1.374795`, arm depth/body depth
`1.133566`, ten eyes, 32 fingers, six two-stage leaves, and five teeth. Tomato
scored `4.17/5`; cumulative mean was `4.03/5`.

Regression decision: multiple combined candidates failed because Tomato or
Nian remained rectangular. Tomato passing alone did not allow the cumulative
cycle to pass while Nian remained broken.

Evidence: `benchmarks/cycles/05-tomato-devil/`,
`benchmarks/grades/cycle-05.json`.

### Round 1 Cycle 06 — SCP-173, multiview, and clip ingestion

Problem: the platform needed to use multiple images without pretending that
authored proxy views were independently observed evidence.

Implementation:

- added explicit orthographic-yaw calibration and common-volume visual-hull
  intersection;
- required every view to be `observed` or `synthetic_proxy`;
- measured all-view and observed-only horizontal constraint rank separately;
- made reconstruction independent of manifest ordering;
- fused only visible colors, with observed samples taking precedence;
- added caller-timestamped `ffmpeg` frame extraction without inferred motion;
- validated requests before `ffmpeg`, checked decoded frame/mask dimensions,
  and published manifests atomically.

View proof: one observed front plus one side proxy produced all-view rank `2`
but observed-only rank `1`, so hidden geometry remained unestablished. The
72-cuboid fit scored `0.885125` front IoU and `0.868913` proxy-side IoU. The
synthetic two-view clip fixture, processed through the real `ffmpeg`
executable, produced 16 cuboids, observed rank `2`, front IoU `0.825636`, side
IoU `0.768511`, and coverage `1.0` for both. It exercised ingestion and
calibration rather than validating a real-world subject.

SCP regression: an earlier 112-cuboid model received an author-side `4.33/5`,
but a later release grader rejected it at `3.73/5`. It used protruding face
pads, repetitive crack noise, and shallow volumes. The final 79-cuboid,
14-bone model uses a flush procedural face over 43 faces.
Head depth/width rose `0.8625 → 1.0`; torso depth/width rose
`0.813559 → 0.949153`; silhouette barely changed
`0.814090 → 0.814957`. The meaningful improvement was material and 3D
coherence, not outline fitting. The corrected SCP passed Cycle 6 at `4.00/5`;
Cycle 7 regraded the unchanged result at `4.17/5`.

This cycle also replaced the Goldfinch, Porsche, and Excalibur reliefs with
semantic volumes. The cumulative visual mean reached `4.19/5`, and `60/60`
tests passed.

Evidence: `benchmarks/cycles/06-scp-173/`, including `view-proof/` and
`clip-proof/`; `benchmarks/grades/cycle-06.json`.

### Round 1 Cycle 07 — Gamma

Problem: branching anatomy needed a reusable validated graph rather than
manually placed chains.

Implementation:

- added deterministic named branch graphs;
- compiled tapered edges into parented piecewise cuboids;
- supported branches starting at shared joints;
- rejected duplicate nodes/edges, cycles, invalid generated IDs, nonfinite or
  degenerate geometry, multiple parents, detached roots, and disconnected
  nodes before mutation;
- added alpha-aware aspect-preserving silhouettes, normalized named-keypoint
  error, and source-frame clipping disclosure.

Measurements:

- 111 cuboids, 67 bones, 13 branch graphs, 120/120 links;
- eight mandible chains and 40 segments across three depth layers;
- four mechanical legs, eight hinges, two leg depth layers, two ring
  assemblies;
- alpha IoU `0.672993`, precision `0.717009`, recall `0.916408`;
- six-keypoint mean error `0.046625H`, maximum `0.082522H`;
- real depth/full width `0.277409`; all eight proportion gates passed.

The source touched all four frame edges, so off-frame continuation remained an
explicit limitation. Gamma scored `4.17/5`. All seven assets passed at a
`4.19/5` mean; the Goldfinch/Porsche/Nian/Gamma jury passed at `4.21/5`.
The exact-commit grader ran 7/7 strict validations, 7/7 native audits, and
67/67 tests without consulting prior verdicts. Cycle 7 also preserved every
prior benchmark tree from its `aeb8888` baseline.

Evidence: `benchmarks/cycles/07-gamma/`, `benchmarks/final-jury.json`, and
`benchmarks/grades/cycle-07.json`.

### Round 1 record caveats

Some historical summary fields were superseded by later cycles and are not
used as the current gate:

- Goldfinch's cycle-local `results.json` still says
  `external_regrade: pending`; the Cycle 6 and Cycle 7 cumulative grades pass
  its semantic replacement.
- Cycle 5's broad regression record names baseline `aba4ffc`, although Nian
  was deliberately revised afterward and its tree hash changed.
- Cycle 6's broad preservation statement fails to account for the
  already-present Porsche refinement and the later Excalibur replacement.
  Current cumulative grades, focused determinism records, and the actual Git
  diff take precedence.
- Near-duplicate image-content detection was added in Round 2 Cycle 08. Round
  1 Cycle 06 distinguished declared observed and proxy evidence but did not
  yet group duplicate pixels automatically.

## Round 2 — harder topology, evidence, wearables, and texture policy

The Round 2 source list named ten assets. Eight image assets became completed
cycles. The two private GLBs could not be read from the protected Downloads
location and were never given a pass. Milestones 09 and 10 are cross-cutting
remediation cycles, not additional asset claims.

| Milestone | Focus | Outcome |
| --- | --- | --- |
| 01 | Golden Apple | True carved negative space |
| 02 | Militech Chimera | Six-legged topology and fixed cameras |
| 03 | Greta | Existing semantic primitives stress-tested |
| 04 | False Apple | Deep asymmetry and carved maw |
| 05 | Aegis X2 | Three-view hard-surface evidence |
| 06 | Falling Devil | Twelve arms and layered depth |
| 07 | Militech Centaur | Piloted exoskeleton, later wearable shell |
| 08 | Zombie Devil | Duplicate-aware single-axis inference |
| 09 | Cross-cutting remediation | Texture baker, wearable export, depth/mass fixes |
| 10 | Palette reconciliation | Chimera camouflage and colorful Zombie fallback |

### Round 2 Cycle 01 — Golden Apple

Problem: a bite and top dimple painted black can look correct from one view but
remain solid geometry.

Implementation: `EllipsoidCutout` subtracts voxel-center occupancy before
greedy merging. The result records initial occupancy, removed voxels, and
exposed carved faces so interior materials are auditable.

Measurements: 155 cuboids, 42 bones, 154/154 links; `3,912 → 3,530` occupied
voxels with 382 removed; two cutouts, ten exposed dark faces, and zero black
proxy solids. Source IoU was `0.705691`, keypoint error `0.022501H`, and apple
depth/width `1.060606`. Four roots occupied all four X/Z quadrants. The cycle
passed at `3.83/4` with 71/71 tests and byte-identical builds.

Decision: reuse branch graphs for roots rather than add an asset-specific API.

Evidence: `benchmarks/round2/cycles/01-golden-apple/`.

### Round 2 Cycle 02 — corrected Militech Chimera

Problem: the first model was visually plausible but factually wrong: 83
cuboids, 26 bones, and four legs. Its IoU `0.640641` and `0.060705H` keypoint
error did not expose the topology failure.

Implementation:

- added a deterministic fixed-perspective renderer;
- validated camera basis and near-plane handling;
- added perspective-correct UV interpolation, z-buffering, and back-face
  rejection;
- made rendering stable across cube order;
- scored raw same-frame silhouettes and keypoints without post-render fit.

Correction: the four-leg result and its early grade were invalidated. The
replacement has 174 cuboids, 36 bones, six four-link leg chains, 24 leg
segments, 18 hinges, six feet, 18 toes, 18 shin-armor layers, 12 collar pieces,
38 turret cuboids, and 191/191 connected attachments. Chassis depth/width rose
`1.665560 → 1.694929`.

Tradeoff: correct anatomy reduced original-view IoU
`0.640641 → 0.605818` and increased keypoint error
`0.060705H → 0.066869H`. The alternate view scored `0.632529` and
`0.070894H`. A provisional `0.65`/`0.06H` aspiration was made non-blocking
because distorting six-leg geometry for one camera would be a regression.

Final palette: the original olive/khaki camouflage is canonical; the white
image is geometry-only. The Minecraft bake contains 1,261 observed texels on
161 faces (`5.1812%` coverage), 24 global colors, no more than four per
material, and no dither. Materials/color rose `3 → 4`. The conservative final
panel scored silhouette/proportions 3 and all other categories 4.

Evidence: `benchmarks/round2/cycles/02-militech-chimera/`.

### Round 2 Cycle 03 — Greta

Problem: test whether the existing semantic toolkit could represent multiple
mouths and attached props without adding one-off primitives.

Decision: no engine primitive was added. Existing chains, branch graphs,
landmarks, attachment audits, and evidence rendering were sufficient; avoiding
an unnecessary abstraction was itself a generalization decision.

Measurements: 72 cuboids, 35 bones, 71/71 links, exactly four toothed mouth
assemblies, eight tooth-row landmarks, and 22 tooth cuboids. Source IoU was
`0.684950`, keypoint error `0.029263H`, torso depth/body width `0.660870`, and
head depth/body width `0.592076`. The source was complete and unclipped.

Corrections made the grin readable at full scale, reduced material noise,
replaced a glyph-like tattoo with flowing blue stair ribbons, simplified the
tail into a broad taper with two lobes, and rebuilt the axe as a connected
hooked cleaver. Final visual grade: 4/4 in every category.

Evidence: `benchmarks/round2/cycles/03-greta/`.

### Round 2 Cycle 04 — False Apple

Problem: a low, asymmetric root creature needed true cavities and separate
near/far depth layers, not a biped template.

Decision: reuse Cycle 01 cutout CSG, branch graphs, and oriented contact
audits. Explicit selected-part world extents were sufficient; no new depth API
was added.

Measurements: 189 cuboids, 79 bones, 188/188 links; 78 skull voxels removed
for a real maw, zero black proxy solids, and a separate 32-cuboid apple with 25
removed voxels. IoU was `0.638953`, keypoint error `0.029835H`, apple
depth/width `0.75`, maw depth/height `0.583333`, and near/far root separation
`28.734837` units. It passed 4/4 in all categories with 90 cumulative tests.

The source touches all four frame edges, so off-frame root continuation stays
unverified.

Evidence: `benchmarks/round2/cycles/04-false-apple/`.

### Round 2 Cycle 05 — Aegis X2

Problem: a mechanically dense hard-surface object needed several views but did
not have calibrated silhouettes suitable for a visual hull.

Decision: use three independent frozen perspective cameras for semantic
corroboration. Camera parameters are disclosed as estimates; the evidence is
not labeled calibrated reconstruction and makes no hidden-geometry claim.

Measurements: 145 cuboids, 11 bones, 144/144 connected attachments and four
grounded supports. View IoUs were `0.635555`, `0.665274`, and `0.630694`;
keypoint errors were `0.038758H`, `0.036311H`, and `0.037577H`. Every view
passed its `0.60` IoU and `0.06H` aspiration. The model includes asymmetric
cannon/launcher assemblies and opposed weapon axes.

Later Minecraft texture bake: 8,768 observed texels on 326 faces,
`21.8762%` coverage, 24 global colors, at most four per material, and no
dither. Cycle-local mean was `3.83/4`; the final cumulative panel scored
materials/color more conservatively at 3. The gate had 99/99 tests.

Evidence: `benchmarks/round2/cycles/05-aegis-x2/`. This documentation pass
also corrected its stale “140-link” sentence to the tested 144/144 count.

### Round 2 Cycle 06 — Falling Devil

Problem: layered repeated anatomy had to preserve exact count, depth ordering,
and physical contact with a detached head.

Design: all six arm pairs are twelve independent three-segment chains. A
six-segment waist tendril is semantically separate so it cannot be mistaken
for a seventh arm. Four hands physically support the head.

Measurements: 78 cuboids, 53 bones, 77/77 links; six depth bands span
`16.966112` units with minimum pair-center separation `1.930865`; torso
depth/width `0.564583`; fixed-camera IoU `0.700233`; keypoint error
`0.018635H`; four of four head contacts. The cumulative gate reached 103/103
tests.

Later texture bake: 3,286 observed and 24,840 fallback texels,
`11.6831%` source coverage on 132 faces, one texel per unit, 24 global colors,
at most four per material, and no dither. Final visual grade: 4/4 throughout.
Clipped shoes remain disclosed inference.

Evidence: `benchmarks/round2/cycles/06-falling-devil/`.

### Round 2 Cycle 07 — Militech Centaur exoskeleton

Problem: the source model already distinguished a pilot from the powered
exoframe, but the deliverable could not yet become equipment around a
replacement player.

Research decision: official front/right/left/back art, concept sheets, and
video timestamps `1:23`, `1:27`, `2:08`, and `2:12` established the wearer
relationship. Web/video research informs the agent’s topology decision; it is
not a runtime dependency or texture-calibration source.

Wearable capability:

- added a validated removable-occupant contract;
- derived a shell-only model and Bedrock attachable automatically;
- required retained shell bones not to descend from occupant bones;
- validated metadata, bone ownership, player scale, origin mapping, collision,
  anchor mapping, and interface coordinates. Asset tests and review separately
  establish the open cavity and physical contacts.

The source-comparison model has 192 cuboids and 28 bones. The wearable removes
seven occupant bones and has 168 cuboids, 21 bones, no audit errors, and six
interfaces: waist, back, two controls, and two boot stirrups. Scale `0.4` and
offset `[0,-5.6,-1.2]` map anchor `[0,14,3]` to `[0,0,0]`; an 85-unit authored
player becomes 34 units.

Regression decision: an exact-archive grader rejected the first optimistic
pass because the powered legs were visually spindly. The correction enlarged
hips, `10×10×10` knee cores, 16-unit feet, shin armor, and ankles while
preserving the pilot cavity.

Before → after fixed-camera IoU:

- source 6: `0.567833 → 0.603863`;
- source 7: `0.463441 → 0.475590`;
- source 8: `0.526309 → 0.542573`.

Keypoint errors changed `0.061855 → 0.061311H`,
`0.083226 → 0.079810H`, and `0.072842 → 0.073091H`. Proportions rose
`2 → 3`. The final geometry has powered-leg, foot, boot-restraint, and shield
contact gates all at `2/2`, with 191/191 links.

Texture: 14,749 observed texels on 486 faces, `20.8461%` coverage, 24 global
colors, at most four per material, no dither. Coverage fell from `24.2951%`
even as observed texels rose from 14,303 because the corrected model added
unseen surface area; this was recorded as honest fallback, not called a loss.

Final visual mean: `3.333333/4`. Runtime animation/controller integration
remains out of scope.

Evidence: `benchmarks/round2/cycles/07-centaur-exoskeleton/`, including
`research-sources.json`.

### Round 2 Cycle 08 — Zombie Devil

Problem: two supplied images looked like multiple views but were nearly
identical crops; treating them as independent would fabricate depth evidence.

Decision: RGB correlation `0.999919` and normalized MAE `0.003353` reduced the
pair to one observed camera axis. Rear volume is explicitly authored. The
model rejects a normal upright-biped template in favor of a broad fused
shoulder mass, embedded face, exposed brain, asymmetric fists, organ
swellings, visceral paths, and no feet.

Depth remediation preserved each observed positive-Z surface while extending
cubes rearward:

- torso depth/width `0.50 → 0.75`;
- head `0.611111 → 0.833333`;
- brain `0.833333 → 1.166667`;
- arm Z extent `25 → 35`, final arm depth/width `0.341463`;
- raw IoU `0.643458 → 0.645798`;
- normalized IoU `0.642441 → 0.644959`;
- keypoint error remained `0.069759H`;
- 3D-coherence score rose `2 → 3`.

Counts remained 188 cuboids, 24 bones, and 187/187 attachments. Two clipped
lower continuations are kept rather than inventing feet.

Palette history: a 16-color grayscale projection preserved the manga marks;
an attempted all-grayscale interpretation was then reverted at the user’s
request. The final model keeps observed pixels grayscale but uses dusty flesh,
pink brain, and muted red-brown fallback for inferred surfaces. Of 176,038
opaque atlas texels, 161,366 (`91.6654%`) are chromatic. The geometry
fingerprint stayed unchanged through the palette-only correction.

Final visual mean: `3.333333/4`; identity and materials scored 4, other
categories 3.

Evidence: `benchmarks/round2/cycles/08-zombie-devil/`.

### Round 2 Cycle 09 — wearable and texture-system remediation

This milestone consolidated several cross-asset fixes:

- defined the replaceable-wearer contract and automatic shell/attachable
  export;
- added calibrated visible-face texture projection with foreground masks and
  z-buffer ownership;
- selected the most front-facing camera with deterministic tie-breaking;
- separated observed and fallback texels;
- introduced `minecraft` style with density 1, a 1024 atlas, at most 24 global
  colors, at most four colors per material, and no dither;
- replaced the first Round 2 v1 bakes—which used literal projection at density
  4 and 2048 atlases—with prefiltered, palette-bounded pixels; observed-texel
  totals across those v1 and v2 bakes therefore are not directly comparable;
- kept literal `source` style opt-in for compatibility;
- removed 26 `dither` materials across the eight benchmark specs;
- kept baking opt-in so unchanged procedural models still build byte-for-byte;
- corrected Centaur leg mass and Zombie rear depth after the independent
  archive gate rejected both earlier results.

This cycle demonstrates the cumulative rule: texture improvement could not
mask geometry regressions. Centaur proportions and Zombie 3D coherence each
had to move from 2 to 3 before the release gate passed.

Evidence: commits `cedca58`, `fde89e7`, `37c84b3`, `e0585c5`, `8254fc1`,
`f19c921`, `f5dd206`, `8edbffd`, `df4ad06`, and milestone `f07eb4f`.

### Round 2 Cycle 10 — source-palette reconciliation

Problem: a universal “more source-faithful” rule conflicted with two distinct
user requirements.

Decisions:

- Chimera uses the original olive/khaki military source as canonical; its
  white image remains topology-only evidence. Observed coverage decreased from
  1,384 texels/193 faces to 1,261/161. Those different source cameras make the
  counts provenance accounting rather than a quality delta; finish correctness
  improved and the materials score rose `3 → 4`.
- Zombie separates source observation from authored inference. Manga pixels
  remain grayscale, while unobserved Minecraft surfaces use the requested
  colorful palette.
- Palette-only commits must preserve the geometry fingerprint and all camera
  metrics.

The final four-asset gate passed Chimera, Aegis X2, Centaur, and Zombie Devil
with every category at least 3/4 and no blocker. It recorded raw fixed-camera
IoUs of Chimera `0.605818/0.632529`, Aegis
`0.635555/0.665274/0.630694`, Centaur
`0.603863/0.475590/0.542573`, and Zombie `0.645798`, with no post-render
alignment. Round 2 finished at 139/139 cumulative tests, plus 27/27 safe
geometry-archive and 9/9 color-restoration checks.

Evidence: `benchmarks/round2/STATUS.md`, `final-judging.json`, and
`final-showcase.json`.

## Round 3 — holistic 3D evidence

Round 3 directly targeted the pancake failure: strong front resemblance with
flat or uninformative sides, back, top, and bottom.

The engine foundation added before the asset cycles:

- six signed mesh directions plus an isometric source/fit/overlap review;
- real fitted-cuboid occupancy instead of assuming source coverage implied a
  good fit;
- per-axis silhouettes and bidirectional depth envelopes;
- source-relative anti-pancake thresholds;
- one-to-one source/fitted component maps;
- failure instead of silent component loss under cuboid pressure;
- portable review and mesh provenance.

### Round 3 Cycle 01 — biblically accurate angel

Problem: one frontal painting encouraged a detailed but flat wing wall.

Design: the result is explicitly semantic inference, not recovered hidden
geometry. It uses a deep stepped core, a wrapped many-eyed crown, three wing
pairs across rear/middle/front-lower depth sectors, and compact three-stage
feather tapers. No source pixels enter the atlas; materials are solid
Minecraft swatches.

Measurements:

- 189 cuboids, 113 bones, 188/188 physical links;
- 21 geometric eyes: seven front, five back, two side, one top, six wing;
- six wings, 18 primary feathers, 12 broad vanes, and 30 three-stage taper
  profiles;
- full depth/width `0.474180` against a `0.40` minimum;
- body depth/width `0.955629` against `0.85`;
- wing depth span `30.0` units;
- all 108 wing-shape cuboids have nonzero yaw;
- side/front area `0.673758`, side/front width `0.547170`;
- back/front area `0.981761`, top/front and bottom/front `0.750201`;
- at least 20 cuboids in each front/middle/rear band;
- 14 model-only render hashes, with all seven holistic views distinct.

Regression decision: the first wing tips read as square paddles. All 30
profiles were changed to three strictly narrowing stages with caps no larger
than `1.4×1.0`, 15 terminal lengths, and maximum terminal length `5.933271`.
The exact-commit grader passed the result at `18/24`; Minecraft segmentation
remains a non-blocking stylistic caveat.

Evidence: `benchmarks/round3/cycles/01-biblical-angel/`.

### Round 3 Cycle 02 — Zetatech Atlus

Problem: the supplied front-quarter image alone could encourage a decorated
front slab.

Design: the agent researched five independent exterior directions—front,
front-quarter, side, rear, and top—plus the supplied screenshot. These are
hash-bound semantic references, not claimed calibrated cameras. Hidden
underside internals remain disclosed bilateral inference.

Measurements:

- 165 cuboids, nine bones, 28 landmarks, 46/46 connected attachments;
- overall extents `37.483459 × 24.745358 × 61.5625`;
- overall length/width `1.642391`, central hull length/width `2.507870`;
- both side pods cover `0.729949` of total length;
- minimum axis/maximum axis `0.401955`;
- front/back pixel difference `0.102881`, top/underside `0.233700`;
- four landing shoes grounded at `0.0`;
- 98 side-detail cuboids, 20 central-fuselage cuboids, 22 cuboids per side pod,
  eight weapon barrels and collars, eight rear louvers, six thruster cuboids,
  and three aerials.

Directional evidence ratios were front width/height `1.452055`, front-quarter
occupancy `0.418177`, rear width/height `1.5`, side length/height `2.418251`,
and top length/width `1.641378`. The source-free native build and every model
render were hash-checked. Independent grade: `20/24`, with 4/4 for materials
and holistic 3D coherence.

Evidence: `benchmarks/round3/cycles/02-atlus/`.

### Round 3 Cycle 03 — off-road truck GLB

Round ledger status: `PENDING_INPUT`, neither an asset pass nor a quality
failure. The latest runner result is `BLOCKED` with
`MISSING_PRIVATE_INPUT` because the expected private GLB was not readable
inside the repository.

The cycle runner is complete and exercises the holistic mesh route. A first
successful reconstruction will lock source SHA-256 and byte length, emit all
seven review views, and stop at `AWAITING_AGENT_VISUAL_REVIEW`. Later source
replacement causes `SOURCE_HASH_MISMATCH`. Exit code 0 means automated
evidence is ready, never visual approval.

A synthetic-box test proves the runner, lock, deterministic rerun, portable
bundle, and replacement rejection. It is not a truck quality grade.

Evidence: `benchmarks/round3/cycles/03-off-road-truck/`.

### Round 3 Cycle 04 — Minecraft hovercraft GLB

Round ledger status: `PENDING_INPUT`; latest runner result: `BLOCKED` with
`MISSING_PRIVATE_INPUT`. The cycle shares the truck runner and preserves its
explicit arguments, six-axis reconstruction, isometric review, hash lock, and
separate-agent requirement. No visual or asset-quality claim exists.

Evidence: `benchmarks/round3/cycles/04-hovercraft/`.

### Round 3 gate status

The angel and Atlus passed independently at exact commit `640b8e7`. The mesh
pipeline passed 25/25 targeted tests and 169/169 tests overall at that point.
Round 3 remains `IN_PROGRESS` with `cumulative_pass: false` because the truck
and hovercraft inputs are missing. Keeping this status is a deliberate
anti-fabrication decision.

## Platform consolidation — version 0.3

The consolidation branch descends from all seven Round 1 cycle heads, all ten
numbered Round 2 milestones, and the Round 3 holistic branch. Three older
perspective/texture side branches were not merged because their patches were
already equivalent to or superseded by the accepted history; merging them
would have restored stale palette choices.

The consolidation added production features not tied to one benchmark:

- a generic seven-angle semantic `review` command and model-only sheet;
- distinct mesh and semantic review keys so evidence cannot overwrite itself;
- exact source hashes plus canonical content fingerprints that survive
  packaging rewrites but reject stale geometry or materials;
- path-containment, hash, model-ID, privacy, and input/output collision checks;
- an `external-reference/` namespace that prevents a source named
  `MODEL_ID.png` from aliasing the generated atlas;
- explicit reference bundling policy without destructive cleanup;
- portable rebuilds from delivered semantic and mesh specifications;
- failure rather than silent component truncation in multiview fitting;
- NumPy-only multiview/reference extras and trimesh only for actual mesh work;
- actionable optional-dependency errors, including the overlap CLI;
- a deterministic, media-free, allowlisted platform release;
- concise public documentation with the research archive kept separately.

The exact consolidation gate passed 193/193 tests, deterministic clean-source
release rebuilding, isolated wheel build/install, all runtime imports, CLI
review/build smoke, checksum verification, and multiple independent read-only
audits. No remote is configured and no branch or artifact was pushed.

## Cross-round decisions

The cycles converge on several durable principles:

- A higher single-view similarity score does not override wrong topology.
- A topology correction may legitimately reduce one view’s IoU.
- A component that cannot fit the budget causes failure, not disappearance.
- Observed, proxy, and inferred surfaces must remain separately labeled.
- Source texture coverage is not a quality target by itself.
- Minecraft abstraction means bounded authored pixels, not generated noise and
  not a photographic collage.
- A piloted reference and a wearable runtime asset require separate outputs.
- Missing private inputs remain pending rather than receiving synthetic grades.
- Structural metrics gate failure modes; independent visual review decides
  recognizability and appeal.
