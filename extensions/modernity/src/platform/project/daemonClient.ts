/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: typed local daemon bridge — matches services.sandbox.client.SandboxDaemonClient
 *       and daemon HTTP routes. No fallback listener.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { discoverDaemon, DiscoveryResult } from './daemonDiscovery';
import { DaemonError, DaemonErrorPayload } from './errors';

export interface DaemonHealth {
	readonly status: 'ok';
	readonly workspace_root: string;
}

export interface CreateSandboxRequest {
	readonly source_project_path?: string;
	readonly project_path?: string;
	readonly create_from_template?: boolean;
	readonly template_path?: string;
	readonly mod_id: string;
	readonly sandbox_id?: string | null;
	readonly backend?: string;
	readonly workspace_root?: string;
	readonly server_port?: number;
	readonly gradle_offline?: boolean;
	readonly rcon_port?: number;
	readonly rcon_password?: string;
	readonly trace_context?: unknown;
}

export interface DaemonRequestSnapshot {
	readonly method: string;
	readonly url: string;
	readonly headers: Record<string, string>;
	readonly body?: string;
}

export interface DaemonClientOptions {
	readonly runtimeFile?: string;
	readonly fetchImpl?: typeof fetch;
	readonly onSnapshot?: (s: DaemonRequestSnapshot) => void;
	readonly discovery?: () => Promise<DiscoveryResult>;
	readonly timeoutMs?: number;
}

function sanitizeDaemonSnapshot(headers: Record<string,string>): Record<string,string> {
	const copy = { ...headers };
	if (copy['Authorization']) { copy['Authorization'] = 'Bearer <redacted>'; }
	return copy;
}

function parseDaemonErrorPayload(text: string, _status: number): DaemonErrorPayload | undefined {
	try {
		const j = JSON.parse(text);
		if (j && typeof j === 'object' && j.error && typeof j.error === 'object') {
			const e = j.error as any;
			if (typeof e.type === 'string' && typeof e.message === 'string') {
				return {
					type: String(e.type),
					where: String(e.where ?? ''),
					message: String(e.message),
					fix_hint: String(e.fix_hint ?? ''),
					retryable: Boolean(e.retryable),
					evidence: (typeof e.evidence === 'object' && e.evidence !== null) ? e.evidence : {},
				};
			}
		}
	} catch { /* ignore */ }
	return undefined;
}

export class ModernityDaemonClient {
	private readonly fetchImpl: typeof fetch;
	private readonly onSnapshot?: (s: DaemonRequestSnapshot) => void;
	private readonly discovery: () => Promise<DiscoveryResult>;
	private cachedDiscovery?: DiscoveryResult;
	private readonly timeoutMs: number;

	constructor(opts: DaemonClientOptions = {}) {
		this.fetchImpl = opts.fetchImpl ?? fetch;
		this.onSnapshot = opts.onSnapshot;
		this.timeoutMs = opts.timeoutMs ?? 900_000;
		if (opts.discovery) {
			this.discovery = opts.discovery;
		} else {
			const rf = opts.runtimeFile;
			this.discovery = () => discoverDaemon(rf);
		}
	}

	private async ensureDiscovery(): Promise<DiscoveryResult> {
		if (this.cachedDiscovery) { return this.cachedDiscovery; }
		const d = await this.discovery();
		this.cachedDiscovery = d;
		return d;
	}

	/** Purge cache — used to simulate daemon restart / stale file. */
	discoveryReset(): void { this.cachedDiscovery = undefined; }

