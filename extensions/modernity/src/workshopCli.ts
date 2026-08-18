/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

/** Thin wrapper around `python -m services.workshop.cli`. */

export interface CliResult {
	readonly stdout: string;
	readonly stderr: string;
	readonly exitCode: number;
}

export class WorkshopCliError extends Error { }

/** Return the diagnostic emitted by a failed workshop command, when one is available. */
export function workshopCommandFailureDetail(
	result: CliResult,
	payload: Record<string, unknown>,
): string | undefined {
	if (result.exitCode === 0) {
		return undefined;
	}
	const payloadError = typeof payload.error === 'string' ? payload.error.trim() : '';
	return payloadError || result.stderr.trim() || undefined;
}

/**
 * Resolve the Modernity repository that holds `services.workshop`.
 *
 * The built-in extension lives at `<repo>/ide/modernity-ide/extensions/modernity`,
 * so the repository root is four levels up unless overridden.
 */
export function resolveRepositoryRoot(extensionPath: string): string {
	return process.env.MODERNITY_REPO || path.resolve(extensionPath, '..', '..', '..', '..');
}

export function resolvePython(repositoryRoot: string): string {
	const candidate = path.join(repositoryRoot, '.venv', 'bin', 'python');
	return fs.existsSync(candidate) ? candidate : 'python3';
}

/**
 * Run a workshop subcommand and return its output.
 *
 * `end` deliberately exits non-zero when the emitted task still has blockers,
 * yet it has already written the bundle. Callers therefore get the exit code
 * alongside stdout instead of an exception, and decide for themselves.
 */
export function runWorkshop(extensionPath: string, args: readonly string[]): Promise<CliResult> {
	const repositoryRoot = resolveRepositoryRoot(extensionPath);
	return new Promise<CliResult>((resolve, reject) => {
		execFile(
			resolvePython(repositoryRoot),
			['-m', 'services.workshop.cli', ...args],
			{ cwd: repositoryRoot, maxBuffer: 8 * 1024 * 1024 },
			(error, stdout, stderr) => {
				const exitCode = typeof error?.code === 'number' ? error.code : error ? 1 : 0;
				if (stdout.trim().length === 0 && exitCode !== 0) {
					reject(new WorkshopCliError(stderr.trim() || error?.message || 'workshop CLI failed'));
					return;
				}
				resolve({ stdout, stderr, exitCode });
			}
		);
	});
}

/** Parse the single JSON object a workshop subcommand prints on stdout. */
export function parseCliJson(stdout: string): Record<string, unknown> {
	const trimmed = stdout.trim();
	if (trimmed.length === 0) {
		throw new WorkshopCliError('workshop CLI produced no output');
	}
	try {
		const parsed: unknown = JSON.parse(trimmed);
		if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
			throw new Error('not an object');
		}
		return parsed as Record<string, unknown>;
	} catch {
		throw new WorkshopCliError(`workshop CLI returned unexpected output: ${trimmed.slice(0, 200)}`);
	}
}
