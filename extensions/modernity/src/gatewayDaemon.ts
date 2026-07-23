/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn, ChildProcess } from 'child_process';

let daemonProcess: ChildProcess | undefined;
let outputChannel: vscode.OutputChannel | undefined;

function getOutputChannel(): vscode.OutputChannel {
	if (!outputChannel) {
		outputChannel = vscode.window.createOutputChannel('Modernity Gateway');
	}
	return outputChannel;
}

function log(msg: string) {
	const ch = getOutputChannel();
	ch.appendLine(`[Modernity] ${msg}`);
	console.log(`[Modernity] ${msg}`);
}

function findRepoRoot(extensionPath: string): string | undefined {
	// extensionPath = .../ide/modernity-ide/extensions/modernity
	// repo root = .../modernity (3 levels up from extensionPath)
	const candidates: string[] = [];
	// From env var MODERNITY_REPO
	if (process.env.MODERNITY_REPO) {
		candidates.push(process.env.MODERNITY_REPO);
	}
	// Relative to extension path: ../../..
	candidates.push(path.resolve(extensionPath, '..', '..', '..', '..'));
	// One more fallback: from workspace? Use path.resolve
	candidates.push(path.resolve(extensionPath, '..', '..', '..', '..', '..'));

	for (const c of candidates) {
		try {
			if (fs.existsSync(path.join(c, 'tools', 'avocado-proxy', 'proxy_server.py'))) {
				return c;
			}
		} catch {}
	}
	return undefined;
}

function findProxyPath(extensionPath: string): string | undefined {
	const repoRoot = findRepoRoot(extensionPath);
	if (repoRoot) {
		const p = path.join(repoRoot, 'tools', 'avocado-proxy');
		if (fs.existsSync(path.join(p, 'proxy_server.py'))) {
			return p;
		}
	}
	// Fallback: check absolute path from original author machine path in README
	// and also check current working directory
	const extra = [
		'/Users/gleon01/AAI/modernity/tools/avocado-proxy',
		path.join(process.cwd(), 'tools', 'avocado-proxy'),
		path.join(process.cwd(), '..', '..', 'tools', 'avocado-proxy')
	];
	for (const c of extra) {
		if (fs.existsSync(path.join(c, 'proxy_server.py'))) {
			return c;
		}
	}
	return undefined;
}

async function isGatewayHealthy(url: string, timeoutMs = 2000): Promise<boolean> {
	try {
		const controller = new AbortController();
		const t = setTimeout(() => controller.abort(), timeoutMs);
		const res = await fetch(url, { signal: controller.signal as any });
		clearTimeout(t);
		return res.ok;
	} catch {
		return false;
	}
}

export async function ensureGatewayDaemon(context: vscode.ExtensionContext): Promise<void> {
	const configUrl = vscode.workspace.getConfiguration('modernity').get<string>('gatewayUrl')?.trim() || 'http://127.0.0.1:8000';
	const base = configUrl.replace(/\/+$/, '');
	const healthUrls = [
		`${base}/health`,
		`${base}/api/inference/v1/health`,
		`http://127.0.0.1:8000/health`,
		`http://127.0.0.1:8000/api/inference/v1/health`
	];

	// Check if already healthy
	for (const hu of healthUrls) {
		if (await isGatewayHealthy(hu)) {
			log(`Gateway already healthy at ${hu}`);
			return;
		}
	}

	// Not healthy – try to start daemon
	const extensionPath = context.extensionPath;
	const proxyPath = findProxyPath(extensionPath);
	if (!proxyPath) {
		log(`Could not find avocado-proxy at expected locations from ${extensionPath}. Tried repo root and fallbacks. Use MODERNITY_REPO env var to override. Gateway will not auto-start.`);
		return;
	}

	log(`Gateway not healthy, attempting to start daemon from ${proxyPath}`);

	// Determine python executable
	const pythonCandidates = [
		process.env.PYTHON_PATH,
		'python3',
		'python'
	].filter(Boolean) as string[];

	const args = ['-m', 'cli', '--host', '127.0.0.1', '--port', '8000'];

	// Try to spawn
	let spawned = false;
	for (const py of pythonCandidates) {
		try {
			log(`Spawning: ${py} ${args.join(' ')} in ${proxyPath}`);
			daemonProcess = spawn(py, args, {
				cwd: proxyPath,
				env: { ...process.env, PYTHONPATH: proxyPath, MODERNITY_GATEWAY_PORT: '8000' },
				stdio: ['ignore', 'pipe', 'pipe'],
				detached: false
			});

			if (!daemonProcess) { continue; }

			daemonProcess.stdout?.on('data', (d: Buffer) => {
				getOutputChannel().append(`[proxy stdout] ${d.toString()}`);
			});
			daemonProcess.stderr?.on('data', (d: Buffer) => {
				getOutputChannel().append(`[proxy stderr] ${d.toString()}`);
			});
			daemonProcess.on('error', (err) => {
				log(`Daemon spawn error: ${err.message}`);
			});
			daemonProcess.on('exit', (code) => {
				log(`Daemon exited with code ${code}`);
				daemonProcess = undefined;
			});

			context.subscriptions.push({
				dispose: () => {
					try {
						if (daemonProcess && !daemonProcess.killed) {
							daemonProcess.kill();
							log('Daemon stopped on extension deactivate');
						}
					} catch {}
				}
			} as any);

			spawned = true;
			break;
		} catch (e: any) {
			log(`Failed to spawn with ${py}: ${e?.message}`);
		}
	}

	if (!spawned) {
		log('Failed to spawn gateway daemon – no python executable succeeded');
		return;
	}

	// Wait a bit for health to become ready
	log('Waiting for gateway to become healthy...');
	for (let i = 0; i < 15; i++) {
		await new Promise(r => setTimeout(r, 1000));
		for (const hu of healthUrls) {
			if (await isGatewayHealthy(hu, 2000)) {
				log(`Gateway became healthy at ${hu} after ${i + 1}s`);
				return;
			}
		}
	}
	log('Gateway did not become healthy within timeout, check Output > Modernity Gateway');
}

export function stopGatewayDaemon() {
	try {
		if (daemonProcess && !daemonProcess.killed) {
			daemonProcess.kill();
			log('Daemon stopped');
		}
	} catch {}
	daemonProcess = undefined;
}
