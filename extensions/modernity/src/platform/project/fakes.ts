/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: Fakes for backend, daemon, fs, IDE Git — business logic stays out of views.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { Checkout, LocalGitStatus, Project, RepositorySummary } from './models';
import type { IGitAdapter } from './gitContract';
import { GitAdapterError } from './errors';
import { ModernityCloudClient } from './cloudClient';
import { ModernityDaemonClient } from './daemonClient';

export class FakeCloudBackend {
	private projects = new Map<string, Project>();
	private repos = new Map<string, RepositorySummary | null>(); // projectId -> repo
	private checkouts = new Map<string, Checkout[]>(); // projectId -> checkouts
	private snapshots: any[] = [];

	setProjects(items: Project[]): void { this.projects = new Map(items.map(p => [p.id, p])); }
	setRepository(projectId: string, repo: RepositorySummary | null): void { this.repos.set(projectId, repo); }
	setCheckouts(projectId: string, items: Checkout[]): void { this.checkouts.set(projectId, items); }

	getSnapshotCount(): number { return this.snapshots.length; }
	getSnapshots(): any[] { return [...this.snapshots]; }

	makeClient(baseUrl = 'https://api.test.modernity.dev', getToken: () => string = () => 'fake-token'): ModernityCloudClient {
		const fakeFetch: typeof fetch = async (input: any, init?: any) => {
			const url = typeof input === 'string' ? input : input.url;
			const method = init?.method ?? 'GET';
			this.snapshots.push({ method, url, headers: init?.headers, body: init?.body, ts: new Date().toISOString() });
			const u = new URL(url);
			// route
			if (u.pathname === '/api/v1/projects' && method === 'GET') {
				const cursor = u.searchParams.get('cursor');
				const limit = Number(u.searchParams.get('limit') ?? '50');
				const all = [...this.projects.values()].sort((a,b)=>a.id.localeCompare(b.id));
				let start = 0;
				if (cursor) {
					const idx = all.findIndex(p=>p.id===cursor);
					start = idx>=0? idx+1 : 0;
				}
				const items = all.slice(start, start+limit);
				const next = all.length > start+limit ? all[start+limit-1].id : null;
				const body = JSON.stringify({ items, next_cursor: next });
				return new Response(body, { status: 200, headers: { 'content-type':'application/json' } });
			}
			const projMatch = u.pathname.match(/^\/api\/v1\/projects\/([^\/]+)$/);
			if (projMatch && method==='GET') {
				const id = decodeURIComponent(projMatch[1]);
				const p = this.projects.get(id);
				if (!p) { return new Response(JSON.stringify({ code:'not_found', message:'Project not found', request_id:'req-1', retryable:false }), { status:404 }); }
				return new Response(JSON.stringify({ project: p }), { status:200 });
			}
			const repoMatch = u.pathname.match(/^\/api\/v1\/projects\/([^\/]+)\/repository$/);
			if (repoMatch && method==='GET') {
				const id = decodeURIComponent(repoMatch[1]);
				const repo = this.repos.get(id) ?? null;
				return new Response(JSON.stringify({ repository: repo }), { status:200 });
			}
			const ckMatch = u.pathname.match(/^\/api\/v1\/projects\/([^\/]+)\/checkouts$/);
			if (ckMatch && method==='GET') {
				const id = decodeURIComponent(ckMatch[1]);
				const all = (this.checkouts.get(id) ?? []).sort((a,b)=>a.id.localeCompare(b.id));
				const cursor = u.searchParams.get('cursor');
				const limit = Number(u.searchParams.get('limit') ?? '50');
				let start=0;
				if (cursor) { const idx=all.findIndex(c=>c.id===cursor); start=idx>=0?idx+1:0; }
				const items = all.slice(start, start+limit);
				const next = all.length > start+limit ? all[start+limit-1].id : null;
				return new Response(JSON.stringify({ items, next_cursor: next }), { status:200 });
			}
			return new Response(JSON.stringify({ code:'not_found', message:'Not found', request_id:'req-miss', retryable:false }), { status:404 });
		};
		return new ModernityCloudClient({ baseUrl, getAccessToken: getToken, fetchImpl: fakeFetch as any });
	}
}

