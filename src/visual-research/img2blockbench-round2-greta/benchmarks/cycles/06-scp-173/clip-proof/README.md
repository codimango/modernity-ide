# Real clip route proof

This directory contains a tiny, repository-owned two-view turntable clip and
the deterministic artifacts produced by `extract-clip-views` followed by
`from-views`. Both frames are labeled `observed`; camera timestamps and yaw
angles are supplied explicitly rather than inferred.

Regenerate with:

```bash
PYTHONPATH=skill/img2blockbench/scripts python3 benchmarks/cycles/06-scp-173/clip-proof/prepare-proof.py
```

The synthetic rectangle is intentionally simple: this artifact validates the
real ffmpeg and calibrated reconstruction path, not semantic image quality.
