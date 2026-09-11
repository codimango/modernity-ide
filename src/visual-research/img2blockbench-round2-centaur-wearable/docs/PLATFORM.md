# Platform architecture

img2blockbench has two deliberately separate layers.

## Agent workflow

The agent interprets the subject, chooses evidence, identifies semantic parts,
infers only defensible hidden geometry, authors bones and pivots, and judges
the final renders. This layer is responsible for resemblance and topology.

## Deterministic engine

The engine validates and compiles the chosen representation. Its stable
capabilities are:

- `semantic`: authored cuboids, bones, landmarks, collision, and materials;
- `mesh`: GLB/GLTF ray sampling, connected components, cuboid fitting, and
  six-direction source-relative evidence;
- `multiview`: calibrated visual-hull carving from independent masks or clip
  frames;
- `relief`: bounded single-view silhouette and thickness reconstruction;
- `threejs-import`: constrained Three.js cuboid scene conversion;
- `texture`: clean palette-bounded source projection;
- `wearable`: player shell and Bedrock attachable derivation;
- `review`: deterministic seven-angle, model-only visual evidence;
- `build`: native Blockbench, texture, Bedrock geometry, audit, manifest, and
  deterministic ZIP output.

The engine never treats a passing structural audit as proof of visual
similarity.

## Shared model contract

Every capability converges on schema-version-1 model JSON. The contract holds
reference provenance, subject uncertainty, a quality contract, texture policy,
materials, semantic bones, native cuboids, optional landmarks, and collision
dimensions. Generated model files are derived artifacts; corrections belong in
the source specification.

## Evidence hierarchy

1. A textured mesh gives the strongest automatic full-volume evidence.
2. Independent calibrated views constrain a visual hull but not hidden
   concavities or articulation.
3. Agent-authored semantics can model hidden structure, but every inference
   must be disclosed and inspected from all angles.
4. Single-image relief preserves source-facing detail and is explicitly 2.5D.

All full-volume reviews use front, back, left, right, top, bottom, and
isometric views. Hashes establish reproducibility, not resemblance; final
approval remains visual.

## Release boundary

The compact platform archive contains only:

- Python runtime modules;
- the agent skill and its two normative references;
- concise and detailed documentation;
- packaging metadata, license, and third-party notices;
- a machine-readable release manifest.

It excludes benchmark media, generated `.bbmodel` files, source meshes,
private inputs, the web demo, and the historical example corpus. Those remain
available in the local autoresearch tree for regression and provenance, but
their size and mixed licensing make them inappropriate production payloads.

## Compatibility

The 0.3 release retains the existing flat Python modules and CLI commands to
avoid breaking research scripts. A future package-layout migration can add
namespaced modules behind compatibility shims; it is not required for using
the consolidated engine.
