# IDE trace-analysis dataset

This directory contains a snapshot of locally retained, closed Codex and Claude Code traces for quick analysis experiments in Modernity IDE.

## Archive

- `archives/codex-claude-completed-traces-2026-09-14.zip.part-*`
- Uncompressed payload: 10,724,900,468 bytes across 1,735 artifacts
- Compressed size: 4,909,465,345 bytes
- SHA-256: `d14b2272389972d49571b336768f9c8a0915dfc4c2ad29e365d46f5fbbefd4ce`

The ZIP is split into 400 MiB Git LFS objects to keep individual transfers reliable. Run `git lfs pull` after checking out this branch, then reconstruct and verify it from the `archives` directory:

```sh
shasum -a 256 -c codex-claude-completed-traces-2026-09-14.zip.parts.sha256
cat codex-claude-completed-traces-2026-09-14.zip.part-* > codex-claude-completed-traces-2026-09-14.zip
shasum -a 256 -c codex-claude-completed-traces-2026-09-14.zip.sha256
```

The reconstructed ZIP includes its own README, source-path manifests, active-session exclusions, and per-artifact SHA-256 checksums.

The traces can contain sensitive prompts, source code, command output, and local paths. Keep the dataset within approved experimentation environments and avoid copying trace contents into logs or public artifacts.