export class FakeDaemon {
	healthResult: { status:'ok', workspace_root:string } = { status:'ok', workspace_root:'/tmp/modernity-workspace' };
	shouldFailHealth = false;
	should401 = false;
	sandboxes = new Map<string, any>();
	snapshots: any[] = [];
	private token = 'fake-daemon-token';
	private port = 12345;

	setUnauthorized(v: boolean): void { this.should401 = v; }

	makeClient(): ModernityDaemonClient {
		const fakeFetch: typeof fetch = async (input: any, init?: any) => {
			const url = typeof input === 'string' ? input : input.url;
			const method = init?.method ?? 'GET';
			const headers = init?.headers ?? {};
			this.snapshots.push({ method, url, headers, body: init?.body, ts: new Date().toISOString() });
			if (this.should401) {
				return new Response(JSON.stringify({ error:{ type:'unauthorized', where:'daemon', message:'bad token', fix_hint:'restart', retryable:false, evidence:{} } }), { status:401 });
			}
			const u = new URL(url);
			if (u.pathname === '/v1/health') {
				if (this.shouldFailHealth) { throw new Error('ECONNREFUSED'); }
				return new Response(JSON.stringify(this.healthResult), { status:200 });
			}
			if (u.pathname === '/v1/sandboxes' && method==='POST') {
				const body = init?.body ? JSON.parse(init.body as string) : {};
				const id = body.sandbox_id || `sb-${Math.random().toString(16).slice(2)}`;
				const rec = { sandbox_id:id, workspace_path:`/tmp/modernity-workspace/${id}`, ...body, status:'created' };
				this.sandboxes.set(id, rec);
				return new Response(JSON.stringify(rec), { status:200 });
			}
			const statusMatch = u.pathname.match(/^\/v1\/sandboxes\/([^\/]+)\/status$/);
			if (statusMatch && method==='GET') {
				const id = decodeURIComponent(statusMatch[1]);
				const sb = this.sandboxes.get(id);
				if (!sb) { return new Response(JSON.stringify({ error:{ type:'not_found', where:'daemon', message:'sandbox not found', fix_hint:'create', retryable:false, evidence:{} } }), { status:404 }); }
				return new Response(JSON.stringify({ sandbox_id:id, phase:'ready', status:'ok' }), { status:200 });
			}
			const opMatch = u.pathname.match(/^\/v1\/sandboxes\/([^\/]+)\/([^\/]+)$/);
			if (opMatch && method==='POST') {
				const id = decodeURIComponent(opMatch[1]);
				const op = decodeURIComponent(opMatch[2]);
				if (!this.sandboxes.has(id)) { return new Response(JSON.stringify({ error:{ type:'not_found', where:'daemon', message:'missing', fix_hint:'', retryable:false, evidence:{} } }), { status:404 }); }
				return new Response(JSON.stringify({ sandbox_id:id, operation:op, result:'ok' }), { status:200 });
			}
			return new Response(JSON.stringify({ error:{ type:'unknown', where:'daemon', message:'unknown route', fix_hint:'', retryable:false, evidence:{} } }), { status:404 });
		};
		return new ModernityDaemonClient({
			discovery: async () => ({ host:'127.0.0.1', port:this.port, token:this.token, workspace_root:'/tmp/modernity-workspace', baseUrl:`http://127.0.0.1:${this.port}`, rawPath:'/tmp/modernity-workspace/daemon.json' }),
			fetchImpl: fakeFetch as any,
			onSnapshot: () => {}
		});
	}

	simulateRestart(): void {
		this.port = this.port+1; // token stays same but cache would be stale if client caches discovery with old port — our fake forces discoveryReset in test
	}
}

export class FakeFilesystem {
	private files = new Set<string>();
	addFile(p: string): void { this.files.add(p); }
	exists(uri: vscode.Uri): Promise<boolean> {
		// naive: check prefix
		return Promise.resolve([...this.files].some(f=>uri.fsPath.startsWith(f)));
	}
}

