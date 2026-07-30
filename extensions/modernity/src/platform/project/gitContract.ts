/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: Safe Git contract from t19 — whitelist only, no force push, no merge/rebase,
 *       no auto-commit, no credential embedding.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { GitAdapterOptions, GitOperation, LocalGitStatus } from './models';

export interface IGitAdapter {
	/**
	 * Return LocalGitStatus for a VS Code URI root. Accepts cancellation, trusted identity,
	 * and explicit options. Never returns credentials.
	 */
	status(uri: vscode.Uri, token?: vscode.CancellationToken): Promise<LocalGitStatus>;

	/** init a non-repo folder as git repo (no credentials). */
	init(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus>;

	/** clone from HTTPS via credential provider; no credential embedding. */
	clone(cloneUrl: string, targetParent: vscode.Uri, folderName: string, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus>;

	/** import existing local folder as project checkout (verify identity). */
	importExisting(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus>;

	/** fetch remote without merging. */
	fetch(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus>;

	/** fast-forward-only pull; must fail (not merge) if not fast-forwardable. */
	fastForwardPull(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus>;

	/** push current branch; never force-push. */
	push(uri: vscode.Uri, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<LocalGitStatus>;

	/** Optional preview before action. */
	preview(uri: vscode.Uri, operation: GitOperation, options?: GitAdapterOptions, token?: vscode.CancellationToken): Promise<{ safe: boolean; reason?: string }>;
}

// Allowed operations per T19 — everything else is disallowed.
export const ALLOWED_OPERATIONS: ReadonlySet<GitOperation> = new Set<GitOperation>([
	'status',
	'init',
	'clone',
	'import',
	'fetch',
	'fast_forward_pull',
	'push',
]);

export const DISALLOWED_KEYWORDS = [
	'--force',
	'-f',
	'--no-ff',
	'--force-with-lease',
	'merge',
	'rebase',
	'commit',
	'--upload-pack',
	'--receive-pack',
] as const;

export function assertNoForce(options?: GitAdapterOptions): void {
	if (options?.force) {
		throw new Error('force push forbidden by Git adapter contract');
	}
}

export function assertSafeArgv(argv: string[]): void {
	const joined = argv.join(' ').toLowerCase();
	for (const kw of DISALLOWED_KEYWORDS) {
		if (kw === 'merge' || kw === 'rebase' || kw === 'commit') {
			// only ban as subcommand at position 1, not in branch name? keep simple: forbid exactly those commands
			if (argv[0] === kw || argv[1] === kw) {
				throw new Error(`Git subcommand forbidden by contract: ${kw}`);
			}
			continue;
		}
		if (joined.includes(kw)) {
			throw new Error(`Git argument forbidden by contract: ${kw}`);
		}
	}
}
