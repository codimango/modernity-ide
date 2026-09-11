# Round 3, Cycle 03 — Minecraft-style off-road truck GLB

This cycle is scaffolded but **blocked**, not passed. The ignored private input
`round3-inputs/Minecraft-style off-road truck.glb` is not currently available
to the repository process. No model quality result is claimed without reading
that exact mesh.

The runner uses the holistic Route 1 pipeline: signed orthographic rays from
front, back, left, right, top, and bottom; six-connected component retention;
adaptive native cuboid fitting; mesh-derived bounded colors; source-relative
anti-pancake metrics; and a seventh isometric source/fit/overlap image. It then
strictly validates and compiles a `.bbmodel`, texture atlas, Bedrock geometry,
audit, manifest, and deterministic bundle. A successful automated run still
has status `AWAITING_AGENT_VISUAL_REVIEW`; only a separate read-only agent that
inspects all seven images may approve it.

On the first fully successful run, `input-contract.json` records the source
SHA-256 and byte length. Every later run checks that lock before reconstruction
and blocks on a mismatch. This prevents silently grading a replacement GLB.

From the repository root:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/round3/cycles/03-off-road-truck/run-cycle.py
```

Exit code `2` means the private input is missing, unreadable, or differs from
the locked hash. Exit code `1` means reconstruction or verification failed.
Exit code `0` means the artifacts and automated geometry gates are ready for
the required human/agent seven-view inspection; it does not mean visual PASS.

If the first seven-view manifest exposes a wrong source coordinate system,
record a deterministic 4×4 `canonical_transform` in `cycle.json` and rerun
before accepting the first hash lock and review. Do not rotate only the final
front render: all signed-axis evidence must share the same transform.