export class FakeGitAdapter implements IGitAdapter {
	private statuses = new Map<string, LocalGitStatus>();
	private calls: Array<{ operation:string; uri: string; ts: string }> = [];

	setStatus(uriPath: string, status: LocalGitStatus): void { this.statuses.set(uriPath, status); }
	getCalls(): Array<{ operation:string; uri:string }> { return [...this.calls]; }

	async status(uri: vscode.Uri): Promise<LocalGitStatus> {
		this.calls.push({ operation:'status', uri: uri.fsPath, ts: new Date().toISOString() });
		return this.statuses.get(uri.fsPath) ?? {
			branch: null, head_sha: null, upstream_sha: null,
			dirty: false, ahead: null, behind: null,
			detached: false, conflicted: false, unpublished: false,
			classification: 'missing'
		};
	}
	async init(uri: vscode.Uri): Promise<LocalGitStatus> {
		this.calls.push({ operation:'init', uri: uri.fsPath, ts: new Date().toISOString() });
		const s: LocalGitStatus = { branch:'main', head_sha:'a'.repeat(40), upstream_sha:null, dirty:false, ahead:null, behind:null, detached:false, conflicted:false, unpublished:true, classification:'unpublished' };
		this.statuses.set(uri.fsPath, s); return s;
	}
	async clone(_cloneUrl: string, targetParent: vscode.Uri, folderName: string): Promise<LocalGitStatus> {
		this.calls.push({ operation:'clone', uri: vscode.Uri.joinPath(targetParent, folderName).fsPath, ts: new Date().toISOString() });
		const dest = vscode.Uri.joinPath(targetParent, folderName);
		const s: LocalGitStatus = { branch:'main', head_sha:'b'.repeat(40), upstream_sha:'b'.repeat(40), dirty:false, ahead:null, behind:null, detached:false, conflicted:false, unpublished:false, classification:'clean' };
		this.statuses.set(dest.fsPath, s); return s;
	}
	async importExisting(uri: vscode.Uri): Promise<LocalGitStatus> {
		this.calls.push({ operation:'import', uri: uri.fsPath, ts: new Date().toISOString() });
		return this.status(uri);
	}
	async fetch(uri: vscode.Uri): Promise<LocalGitStatus> {
		this.calls.push({ operation:'fetch', uri: uri.fsPath, ts: new Date().toISOString() });
		return this.statuses.get(uri.fsPath) ?? { branch:'main', head_sha:'c'.repeat(40), upstream_sha:'c'.repeat(40), dirty:false, ahead:null, behind:1, detached:false, conflicted:false, unpublished:false, classification:'remote_ahead' };
	}
	async fastForwardPull(uri: vscode.Uri): Promise<LocalGitStatus> {
		this.calls.push({ operation:'fast_forward_pull', uri: uri.fsPath, ts: new Date().toISOString() });
		const cur = this.statuses.get(uri.fsPath);
		if (cur && (cur.classification==='diverged' || cur.classification==='local_ahead')) {
			throw new GitAdapterError('conflict', 'not fast-forwardable');
		}
		const s: LocalGitStatus = { branch:'main', head_sha:'d'.repeat(40), upstream_sha:'d'.repeat(40), dirty:false, ahead:null, behind:null, detached:false, conflicted:false, unpublished:false, classification:'clean' };
		this.statuses.set(uri.fsPath, s); return s;
	}
	async push(uri: vscode.Uri): Promise<LocalGitStatus> {
		this.calls.push({ operation:'push', uri: uri.fsPath, ts: new Date().toISOString() });
		return this.statuses.get(uri.fsPath) ?? { branch:'main', head_sha:'e'.repeat(40), upstream_sha:'e'.repeat(40), dirty:false, ahead:null, behind:null, detached:false, conflicted:false, unpublished:false, classification:'clean' };
	}
	async preview(uri: vscode.Uri, operation: string): Promise<{ safe:boolean; reason?:string }> {
		this.calls.push({ operation:`preview:${operation}`, uri: uri.fsPath, ts: new Date().toISOString() });
		return { safe:true };
	}
}
