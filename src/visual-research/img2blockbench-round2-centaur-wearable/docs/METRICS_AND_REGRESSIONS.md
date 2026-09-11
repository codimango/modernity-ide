# Metrics and regression design

## Why the platform uses multiple gates

No scalar score establishes that a Blockbench model is faithful. A silhouette
can match while depth is flat, a voxel fit can cover the source while grossly
overfilling it, and a clean audit can validate a model of the wrong subject.
img2blockbench therefore uses four layers:

1. contract and provenance validation;
2. deterministic geometry, topology, texture, and artifact metrics;
3. asset-specific identity gates;
4. independent visual review of the required views.

An asset passes only when every required layer passes. Missing input or
missing visual review remains pending; it is never converted into a numerical
pass.

## Metric families

### Silhouette metrics

For binary source mask `S` and model mask `M`:

- intersection over union: `|S ∩ M| / |S ∪ M|`;
- source coverage or recall: `|S ∩ M| / |S|`;
- model precision: `|S ∩ M| / |M|`.

IoU balances omitted and extra area. Coverage detects missing source parts.
Precision detects model overfill. All three depend on the camera and alignment
protocol, so a value is meaningful only with its recorded method.

Three protocols appear in the research history:

- aligned source-facing metrics permit a declared uniform scale and
  translation, and sometimes a recorded roll correction;
- fixed-camera metrics render directly through a frozen perspective camera
  without runtime fit, translation, or recentering;
- mesh projections compare source and fitted occupancy in a shared canonical
  voxel frame.

Values from different protocols are not directly comparable. In particular,
the high aligned Excalibur score from its original cycle and the later semantic
review score answer different questions.

### Keypoint metrics

Named landmarks are projected through the same camera as the render. Mean
point distance is divided by subject height, producing an error in “subject
heights.” This makes the number resolution-independent and catches a model
whose global silhouette is acceptable while eyes, wheels, weapons, or joints
are misplaced.

Keypoints are sparse constraints, not a surface metric. They cannot approve
unmeasured anatomy.

### Extent and ratio metrics

Compiled oriented-cuboid bounds yield X/Y/Z extents and ratios such as:

- depth to width;
- width or length to height;
- appendage span to body size;
- side-pod coverage of vehicle length;
- grounded foot or support height.

These are inexpensive anti-collapse checks. Thresholds are asset-specific for
semantic models. A source-relative mesh test is preferred when a real mesh is
available.

### Voxel and surface metrics

For mesh and visual-hull reconstruction, the engine compares its source
occupancy with the union of fitted cuboids. “Source” here means ray-derived
mesh occupancy for the mesh route and the internally carved occupancy for the
visual-hull route:

- voxel IoU measures exact occupied-cell agreement;
- source coverage requires source voxels to remain represented;
- model precision penalizes cuboid volume outside source occupancy;
- one-voxel-tolerant surface precision and recall compare dilated six-neighbor
  surfaces;
- their harmonic mean is the tolerant surface F1 score.

Tolerance acknowledges the deliberate cuboid approximation without hiding
large topology errors.

The visual-hull route additionally reports source-mask IoU, coverage, and
model precision per calibrated view. Its tolerant surface F1 describes fit to
the carved hull, not independent agreement with a real 3D surface.

### Depth-envelope metrics

For every projected ray on X, Y, and Z, the engine records the nearest and
farthest occupied cell. It derives:

- source depth-envelope coverage;
- model depth-envelope precision;
- depth inflation ratio;
- collapsed source ray count and fraction;
- normalized bidirectional boundary mean absolute error;
- model/source mean depth ratio.

The current generic mesh anti-pancake contract requires:

| Gate | Threshold |
| --- | ---: |
| Axis-span preservation | `>= 1.0` |
| Source depth-envelope coverage | `>= 1.0` |
| Collapsed source rays | `0` |
| Model voxel precision | `>= 0.25` |
| Per-axis model silhouette precision | `>= 0.50` |
| Per-axis model depth precision | `>= 0.35` |
| Maximum depth-envelope inflation | `<= 3.0` |
| Signed axis views recorded | `6` |
| Fitted component mapping | one-to-one |

Axes below `0.1` of the longest source span are recorded as intrinsically
thin, but they do not bypass coverage or overfill checks. This is how the same
gate can protect a deep hovercraft without forcing a sword to become thick.

### Component metrics

Six-neighbor connectivity means cells connect only across faces, not edges or
corners. Evidence records:

- components before and after cleanup;
- removed voxel counts and thresholds;
- cuboids assigned per retained source component;
- source-to-fitted and fitted-to-source component maps;
- merged, split, or unmapped component groups;
- one-to-one fitted connectivity.

The fitter reserves one leaf per retained component. If the cuboid budget is
smaller than that minimum, reconstruction fails. Earlier behavior sliced a
list to the budget and could silently discard a valid disconnected part; the
consolidated regression tests prohibit that behavior for both mesh and
multiview routes.

### Attachment metrics

Semantic models declare parent-child or part-to-part connections. The audit
transforms each rotated cuboid into compiled space and measures whether the
declared joint lies inside or touches both shapes. Its core report contains a
record and margin for every declared attachment, the minimum margin, and an
`all_connected` result. Asset evaluators derive link counts and coverage from
those records.

A bone parent relationship alone is insufficient: it describes hierarchy but
does not prove that two rendered pieces meet.

### Texture metrics

Calibrated texture evidence records:

- source-observed faces and texels;
- source fraction versus disclosed fallback fraction;
- global palette size and colors per semantic material;
- texture density and atlas size;
- mask rejection and occlusion outcomes;
- whether dithering or literal source projection was used.

