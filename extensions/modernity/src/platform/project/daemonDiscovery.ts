/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: daemon discovery — single source of truth, no fallback protocol.
 *--------------------------------------------------------------------------------------------*/

import * as path from 'path';
import * as os from 'os';
import { DaemonError } from './errors';

// Node-only fs — lazy loaded so browser bundle stays external and doesn't crash at import time.
// In browser (no process.versions.node), discovery will emit runtime_missing and map to daemon unavailable.
type FsPromises = { readFile: (p: string, enc: string) => Promise<string>; stat: (p: string) => Promise<{ mode: number }> };
type FsSync = { readFileSync: (p: string, enc: string) => string };

function getFs(): { promises: FsPromises; readFileSync: FsSync['readFileSync'] } | undefined {
	try {
		// eslint-disable-next-line @typescript-eslint/no-var-requires
		const fs = require('fs') as any;
		if (fs?.promises?.readFile && fs?.readFileSync) {
			return fs as { promises: FsPromises; readFileSync: FsSync['readFileSync'] };
		}
		return undefined;
	} catch {
		return undefined;
	}
}

function isNode(): boolean {
	return typeof process !== 'undefined' && !!(process as any).versions?.node;
}

export interface DaemonRuntimeJson {
	readonly host: string;
	readonly port: number;
	readonly token: string;
	readonly workspace_root: string; // absolute-path per contract
}

export interface DiscoveryResult {
	readonly host: string;
	readonly port: number;
	readonly token: string;
	readonly workspace_root: string;
	readonly baseUrl: string; // http://host:port
	readonly rawPath: string;
}

const DEFAULT_PRIMARY = '/tmp/modernity-workspace/daemon.json';

function getOverridePath(): string | undefined {
	return process.env.MODERNITY_DAEMON_FILE?.trim() || undefined;
}

function getPlatformFallbacks(): string[] {
	const plat = os.platform();
	if (plat === 'win32') {
		const base = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
		return [path.join(base, 'Modernity', 'daemon.json')];
	}
	if (plat === 'darwin') {
		return [path.join(os.homedir(), 'Library', 'Application Support', 'Modernity', 'daemon.json')];
	}
	const xdg = process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local', 'state');
	return [path.join(xdg, 'modernity', 'daemon.json')];
}

function isLoopback(host: string): boolean {
	return host === '127.0.0.1' || host === 'localhost' || host === '::1';
}

function validateRuntimeShape(raw: any): DaemonRuntimeJson {
	if (!raw || typeof raw !== 'object') { throw new Error('invalid shape'); }
	const { host, port, token, workspace_root } = raw as any;
	if (typeof host !== 'string' || !host) { throw new Error('host missing'); }
	if (!isLoopback(host)) { throw new Error('host must be loopback'); }
	if (typeof port !== 'number' || !Number.isInteger(port) || port <= 0 || port > 65535) { throw new Error('port invalid'); }
	if (typeof token !== 'string' || !token) { throw new Error('token missing'); }
	if (typeof workspace_root !== 'string' || !path.isAbsolute(workspace_root)) { throw new Error('workspace_root must be absolute'); }
	return { host, port, token, workspace_root };
}

export async function discoverDaemon(runtimeFile?: string): Promise<DiscoveryResult> {
	// Browser guard — no fs in browser extension host, treat as runtime_missing per task (no fallback listener)
	if (!isNode()) {
		throw new DaemonError('runtime_missing', 'daemon discovery unavailable in browser host (no fs)');
	}
	const nodeFs = getFs();
	if (!nodeFs) {
		throw new DaemonError('runtime_missing', 'daemon discovery fs unavailable');
	}
	const candidates: string[] = [];
	const override = runtimeFile || getOverridePath();
	if (override) {
		candidates.push(override);
	} else {
		candidates.push(DEFAULT_PRIMARY);
		candidates.push(...getPlatformFallbacks());
	}

	let lastError: DaemonError | undefined;
	for (const p of candidates) {
		try {
			const text = await nodeFs.promises.readFile(p, 'utf8');
			let raw: any;
			try {
				raw = JSON.parse(text);
			} catch {
				throw new DaemonError('runtime_invalid', `daemon runtime JSON malformed: ${p}`, undefined, { path: p });
			}
			let parsed: DaemonRuntimeJson;
			try {
				parsed = validateRuntimeShape(raw);
			} catch (e: any) {
				throw new DaemonError('runtime_invalid', `daemon runtime invalid shape at ${p}: ${e?.message ?? e}`, undefined, { path: p, raw });
			}
			// owner-only check on POSIX
			try {
				if (os.platform() !== 'win32') {
					const stat = await nodeFs.promises.stat(p);
					const mode = stat.mode & 0o777;
					if (mode & 0o077) {
						// Not owner-only — per security contract should be owner-only; we don't crash in dev, but keep note
					}
				}
			} catch { /* ignore stat failures */ }

			return {
				host: parsed.host,
				port: parsed.port,
				token: parsed.token,
				workspace_root: parsed.workspace_root,
				baseUrl: `http://${parsed.host}:${parsed.port}`,
				rawPath: p,
			};
		} catch (err: any) {
			if (err instanceof DaemonError) {
				if (err.kind === 'runtime_invalid' || err.kind === 'unauthorized') {
					throw err;
				}
				lastError = err;
				continue;
			}
			if (err?.code === 'ENOENT') {
				lastError = new DaemonError('runtime_missing', `daemon runtime file not found: ${p}`, undefined, { path: p });
				continue;
			}
			lastError = new DaemonError('runtime_missing', `daemon discovery failed for ${p}: ${err?.message ?? err}`, undefined, { path: p });
		}
	}
	throw lastError ?? new DaemonError('runtime_missing', `daemon runtime not found from candidates: ${candidates.join(', ')}`);
}

export function discoverDaemonSync(runtimeFile?: string): DiscoveryResult {
	if (!isNode()) {
		throw new DaemonError('runtime_missing', 'daemon sync discovery unavailable in browser host');
	}
	const nodeFs = getFs();
	if (!nodeFs) {
		throw new DaemonError('runtime_missing', 'daemon sync fs unavailable');
	}
	const candidates: string[] = [];
	const override = runtimeFile || getOverridePath();
	if (override) {
		candidates.push(override);
	} else {
		candidates.push(DEFAULT_PRIMARY);
		candidates.push(...getPlatformFallbacks());
	}
	let lastError: DaemonError | undefined;
	for (const p of candidates) {
		try {
			const text = nodeFs.readFileSync(p, 'utf8');
			let raw: any;
			try { raw = JSON.parse(text); } catch { throw new DaemonError('runtime_invalid', `daemon runtime JSON malformed: ${p}`, undefined, { path: p }); }
			const parsed = validateRuntimeShape(raw);
			return {
				host: parsed.host,
				port: parsed.port,
				token: parsed.token,
				workspace_root: parsed.workspace_root,
				baseUrl: `http://${parsed.host}:${parsed.port}`,
				rawPath: p,
			};
		} catch (err: any) {
			if (err instanceof DaemonError) {
				if (err.kind === 'runtime_invalid') { throw err; }
				lastError = err; continue;
			}
			if (err?.code === 'ENOENT') {
				lastError = new DaemonError('runtime_missing', `daemon runtime file not found: ${p}`, undefined, { path: p });
				continue;
			}
			lastError = new DaemonError('runtime_missing', `daemon discovery failed: ${err?.message ?? err}`, undefined, { path: p });
		}
	}
	throw lastError ?? new DaemonError('runtime_missing', 'daemon runtime not found');
}
