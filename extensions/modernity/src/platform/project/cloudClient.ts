/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: typed cancellable cloud client for /api/v1 project APIs.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { CloudApiError, CloudErrorKind, CloudErrorEnvelope, mapHttpStatusToCloudKind } from './errors';
import type { Checkout, Page, Project, RepositorySummary, CursorParams } from './models';

export interface CloudClientOptions {
	readonly baseUrl: string; // e.g. https://api.modernity.dev or http://127.0.0.1:8000
	readonly getAccessToken: () => Promise<string | undefined> | string | undefined;
	readonly fetchImpl?: typeof fetch;
	/** For tests — capture request snapshots without sending. */
	readonly onRequestSnapshot?: (snap: RequestSnapshot) => void;
}

export interface RequestSnapshot {
	readonly method: string;
	readonly url: string;
	readonly headers: Record<string, string>;
	readonly body?: string;
}

interface RawErrorBody {
	readonly code?: string;
	readonly message?: string;
	readonly request_id?: string;
	readonly retryable?: boolean;
	readonly details?: Record<string, unknown>;
}

const IDEMPOTENCY_KEY_RE = /^[\x20-\x7E]{16,128}$/;

function assertIdempotencyKey(key: string): void {
	if (!IDEMPOTENCY_KEY_RE.test(key)) {
		throw new Error(`Idempotency-Key must be 16-128 printable ASCII, got ${key.length} chars`);
	}
}

function stableErrorEnvelope(status: number, bodyText: string, headers: Headers): CloudErrorEnvelope {
	let parsed: RawErrorBody | undefined;
	try { parsed = JSON.parse(bodyText) as RawErrorBody; } catch { parsed = undefined; }
	const requestId = parsed?.request_id || headers.get('x-request-id') || headers.get('x-modernity-request-id') || 'unknown';
	return {
		code: parsed?.code || `http_${status}`,
		message: parsed?.message || bodyText.slice(0, 500) || `HTTP ${status}`,
		request_id: requestId,
		retryable: parsed?.retryable ?? (status === 429 || status >= 500),
		details: parsed?.details,
	};
}

export class ModernityCloudClient {
	private readonly baseUrl: string;
	private readonly getToken: () => Promise<string | undefined> | string | undefined;
	private readonly fetchImpl: typeof fetch;
	private readonly onSnapshot: ((s: RequestSnapshot) => void) | undefined;

	constructor(opts: CloudClientOptions) {
		this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
		this.getToken = opts.getAccessToken;
		this.fetchImpl = opts.fetchImpl ?? fetch;
		this.onSnapshot = opts.onRequestSnapshot;
	}

	private async authHeader(): Promise<string | undefined> {
		const tok = await this.getToken();
		if (!tok) { return undefined; }
		return `Bearer ${tok}`;
	}

	private buildUrl(path: string, params?: CursorParams): string {
		const u = new URL(`${this.baseUrl}${path}`);
		if (params?.limit !== undefined) { u.searchParams.set('limit', String(params.limit)); }
		if (params?.cursor) { u.searchParams.set('cursor', params.cursor); }
		if (params?.include_archived !== undefined) { u.searchParams.set('include_archived', String(params.include_archived)); }
		return u.toString();
	}

	private async request<T>(
		method: string,
		url: string,
		token: vscode.CancellationToken | undefined,
		init?: { body?: string; extraHeaders?: Record<string,string> }
	): Promise<T> {
		const auth = await this.authHeader();
		const headers: Record<string,string> = {
			'Accept': 'application/json',
			'Content-Type': 'application/json',
			...(init?.extraHeaders ?? {}),
		};
		if (auth) { headers['Authorization'] = auth; }

		const snap: RequestSnapshot = { method, url, headers: { ...headers }, body: init?.body };
		// scrub auth in snapshot copy? Keep shape but task says snapshots should include header presence; redact token value
		if (snap.headers['Authorization']) { snap.headers['Authorization'] = 'Bearer <redacted>'; }
		this.onSnapshot?.(snap);

		const controller = new AbortController();
		const disp = token?.onCancellationRequested(() => controller.abort());

		try {
			const resp = await this.fetchImpl(url, {
				method,
				headers: headers as any,
				body: init?.body,
				signal: controller.signal as any,
			});
			const text = await resp.text();
			if (!resp.ok) {
				const env = stableErrorEnvelope(resp.status, text, resp.headers as any);
				const kind = mapHttpStatusToCloudKind(resp.status);
				throw new CloudApiError(resp.status, kind as CloudErrorKind, env);
			}
			if (!text) { return {} as T; }
			return JSON.parse(text) as T;
		} catch (e: any) {
			if (e?.name === 'AbortError' || token?.isCancellationRequested) {
				throw new vscode.CancellationError();
			}
			if (e instanceof CloudApiError) { throw e; }
			// network failure -> offline
			const env: CloudErrorEnvelope = {
				code: 'offline',
				message: e?.message ?? 'Network failure',
				request_id: 'offline',
				retryable: true,
			};
			throw new CloudApiError(0, 'offline', env);
		} finally {
			disp?.dispose();
		}
	}

	async listProjects(params?: CursorParams, token?: vscode.CancellationToken): Promise<Page<Project>> {
		const url = this.buildUrl('/api/v1/projects', params);
		const raw = await this.request<{ items: Project[]; next_cursor: string | null }>('GET', url, token);
		return { items: raw.items ?? [], next_cursor: raw.next_cursor ?? null };
	}

	async getProject(projectId: string, token?: vscode.CancellationToken): Promise<{ project: Project }> {
		const url = `${this.baseUrl}/api/v1/projects/${encodeURIComponent(projectId)}`;
		return this.request('GET', url, token);
	}

	async getRepository(projectId: string, token?: vscode.CancellationToken): Promise<{ repository: RepositorySummary | null }> {
		const url = `${this.baseUrl}/api/v1/projects/${encodeURIComponent(projectId)}/repository`;
		return this.request('GET', url, token);
	}

	async listCheckouts(projectId: string, params?: CursorParams, token?: vscode.CancellationToken): Promise<Page<Checkout>> {
		const url = this.buildUrl(`/api/v1/projects/${encodeURIComponent(projectId)}/checkouts`, params);
		const raw = await this.request<{ items: Checkout[]; next_cursor: string | null }>('GET', url, token);
		return { items: raw.items ?? [], next_cursor: raw.next_cursor ?? null };
	}

	async createProject(body: Record<string, unknown>, idempotencyKey: string, token?: vscode.CancellationToken): Promise<{ project: Project }> {
		assertIdempotencyKey(idempotencyKey);
		const url = `${this.baseUrl}/api/v1/projects`;
		return this.request('POST', url, token, { body: JSON.stringify(body), extraHeaders: { 'Idempotency-Key': idempotencyKey } });
	}

	async patchProject(projectId: string, body: Record<string, unknown>, version: number, token?: vscode.CancellationToken): Promise<{ project: Project }> {
		const url = `${this.baseUrl}/api/v1/projects/${encodeURIComponent(projectId)}`;
		return this.request('PATCH', url, token, { body: JSON.stringify(body), extraHeaders: { 'If-Match': String(version) } });
	}

	/** Helper for tests to validate limit contract 1..100 default 50 client-side */
	static normalizeLimit(limit?: number): number {
		if (limit === undefined || limit === null) { return 50; }
		if (!Number.isInteger(limit) || limit < 1 || limit > 100) { throw new Error(`limit must be integer 1..100, got ${limit}`); }
		return limit;
	}
}
