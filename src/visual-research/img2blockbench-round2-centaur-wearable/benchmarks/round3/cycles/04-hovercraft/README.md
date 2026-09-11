# Round 3, Cycle 04 — Meshy Minecraft hovercraft GLB

This cycle is scaffolded but **blocked**, not passed. The ignored private input
`round3-inputs/Meshy_AI_minecraft_hovercraft_0907011803_image-to-3d-texture.glb`
is not currently available to the repository process. No model quality result
is claimed without reading that exact mesh.

The runner invokes the same holistic Route 1 implementation as Cycle 03:
signed orthographic rays from front, back, left, right, top, and bottom;
six-connected component retention; adaptive native cuboid fitting;
mesh-albedo palette transfer; source-relative anti-pancake metrics; and a
seventh isometric source/fit/overlap image. It then strictly validates and
compiles the native Blockbench bundle. A successful automated run remains
`AWAITING_AGENT_VISUAL_REVIEW`; a separate read-only agent must inspect every
view before approval.

The first fully successful run locks the source SHA-256 and byte length in
`input-contract.json`. Later runs verify that lock before reconstruction, so a
different export cannot silently replace the graded input.

From the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/04-hovercraft/run-cycle.py
```

Exit code `2` is an input blocker, exit code `1` is a failed reconstruction or
verification, and exit code `0` means only that automated evidence is ready
for seven-view review. If the GLB axes are not canonical, set an explicit 4×4
`canonical_transform` in `cycle.json` and regenerate all views together.
