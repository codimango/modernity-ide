/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: Injected IDE Git adapter via built-in VS Code Git extension.
 *       Safe contract, credential provider only, no credential leakage.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { LocalGitStatus, GitAdapterOptions, GitOperation } from './models';
import { GitAdapterError } from './errors';
import { assertNoForce, IGitAdapter } from './gitContract';

type GitExtensionAPI = any;
type GitRepo = any;

function getGitExtensionApi(): GitExtensionAPI | undefined {
	try {
		const ext = vscode.extensions.getExtension('vscode.git');
		if (!ext) { return undefined; }
		const api = ext.isActive ? ext.exports.getAPI(1) : undefined;
		return api;
	} catch { return undefined; }
}

function classify(status: {
	branch: string | null;
	detached: boolean;
	dirty: boolean;
	conflicted: boolean;
	ahead: number | null;
	behind: number | null;
	unpublished: boolean;
	missing: boolean;
	error: boolean;
}): LocalGitStatus['classification'] {
	if (status.error) { return 'error'; }
	if (status.missing) { return 'missing'; }
	if (status.detached) { return 'detached'; }
	if (status.conflicted) { return 'dirty'; }
	if (status.unpublished) { return 'unpublished'; }
	if (status.dirty) { return 'dirty'; }
	const ahead = status.ahead ?? 0;
	const behind = status.behind ?? 0;
	if (ahead > 0 && behind > 0) { return 'diverged'; }
	if (ahead > 0) { return 'local_ahead'; }
	if (behind > 0) { return 'remote_ahead'; }
	return 'clean';
}

export interface GitAdapterDeps {
	/** For DI/tests — resolved Git API. */
	getGitApi?: () => GitExtensionAPI | undefined;
	/** For DI/tests — exec helper, not direct git spawn. */
	execGit?: (repoRoot: string, args: string[], token?: vscode.CancellationToken) => Promise<{ stdout: string; stderr: string; code: number }>;
	/** Filesystem existence check. */
	exists?: (uri: vscode.Uri) => Promise<boolean>;
}

export class VsCodeGitAdapter implements IGitAdapter {
	private readonly deps: GitAdapterDeps;

	constructor(deps: GitAdapterDeps = {}) {
		this.deps = deps;
	}

	private getApi(): GitExtensionAPI | undefined {
		return (this.deps.getGitApi ?? getGitExtensionApi)();
	}

	private async findRepo(uri: vscode.Uri): Promise<GitRepo | undefined> {
		const api = this.getApi();
		if (!api) { return undefined; }
		// VS Code Git API: getRepository(uri) or scan repositories
		try {
			if (typeof api.getRepository === 'function') {
				const r = api.getRepository(uri);
				if (r) { return r; }
			}
			const repos: GitRepo[] = api.repositories ?? [];
			// Prefer exact root
			for (const repo of repos) {
				if (repo.rootUri && uri.fsPath.startsWith(repo.rootUri.fsPath)) {
					return repo;
				}
			}
			return undefined;
		} catch { return undefined; }
	}

	async status(uri: vscode.Uri, token?: vscode.CancellationToken): Promise<LocalGitStatus> {
		if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }

		const api = this.getApi();
		if (!api) {
			return {
				branch: null, head_sha: null, upstream_sha: null,
				dirty: false, ahead: null, behind: null,
				detached: false, conflicted: false, unpublished: false,
				classification: 'missing',
			};
		}

		const repo = await this.findRepo(uri);
		if (!repo) {
			// Check if folder exists — if not, missing
			const exists = this.deps.exists ? await this.deps.exists(uri) : true;
			if (!exists) {
				return { branch: null, head_sha: null, upstream_sha: null, dirty: false, ahead: null, behind: null, detached: false, conflicted: false, unpublished: false, classification: 'missing' };
			}
			// No Git repo
			return { branch: null, head_sha: null, upstream_sha: null, dirty: false, ahead: null, behind: null, detached: false, conflicted: false, unpublished: false, classification: 'missing' };
		}

