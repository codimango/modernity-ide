---
name: modernity-tooling
description: Build, run, inspect, and visually verify Minecraft mods through the Modernity IDE sandbox tools. Use for compilation, GameTests, server boot, RCON, logs, captures, or sandbox lifecycle work in a Modernity project. Do not use for standalone image-to-Blockbench conversion; use img2blockbench for that.
---

# Modernity Tooling

Use the IDE-provided Modernity Sandbox Tools MCP server. The Modernity
extension starts the required daemon and registers the tools automatically;
do not start another daemon or scrape Gradle, RCON, or process output yourself.

## Workflow

1. Inspect the available Modernity tools and their current input schemas.
2. Call `create_sandbox` with the durable source project path. Keep the returned
   `sandbox_id` and use it for every later sandbox-scoped call. The default is
   get-or-create; request `force_new` only when isolation is actually needed.
3. Edit only the durable source project. Use `sandbox_diff` for a read-only
   preview when useful, stop a running server, and call `refresh_from_project`
   before compiling. Refresh never copies sandbox edits back to source.
4. Call `compile` before any test or runtime validation. Prefer its quick mode
   while iterating.
5. Run a focused `gametest` selector when one exists, then broaden validation
   only as needed.
6. Call `boot` with `wait: true` before RCON or visual checks. Use `status` and
   cursor-based `tail_logs` when diagnosing startup.
7. Use `rcon`, `rcon_batch`, `worldgen_probe`, and `capture_region` for runtime
   and visual evidence. A successful RCON response proves only command delivery.
8. Call `destroy` when the sandbox is no longer needed. Set
   `remove_workspace: true` only when deleting its generated workspace is
   explicitly intended.

New mods must be scaffolded through `create_sandbox` from the Modernity
template. Do not hand-author Gradle wrapper or build configuration files. The
platform target is Minecraft 26.2, NeoForge 26.2, Java 25, and Gradle 9.2.1.

When `$img2blockbench` produces a model bundle, place the selected model,
texture, and Bedrock/Java resources in the durable mod source, refresh the
sandbox, compile, and capture the result in-game before declaring the asset
finished.

## Result contract

Every tool returns a structured `ToolResult`:

```json
{
  "status": "ok | fail",
  "verified_by": ["compile"],
  "unverified": ["client_load", "gametest", "visual"],
  "error": null,
  "output": {}
}
```

- Trust only capabilities listed in `verified_by`. A successful compile does
  not prove GameTests, client loading, or visual quality.
- Read `output.evidence` and `error.fix_hint` on failure.
- `tail_logs` is a cursor: pass its returned `next_offset` into the next call.
- A non-waiting boot returns while the server is still starting; poll `status`.

Retry an unchanged operation at most twice, and only for a genuinely transient
`BOOT_TIMEOUT`, `RESOURCE_LIMIT_EXCEEDED`, `BACKEND_INTERNAL_ERROR`, or a
transient `PRECHECK_FAILED` such as a port conflict. Treat compile, dependency,
server-crash, verification, bad-parameter, unknown-tool, and registry failures
as actionable: inspect the evidence, fix the source or invocation, then rerun.
