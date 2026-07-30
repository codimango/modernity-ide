# T23 – Modernity Project Platform Service – Code Ownership

**Task:** [T280743647](https://www.internalfb.com/tasks/T280743647) – Add Modernity project platform service, typed cloud/daemon clients, injected IDE Git adapter, and lifecycle.

This file identifies which code belongs to T23. If you need to resume work from any conversation, look here.

## File Map (all under `extensions/modernity/src/platform/project/`)

| File | Purpose | Key contract |
|------|---------|--------------|
| `models.ts` | Typed domain models | `Project` (UUID id, slug, mod_id, license, template_id, minecraft_version, neoforge_version, java_version, gradle_version, visibility private|public, default_branch, settings, lifecycle_status provisioning|awaiting_checkout|awaiting_push|active|error|archived, failure {code,message,retryable}|null, repository RepositorySummary|null, created_at RFC3339, updated_at, archived_at, last_opened_at, version), `RepositorySummary` (id, github_repository_id decimal-string, installation_id, owner, name, full_name, visibility, default_branch, html_url, clone_url, archived, status active|missing|unauthorized, **head_sha cached only from backend, never inferred from local Git**, head_observed_at, version), `Checkout` (id, project_id, machine {id,display_name}, **absolute_path only for current machine**, folder_basename, state present|missing|moved|detached, is_primary, manifest_version, last_seen_at, version), `Page<T>` {items,next_cursor}, `CursorParams` limit 1..100 default 50, `LocalGitStatus` {branch,head_sha,upstream_sha,dirty,ahead,behind,detached,conflicted,unpublished,classification clean|dirty|local_ahead|remote_ahead|diverged|detached|unpublished|missing|error} |
| `errors.ts` | Stable typed errors | `CloudErrorEnvelope` {code,message,request_id,retryable,details?}, `CloudApiError` kind mapping 401→signed_out, 403→unauthorized, 404→missing, 409→conflict, 422→validation, 429→rate_limited, 503/network→offline (preserves cache). `DaemonError` kind runtime_missing|runtime_invalid|unauthorized|unavailable|restarted|backend with payload {type,where,message,fix_hint,retryable,evidence}. `GitAdapterError` |
| `cloudClient.ts` | Cancellable typed cloud client | `GET /api/v1/projects?cursor&limit&include_archived=false → 200 {items:Project[],next_cursor}`, `GET /api/v1/projects/{id} → 200 {project:Project}`, `GET /api/v1/projects/{id}/repository → 200 {repository:RepositorySummary|null}`, `GET /api/v1/projects/{id}/checkouts?cursor&limit → 200 {items:Checkout[],next_cursor}`. Bearer auth via injected `getAccessToken()` (t11). Cursor validation, `If-Match: <version>`, `Idempotency-Key` 16-128 printable ASCII, identical replay returns stored response. Request snapshots with redacted token, never logs absolute paths. CancellationError on token cancel. |
| `daemonDiscovery.ts` | Single-source daemon discovery, no fallback | Reads owner-only runtime JSON `{host,port,token,workspace_root absolute-path}` from `MODERNITY_DAEMON_FILE` or `/tmp/modernity-workspace/daemon.json` (primary, T280149056) + platform fallbacks. Validates loopback-only `http://host:port`, workspace_root absolute. Missing/stale file, connection failure, 401, malformed JSON, daemon restart → typed DaemonError. Never falls back to second listener or workspace protocol. Browser-safe (fs lazy, throws runtime_missing in browser host). |
| `daemonClient.ts` | Typed local bridge matching `services.sandbox.client.SandboxDaemonClient` | `GET /v1/health → 200 {status:"ok",workspace_root}`, `POST /v1/sandboxes` → createSandbox, `GET /v1/sandboxes/{id}/status` → getStatus, `POST /v1/sandboxes/{id}/{operation}` → postOperation. Bearer token. 401→unauthorized (stale file), invalid JSON→runtime_invalid, connection fail→unavailable. Snapshots redacted, local absolute paths allowed only here, never copied to cloud/telemetry/logs. `discoveryReset()` for restart. Timeout 900s default, health 2s. |
| `gitContract.ts` | Safe contract from t19 | `ALLOWED_OPERATIONS` = status|init|clone|import|fetch|fast_forward_pull|push. `DISALLOWED_KEYWORDS` includes --force, merge, rebase, commit. `assertNoForce`, `assertSafeArgv`. No arbitrary subcommand, no force-push, no auto-commit, no merge/rebase/conflict resolution. |
| `gitAdapter.ts` | Injected IDE Git adapter via built-in Git extension | Uses `vscode.extensions.getExtension('vscode.git')`, credential provider only, never embeds credentials in argv, remote URLs, .git/config, settings, SecretStorage, telemetry, logs. Accepts `URI` roots, `CancellationToken`, trusted identity `{owner,name}`, explicit options. Returns `LocalGitStatus` + preview `{safe,reason}` + action results. Classifies clean/dirty/local_ahead/remote_ahead/diverged/detached/unpublished/missing/error. Fast-forward-only pull fails if not ff-able. |
| `projectService.ts` | `modernityProject` platform service | Owns `Map<id,Project>`, repositories, checkouts, lastUpdatedAt, cloudOffline, daemonAvailable, lastError. Events `onDidChangeProjects`, `onDidChangeDaemonAvailability`. `DisposableStore`-like (`SimpleDisposableStore`), `CancellationTokenSource` per refresh, coalesced refresh (queue flag, reuse promise), preserves last-known cloud state offline, maps daemon unavailability separate from cloud offline, disposes listeners/tasks immediately on window shutdown, injected `FlowCoordinator` `coordinateCheckout`. `handleDaemonRestart()` clears discovery cache. Registration helper `registerModernityProjectService`. |
| `fakes.ts` | Fakes for backend/daemon/fs/Git | `FakeCloudBackend` cursor pagination, snapshots; `FakeDaemon` health/401/unavailable/restart simulation; `FakeFilesystem`; `FakeGitAdapter` call tracking + status map + diverged blocking. Business logic stays out of views per task. |
| `index.ts` | Barrel | Public API |
| `tests/` | Contract & lifecycle tests (excluded from extension build) | `cloudClient.test.ts` request snapshots Bearer redaction, limit 1..100 default 50, 401→signed-out, offline, cursor. `daemonClient.test.ts` health snapshot, 401 unauthorized, unavailable, restart reset, no second listener fallback. `gitAdapter.test.ts` allowed ops whitelist, force-push forbidden, clone HTTPS-only, credential embedding rejection, ff safety diverged blocked, no credential leak. `projectService.test.ts` coalescing, offline preserves cache, cancellation, daemon unavailability distinct from cloud offline, daemon restart handling, immediate disposal. |

## Wiring

`src/extension.ts` now:
- imports `ModernityCloudClient`, `ModernityDaemonClient`, `VsCodeGitAdapter`, `ModernityProjectService`
- `getAccessToken()` reads `context.secrets.get('modernity.accessToken')` then config `modernity.accessToken` (t11 placeholder)
- creates clients, git adapter, service, registers in `context.subscriptions`
- `onDidChangeProjects` traced, `onDidChangeDaemonAvailability` info-logged
- commands `modernity.refreshProjects` (coalesced) + `modernity.cancelRefreshProjects` (cancellation)
- initial `service.refresh()` preserving cache offline, handling `CancellationError`
- `deactivate()` disposes `projectService` + `stopSandbox`

## Security invariants enforced
- No credentials in argv, remote URL, .git/config, SecretStorage, logs, telemetry
- No arbitrary Git subcommand, no --force, no merge/rebase/commit auto, no force push
- `head_sha` never inferred from local Git — always from backend cache
- Daemon absolute paths never copied to cloud requests
- Single daemon discovery path, no second listener fallback

## Prereqs (per task)
t11 (auth + machine registration), t13 (project APIs), t15 (repository binding), t19 (Git safety contract) — all referenced but not hard-dependent; service gracefully degrades to offline/signed-out.

## How to run
```
cd ide/modernity-ide
npm run gulp compile-extension:modernity
```