Higher source fraction is not automatically better. A small, accurate set of
logos and panels plus clean fallback may be more faithful to Minecraft than a
photographic wrap. The hard policy is truthful attribution, bounded palette,
no accidental background transfer, and no random-noise substitute for detail.

### Render-diversity metrics

Directional render checks include silhouette area ratios, bounding-box width
ratios, foreground occupancy, and normalized pixel differences between
opposing views. They catch identical or nearly empty sides and backs.

Distinct hashes prove that files differ, not that the differences are correct.
The generic review therefore treats duplicate view hashes as a warning because
true symmetry is possible. Nonempty required views and portable artifacts are
blocking; resemblance remains a visual decision.

### Reproducibility and provenance metrics

The platform hashes source files, model specifications, review images,
manifests, and delivery artifacts. Determinism tests compare complete output
bytes across two builds. Private-input contracts lock SHA-256 and byte length
after a first successful reconstruction and reject later substitution.

The canonical model-content fingerprint excludes delivery-local reference and
mesh locator/status metadata, plus generated review records. Geometry,
materials, texture rules, source hashes, semantic metadata, and quality
contracts remain covered. This permits a localized delivery spec to rebuild
while rejecting a stale review after a substantive edit.

Hashes answer “is this the same artifact?” They do not answer “is it good?”

## Visual scoring protocols

The rubric changed between rounds and historical scores must retain that
context.

| Research phase | Scale | Pass interpretation |
| --- | --- | --- |
| Round 1 | Six categories, generally `1–5` | Recognizable asset, no critical defect, cumulative regrade of every prior asset |
| Round 2 | Six categories, `1–4` | Every selected final-showcase category at least `3`, no critical structural mismatch |
| Round 3 | Six categories, `1–4` | Exact-commit independent visual pass plus holistic side/rear/top/bottom evidence |

The common categories are silhouette, proportions, identity, materials/color,
topology/attachments, and 3D coherence. A mean does not override a critical
error such as the wrong number of legs or a non-wearable “wearable” model.

## Regression strategy

### Cumulative asset gates

Each research cycle added its new asset to the prior accepted set. A cycle
could not pass merely because its new sample improved; earlier models also had
to retain their structural and visual gates. This exposed several cross-cycle
regressions, including Nian anatomy while Tomato was being improved and later
Centaur/Zombie depth issues after texture work.

Historical suite counts are commit-specific:

- Round 1 ended with `67/67` tests and seven independently passed assets;
- Round 2 ended with `139/139` cumulative tests and eight passed image assets;
- the Round 3 engine/benchmark commit passed `169/169`, while its overall asset
  gate stayed pending for two missing private GLBs;
- platform consolidation currently passes `193/193` tests.

### Test layers

The current suite locks the following behaviors:

| Layer | Representative test modules | Regression prevented |
| --- | --- | --- |
| Compiler/schema | `test_img2blockbench.py` | Invalid bones, references, UVs, nondeterministic output |
| Semantic geometry | `test_semantic_geometry.py` | Disconnected chains, invalid graphs, budget overruns |
| Semantic evidence | `test_semantic_evidence.py` | Camera errors, unstable rasterization, false keypoint metrics |
| Mesh reconstruction | `test_mesh_reconstruction.py` | Pancake fits, component merging/dropping, stale or tampered review evidence |
| Multiview/clip | `test_view_reconstruction.py` | Fake depth from duplicate/proxy views, invalid frames, dropped components |
| Texture projection | `test_reference_texture.py` | Background leakage, occlusion errors, noisy Minecraft output |
| Wearable export | `test_wearable_export.py` | Pilot baked into shell, invalid fit or attachment ownership |
| Generic review | `test_model_review.py` | Missing angles, path escape, source leakage, cross-model or stale manifests |
| Release | `test_platform_release.py` | Missing modules, nondeterministic ZIPs, broken links, workstation paths |
| Cycle gates | `test_cycle*`, `test_round2*`, `test_round3*` | Asset-specific anatomy, palette, provenance, and cumulative regressions |

### Safety regressions added during consolidation

The final integration found issues that asset screenshots alone would not
expose:

- external reference mode originally risked deleting an existing bundled
  reference; deletion was removed;
- a reference named `MODEL_ID.png` could alias the generated atlas; external
  locators now use an `external-reference/` namespace;
- building into the source directory could overwrite an authored spec or
  reference; all planned outputs are now collision-checked before writes;
- a localized review could become unrebuildable or stale; semantic and mesh
  manifests now bind canonical model content;
- semantic review paths could escape their evidence directory; portable
  relative-path checks now block this;
- semantic review could overwrite mesh review metadata; the two contracts use
  separate keys and artifact names;
- an incomplete review command once returned success; it now exits nonzero;
- optional commands produced raw import tracebacks; each now names the correct
  install extra;
- the compact archive could omit a newly imported module; packaging tests now
  require every runtime module in `py-modules`.

## Reading an evaluation correctly

Use this order:

1. Confirm source hashes, camera method, and whether each view is observed,
   proxy, or inferred.
2. Confirm strict schema and native audit success.
3. Check component and attachment integrity before aggregate similarity.
4. Check silhouette, depth, and extent metrics under their stated protocol.
5. Inspect texture observed/fallback attribution and palette policy.
6. Inspect every required render, including side, rear, top, and bottom.
7. Apply asset identity gates and record a separate visual verdict.
8. Verify artifact hashes and deterministic rebuild.

Never compare a fitted-camera IoU to a fixed-camera IoU as though one were a
direct improvement. Never treat a proxy view as independent observation.
Never use an aggregate score to excuse missing topology.

The cycle-specific thresholds and outcomes are recorded in
[the autoresearch cycle ledger](AUTORESEARCH_CYCLES.md).