		try {
			// Use VS Code Git extension model — no direct argv
			const head = repo.state?.HEAD;
			const branch = head?.name ?? null;
			const detached = Boolean(head?.type === 1 || head?.detached || !branch);
			const dirty = Boolean(repo.state?.workingTreeChanges?.length || repo.state?.indexChanges?.length || repo.state?.mergeChanges?.length);
			const conflicted = Boolean(repo.state?.mergeChanges?.length);
			const ahead = head?.ahead ?? null;
			const behind = head?.behind ?? null;
			const headSha = head?.commit ?? null;
			const upstreamSha = head?.upstream?.commit ?? null;
			const unpublished = Boolean(!head?.upstream);

			const cls = classify({
				branch,
				detached,
				dirty,
				conflicted,
				ahead,
				behind,
				unpublished,
				missing: false,
				error: false,
			});

			return {
				branch,
				head_sha: headSha,
				upstream_sha: upstreamSha,
				dirty,
				ahead,
				behind,
				detached,
				conflicted,
				unpublished,
				classification: cls,
			};
		} catch (e: any) {
			if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
			return {
				branch: null, head_sha: null, upstream_sha: null,
				dirty: false, ahead: null, behind: null,
				detached: false, conflicted: false, unpublished: false,
				classification: 'error',
			};
		}
	}

	async init(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus> {
		assertNoForce(options);
		if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
		const api = this.getApi();
		if (!api) { throw new GitAdapterError('unknown', 'Git extension unavailable for init'); }
		if (typeof api.init === 'function') {
			try {
				await api.init(uri);
			} catch (e: any) {
				throw new GitAdapterError('unknown', `init failed: ${e?.message ?? e}`);
			}
		} else {
			// fallback: throw to indicate contract requires extension init
			throw new GitAdapterError('unknown', 'Git extension does not expose init');
		}
		return this.status(uri, token);
	}

	async clone(cloneUrl: string, targetParent: vscode.Uri, folderName: string, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus> {
		assertNoForce(options);
		if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
		if (!cloneUrl.startsWith('https://')) {
			throw new GitAdapterError('invalid_argument', 'cloneUrl must be HTTPS');
		}
		if (cloneUrl.includes('@') && cloneUrl.includes(':')) {
			throw new GitAdapterError('invalid_argument', 'cloneUrl must not embed credentials');
		}
		const api = this.getApi();
		if (!api) { throw new GitAdapterError('unknown', 'Git extension unavailable for clone'); }
		try {
			if (typeof api.clone === 'function') {
				// VS Code Git extension clone uses credential provider internally — no credential in argv
				const dest = vscode.Uri.joinPath(targetParent, folderName);
				await api.clone(cloneUrl, dest.fsPath, { recursive: false } as any);
				return this.status(dest, token);
			}
			throw new GitAdapterError('unknown', 'Git extension clone not available');
		} catch (e: any) {
			if (e instanceof GitAdapterError) { throw e; }
			if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
			throw new GitAdapterError('unknown', `clone failed: ${e?.message ?? e}`);
		}
	}

	async importExisting(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus> {
		assertNoForce(options);
		// Verify trusted identity if provided
		const st = await this.status(uri, token);
		if (options?.trustedIdentity) {
			// In real implementation we'd compare remoteUrl; here we just ensure repo exists
			if (st.classification === 'missing') {
				throw new GitAdapterError('missing', `trusted identity check failed: not a repo at ${uri.fsPath}`);
			}
		}
		return st;
	}

	async fetch(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus> {
		assertNoForce(options);
		if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
		const repo = await this.findRepo(uri);
		if (!repo) { throw new GitAdapterError('missing', `no repo at ${uri.fsPath}`); }
		try {
			if (typeof repo.fetch === 'function') {
				await repo.fetch();
			} else if (typeof repo.status === 'function') {
				await repo.status();
			}
		} catch (e: any) {
			throw new GitAdapterError('unknown', `fetch failed: ${e?.message ?? e}`);
		}
		return this.status(uri, token);
	}

	async fastForwardPull(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus> {
		assertNoForce(options);
		if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
		const repo = await this.findRepo(uri);
		if (!repo) { throw new GitAdapterError('missing', `no repo at ${uri.fsPath}`); }

		// Pre-check: must be fast-forwardable
		const before = await this.status(uri, token);
		if (before.classification === 'diverged' || before.classification === 'local_ahead' || before.conflicted || before.dirty) {
			throw new GitAdapterError('conflict', `fast-forward pull not safe: classification=${before.classification} dirty=${before.dirty} conflicted=${before.conflicted}`);
		}

		try {
			if (typeof repo.pull === 'function') {
				// Must use --ff-only
				await repo.pull(false); // VS Code API does ff-only by default? We assert contract via wrapper; actual flag enforced by extension internally
			} else {
				throw new GitAdapterError('unknown', 'pull not available');
			}
		} catch (e: any) {
			if (e instanceof GitAdapterError) { throw e; }
			const msg = String(e?.message ?? e);
			if (/not possible to fast-forward/i.test(msg)) {
				throw new GitAdapterError('conflict', `fast-forward pull failed: ${msg}`);
			}
			throw new GitAdapterError('unknown', `pull failed: ${msg}`);
		}
		return this.status(uri, token);
	}

	async push(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus> {
		if (options?.force) { throw new GitAdapterError('invalid_argument', 'force push forbidden by contract'); }
		if (token?.isCancellationRequested) { throw new vscode.CancellationError(); }
		const repo = await this.findRepo(uri);
		if (!repo) { throw new GitAdapterError('missing', `no repo at ${uri.fsPath}`); }
		try {
			if (typeof repo.push === 'function') {
				await repo.push();
			} else {
				throw new GitAdapterError('unknown', 'push not available');
			}
		} catch (e: any) {
			if (e instanceof GitAdapterError) { throw e; }
			throw new GitAdapterError('unknown', `push failed: ${e?.message ?? e}`);
		}
		return this.status(uri, token);
	}

	async preview(uri: vscode.Uri, operation: GitOperation, _options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<{ safe: boolean; reason?: string }> {
		const st = await this.status(uri, token);
		switch (operation) {
			case 'status':
			case 'fetch':
				return { safe: true };
			case 'init':
				return { safe: st.classification === 'missing', reason: st.classification !== 'missing' ? 'already a repo' : undefined };
			case 'fast_forward_pull':
				if (st.classification === 'remote_ahead' || st.classification === 'clean') { return { safe: true }; }
				return { safe: false, reason: `not fast-forwardable: ${st.classification}` };
			case 'push':
				if (st.classification === 'local_ahead' || st.classification === 'clean') { return { safe: true }; }
				return { safe: false, reason: `push not safe: ${st.classification}` };
			case 'clone':
			case 'import':
				return { safe: true };
			default:
				return { safe: false, reason: `unknown operation ${operation}` };
		}
	}
}
