/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as net from 'net';
import { spawn, ChildProcess } from 'child_process';

const DAEMON_RUNTIME_FILE = '/tmp/modernity-workspace/daemon.json';
const WORKSPACE_ROOT = '/tmp/modernity-workspace';

let sandboxDaemonProcess: ChildProcess | undefined;
let channel: vscode.OutputChannel | undefined;

const modernityCommand = process.env.MODERNITY_CLI || 'modernity';

function log(msg: string): void {
	if (!channel) {
		channel = vscode.window.createOutputChannel('Modernity Sandbox');
	}
	channel.appendLine(`[Modernity] ${msg}`);
	console.log(`[Modernity] ${msg}`);
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
export async function ensureSandboxDaemon(): Promise<void> {
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
	try {
		fs.mkdirSync(WORKSPACE_ROOT, { recursive: true });
	} catch {
		// ignore; the daemon will surface a clearer error if the path is unusable
	}
	const args = [
		'daemon', 'start',
		'--host', '127.0.0.1',
		'--port', '0',
		'--workspace-root', WORKSPACE_ROOT,
		'--runtime-file', DAEMON_RUNTIME_FILE
	];
	log(`Starting sandbox daemon: ${modernityCommand} ${args.join(' ')}`);
	sandboxDaemonProcess = spawn(modernityCommand, args, {
		env: { ...process.env, SSL_CERT_FILE: process.env.SSL_CERT_FILE || '/etc/ssl/cert.pem' },
		stdio: ['ignore', 'pipe', 'pipe'],
		detached: false
	});
	sandboxDaemonProcess.stdout?.on('data', (data: Buffer) => log(`daemon: ${data.toString().trim()}`));
	sandboxDaemonProcess.stderr?.on('data', (data: Buffer) => log(`daemon(err): ${data.toString().trim()}`));
	sandboxDaemonProcess.on('error', error => {
		log(`Failed to start sandbox daemon: ${error.message}`);
		sandboxDaemonProcess = undefined;
	});
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
			// The MCP server requires a healthy daemon; make sure it is up before launch.
			await ensureSandboxDaemon();
			const version = (context.extension.packageJSON as { version?: string }).version || '0.0.1';
			const server = new vscode.McpStdioServerDefinition(
				'Modernity Sandbox Tools',
				modernityCommand,
				['mcp', 'serve'],
				{
					MODERNITY_DAEMON_FILE: DAEMON_RUNTIME_FILE
				},
				version
			);
			log(`Providing sandbox MCP server: ${modernityCommand} mcp serve`);
			return [server];
		}
	});
}
