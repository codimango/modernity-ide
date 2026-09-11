# img2blockbench

img2blockbench converts reviewed image, clip, multiview, and 3D-mesh evidence
into native Minecraft-style Blockbench assets. The platform combines agentic
shape reasoning with a deterministic engine for validation, rendering,
texture synthesis, compilation, and packaging.

The output is real cuboid geometry—not a billboard or dense voxel soup—and
includes `.bbmodel`, Bedrock `geo.json`, a pixel texture atlas, audit metadata,
and a deterministic ZIP.

## Install

```bash
python3 -m pip install -e '.[all]'
img2blockbench --version
```

The base install needs Pillow. The `all` extra adds NumPy and trimesh for mesh,
multiview, and deterministic render evidence.

## Install the agent skill

The release archive also includes `skill/img2blockbench/`. Copy that complete
directory into your agent's skills directory when you want the agentic route
selection, visual reasoning, and approval workflow. Installing the Python
wheel exposes the deterministic CLI and modules only; it does not register the
agent skill automatically.

## Choose the right input

| Input | Capability | Result |
| --- | --- | --- |
| Reviewed semantic model spec | `semantic` | Detailed, riggable native model |
| Textured GLB or GLTF | `mesh` | Full-volume ray/voxel cuboid fit |
| Calibrated images or clip frames | `multiview` | Visual-hull cuboid volume |
| One image plus mask/depth | `relief` | Explicitly limited 2.5D reconstruction |
| Constrained Three.js scene | `threejs-import` | Native cuboid conversion |

For an arbitrary photograph or illustration, the most faithful path is either
a textured mesh or an agent-authored semantic model. Single-image relief is
useful for source-facing detail, but it does not infer hidden anatomy.

## Core workflow

Create and validate an agent-editable semantic specification:

```bash
img2blockbench probe reference.png --output reference.json
img2blockbench new reference.png \
  --id subject \
  --description "Minecraft-style subject" \
  --output model-spec.json
```

Have the agent replace the starter geometry, record identity features and
uncertainties, and set an honest cuboid budget. The starter is intentionally
not strict-valid until that authoring step is complete. Then validate it:

```bash
img2blockbench validate model-spec.json --strict
```

Render the same geometry from every important direction before approval:

```bash
img2blockbench review model-spec.json \
  --output review \
  --build-output build \
  --reference-policy external
```

This writes model-only front, back, left, right, top, bottom, and isometric
PNGs, an all-angle sheet, and a hash-bound review manifest. It is structural
evidence; an agent or human must still judge resemblance. The optional build
shown above packages that evidence and keeps the standalone reference file
out of the release bundle. To compile after a separate review pass, use:

```bash
img2blockbench build model-spec.json \
  --output build \
  --review-manifest review/model-review.json \
  --reference-policy external
```

This policy does not remove pixels deliberately transferred into an atlas or
embedded source texture. Use Minecraft-style texture baking when derived
textures also need to avoid literal photographic detail.

## Full-volume mesh reconstruction

```bash
img2blockbench from-mesh source.glb \
  --reference reference.png \
  --id subject \
  --description "Minecraft-style reconstruction" \
  --output model-spec.json \
  --evidence mesh-evidence.json \
  --build-output build \
  --reference-policy external
```

Mesh reconstruction casts rays on all three axes, records all six signed
directions, preserves retained 6-connected components, transfers bounded mesh
colors, and rejects both collapsed and excessively overfilled cuboid fits. Its
build contains hash-verified front/back/left/right/top/bottom/isometric review
evidence with workstation paths removed.

## Calibrated multiview and clips

```bash
img2blockbench from-views views.json \
  --id subject \
  --description "Calibrated multiview reconstruction" \
  --output model-spec.json \
  --evidence view-evidence.json \
  --build-output build
```

Clip ingestion extracts caller-selected timestamps; it never invents camera
calibration. The extraction command requires `ffmpeg` on `PATH`:

```bash
img2blockbench extract-clip-views clip.mp4 \
  --samples samples.json \
  --frames-dir frames \
  --output views.json
```

At least two independent calibrated axes are required to claim recovered
depth. Duplicate frames and synthetic proxy views are reported separately.

## Supporting capabilities

- Deterministic Minecraft-style reference texture baking with bounded palettes
- Semantic chain, branch, radial, ellipsoid, and attachment helpers
- Fixed-camera perspective evidence without post-render fitting
- Player-wearable shell and Bedrock attachable export
- Three.js import and preview generation
- Strict schema, provenance, collision, connectivity, and native-output audits

## Platform versus research archive

The installable platform is the code under `skill/img2blockbench/`. The
`benchmarks/`, `examples/`, and `demo/` trees preserve autoresearch evidence
and are intentionally excluded from the compact production release. From the
full autoresearch checkout, build that deterministic local release with:

```bash
python3 tools/build-platform-release.py --output dist
```

Start with [the platform architecture](docs/PLATFORM.md), then use the
[technical design](docs/TECHNICAL_DESIGN.md),
[cycle-by-cycle decision record](docs/AUTORESEARCH_CYCLES.md), and
[metrics and regression guide](docs/METRICS_AND_REGRESSIONS.md) for the full
engineering rationale. The [autoresearch index](docs/AUTORESEARCH.md) gives a
shorter overview. The full research checkout also retains the long-form
`docs/ENGINE_REFERENCE.md`.

## Current validation status

- Round 1: seven cumulative assets passed independent review.
- Round 2: eight difficult assets plus wearable and texture corrections passed.
- Round 3: the biblical angel and Zetatech Atlus passed exact-commit review;
  the generalized GLB pipeline passed its code/evidence gate.
- Round 3 truck and hovercraft asset runs remain pending because their private
  GLBs are not available inside the repository.

From the full autoresearch checkout, run the complete local suite:

```bash
PYTHONPATH=skill/img2blockbench/scripts \
  python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Honest limits

The deterministic engine does not decide what an ambiguous object is, invent
correct unseen anatomy from one picture, or replace visual review. Mesh and
calibrated multiview inputs provide the strongest geometric evidence. Organic
identity, topology, articulation, and inferred hidden surfaces remain agentic
modeling decisions and must be disclosed and reviewed.

MIT licensed. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