	private async request<T>(
		method: string,
		path: string,
		bodyObj: any | undefined,
		token: vscode.CancellationToken | undefined,
		timeoutMs?: number,
	): Promise<T> {
		const disc = await this.ensureDiscovery();
		const url = `${disc.baseUrl}${path}`;
		const body = bodyObj !== undefined ? JSON.stringify(bodyObj) : undefined;
		const headers: Record<string,string> = {
			'Authorization': `Bearer ${disc.token}`,
			'Accept': 'application/json',
		};
		if (body !== undefined) { headers['Content-Type'] = 'application/json'; }

		const snap: DaemonRequestSnapshot = {
			method,
			url,
			headers: sanitizeDaemonSnapshot(headers),
			body,
		};
		// snapshots must never leak absolute paths from cloud reqs — daemon is allowed to contain them, but we still check caller contract
		// Here allowed: local absolute paths may be used in daemon calls
		this.onSnapshot?.(snap);

		const controller = new AbortController();
		const abortDisp = token?.onCancellationRequested(() => controller.abort());
		let timeoutHandle: NodeJS.Timeout | undefined;
		if (timeoutMs !== undefined) {
			timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);
		}

		try {
			const resp = await this.fetchImpl(url, {
				method,
				headers: headers as any,
				body,
				signal: controller.signal as any,
			});
			const text = await resp.text();
			if (!resp.ok) {
				if (resp.status === 401) {
					throw new DaemonError('unauthorized', `daemon unauthorized at ${disc.rawPath} (token mismatch / stale file)`, undefined, { path: disc.rawPath, status: resp.status });
				}
				const payload = parseDaemonErrorPayload(text, resp.status);
				if (payload) {
					throw new DaemonError('backend', payload.message, payload, { path: disc.rawPath, status: resp.status });
				}
				throw new DaemonError('unavailable', `daemon http ${resp.status} at ${disc.rawPath}: ${text.slice(0, 500)}`, undefined, { path: disc.rawPath, status: resp.status, body: text.slice(0, 1000) });
			}
			if (!text) { return {} as T; }
			try {
				return JSON.parse(text) as T;
			} catch {
				throw new DaemonError('runtime_invalid', `daemon returned invalid JSON at ${disc.rawPath}`, undefined, { path: disc.rawPath, bodyPrefix: text.slice(0, 500) });
			}
		} catch (e: any) {
			if (e instanceof DaemonError) { throw e; }
			if (e?.name === 'AbortError') {
				if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
				throw new DaemonError('unavailable', `daemon request timeout/unavailable at ${url}: ${e.message}`, undefined, { url });
			}
			throw new DaemonError('unavailable', `daemon unavailable at ${disc.rawPath}: ${e?.message ?? e}`, undefined, { path: disc.rawPath, cause: e?.message });
		} finally {
			abortDisp?.dispose();
			if (timeoutHandle) { clearTimeout(timeoutHandle); }
		}
	}

	// ---- contract-matching methods ----

	async health(token?: vscode.CancellationToken): Promise<DaemonHealth> {
		return this.request<DaemonHealth>('GET', '/v1/health', undefined, token, 2000);
	}

	async createSandbox(req: CreateSandboxRequest, token?: vscode.CancellationToken): Promise<any> {
		return this.request('POST', '/v1/sandboxes', req, token, this.timeoutMs);
	}

	async getStatus(sandboxId: string, token?: vscode.CancellationToken): Promise<any> {
		return this.request('GET', `/v1/sandboxes/${encodeURIComponent(sandboxId)}/status`, undefined, token);
	}

	async postOperation(sandboxId: string, operation: string, body?: Record<string, unknown>, token?: vscode.CancellationToken): Promise<any> {
		return this.request('POST', `/v1/sandboxes/${encodeURIComponent(sandboxId)}/${encodeURIComponent(operation)}`, body ?? {}, token, this.timeoutMs);
	}

	// Compatibility shim with python client naming
	async create_sandbox(req: CreateSandboxRequest, token?: vscode.CancellationToken): Promise<any> {
		return this.createSandbox(req, token);
	}
	async get_status(sandboxId: string, token?: vscode.CancellationToken): Promise<any> {
		return this.getStatus(sandboxId, token);
	}
	async post_sandbox(sandboxId: string, operation: string, body?: Record<string, unknown>, token?: vscode.CancellationToken): Promise<any> {
		return this.postOperation(sandboxId, operation, body, token);
	}
}
