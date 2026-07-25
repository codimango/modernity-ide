/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as net from 'net';
import { spawn, ChildProcess } from 'child_process';

const DAEMON_RUNTIME_FILE = '/tmp/modernity-workspace/daemon.json';
const WORKSPACE_ROOT = '/tmp/modernity-workspace';

let sandboxDaemonProcess: ChildProcess | undefined;
let channel: vscode.OutputChannel | undefined;

function log(msg: string): void {
	if (!channel) {
		channel = vscode.window.createOutputChannel('Modernity Sandbox');
	}
	channel.appendLine(`[Modernity] ${msg}`);
	console.log(`[Modernity] ${msg}`);
}

/**
 * Locate the aai-labs-modernity repo root (which holds the `services` package).
 * In dev builds the extension lives at <repo>/ide/modernity-ide/extensions/modernity.
 */
function findRepoRoot(extensionPath: string): string | undefined {
	const candidates: string[] = [];
	if (process.env.MODERNITY_REPO) {
		candidates.push(process.env.MODERNITY_REPO);
	}
	candidates.push(path.resolve(extensionPath, '..', '..', '..', '..'));
	candidates.push(path.resolve(extensionPath, '..', '..', '..', '..', '..'));
	for (const candidate of candidates) {
		try {
			if (fs.existsSync(path.join(candidate, 'services', 'tooling', 'mcp_server.py'))) {
				return candidate;
			}
		} catch {
			// ignore and try the next candidate
		}
	}
	return undefined;
}

/** Prefer the repo venv python (it has the daemon deps); fall back to system python. */
function resolvePython(repoRoot: string): string {
	const venvPython = path.join(repoRoot, '.venv', 'bin', 'python');
	if (fs.existsSync(venvPython)) {
		return venvPython;
	}
	return process.env.PYTHON_PATH || 'python3';
}

function readDaemonPort(): number | undefined {
	try {
		const data = JSON.parse(fs.readFileSync(DAEMON_RUNTIME_FILE, 'utf8'));
		return typeof data.port === 'number' ? data.port : undefined;
	} catch {
		return undefined;
	}
}

function isPortOpen(port: number, timeoutMs = 1500): Promise<boolean> {
	return new Promise<boolean>(resolve => {
		const socket = new net.Socket();
		const finish = (ok: boolean) => {
			socket.destroy();
			resolve(ok);
		};
		socket.setTimeout(timeoutMs);
		socket.once('connect', () => finish(true));
		socket.once('timeout', () => finish(false));
		socket.once('error', () => finish(false));
		socket.connect(port, '127.0.0.1');
	});
}

async function isDaemonHealthy(): Promise<boolean> {
	const port = readDaemonPort();
	if (!port) {
		return false;
	}
	return isPortOpen(port);
}

const delay = (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Ensure the local sandbox daemon is running. The tooling MCP server refuses to start
 * without a healthy daemon, so this must succeed before the MCP server is launched.
 */
export async function ensureSandboxDaemon(context: vscode.ExtensionContext): Promise<void> {
	if (await isDaemonHealthy()) {
		log('Sandbox daemon already running');
		return;
	}
	if (sandboxDaemonProcess) {
		// A start is already in flight; just wait for it to bind.
		for (let i = 0; i < 20; i++) {
			await delay(500);
			if (await isDaemonHealthy()) {
				return;
			}
		}
		return;
	}
	const repoRoot = findRepoRoot(context.extensionPath);
	if (!repoRoot) {
		log('Repo root not found (services/tooling/mcp_server.py missing). Set MODERNITY_REPO. Sandbox tools unavailable.');
		return;
	}
	const python = resolvePython(repoRoot);
	try {
		fs.mkdirSync(WORKSPACE_ROOT, { recursive: true });
	} catch {
		// ignore; the daemon will surface a clearer error if the path is unusable
	}
	const args = [
		'-m', 'services.sandbox.daemon', 'start',
		'--host', '127.0.0.1',
		'--port', '0',
		'--workspace-root', WORKSPACE_ROOT,
		'--runtime-file', DAEMON_RUNTIME_FILE
	];
	log(`Starting sandbox daemon: ${python} ${args.join(' ')} (cwd ${repoRoot})`);
	sandboxDaemonProcess = spawn(python, args, {
		cwd: repoRoot,
		env: { ...process.env, PYTHONPATH: repoRoot, SSL_CERT_FILE: process.env.SSL_CERT_FILE || '/etc/ssl/cert.pem' },
		stdio: ['ignore', 'pipe', 'pipe'],
		detached: false
	});
	sandboxDaemonProcess.stdout?.on('data', (data: Buffer) => log(`daemon: ${data.toString().trim()}`));
	sandboxDaemonProcess.stderr?.on('data', (data: Buffer) => log(`daemon(err): ${data.toString().trim()}`));
	sandboxDaemonProcess.on('exit', code => {
		log(`Sandbox daemon exited with code ${code}`);
		sandboxDaemonProcess = undefined;
	});
	for (let i = 0; i < 20; i++) {
		await delay(500);
		if (await isDaemonHealthy()) {
			log('Sandbox daemon is healthy');
			return;
		}
	}
	log('Sandbox daemon did not become healthy in time; sandbox tools may be unavailable.');
}

export function stopSandboxDaemon(): void {
	if (sandboxDaemonProcess) {
		try {
			sandboxDaemonProcess.kill();
		} catch {
			// ignore
		}
		sandboxDaemonProcess = undefined;
	}
}

/**
 * Register the Modernity tooling MCP server (compile / boot / create_sandbox / gametest /
 * rcon / ...) so the agent can drive the real sandbox instead of scaffolding by hand.
 */
export function registerSandboxMcpProvider(context: vscode.ExtensionContext): vscode.Disposable {
	return vscode.lm.registerMcpServerDefinitionProvider('modernity-sandbox', {
		provideMcpServerDefinitions: async () => {
			const repoRoot = findRepoRoot(context.extensionPath);
			if (!repoRoot) {
				log('Cannot provide sandbox MCP server: repo root not found (set MODERNITY_REPO).');
				return [];
			}
			// The MCP server requires a healthy daemon; make sure it is up before launch.
			await ensureSandboxDaemon(context);
			const python = resolvePython(repoRoot);
			const version = (context.extension.packageJSON as { version?: string }).version || '0.0.1';
			const server = new vscode.McpStdioServerDefinition(
				'Modernity Sandbox Tools',
				python,
				['-m', 'services.tooling.mcp_server'],
				{
					PYTHONPATH: repoRoot,
					SSL_CERT_FILE: process.env.SSL_CERT_FILE || '/etc/ssl/cert.pem',
					MODERNITY_DAEMON_FILE: DAEMON_RUNTIME_FILE
				},
				version
			);
			server.cwd = vscode.Uri.file(repoRoot);
			log(`Providing sandbox MCP server: ${python} -m services.tooling.mcp_server (cwd ${repoRoot})`);
			return [server];
		}
	});
}
