/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as net from 'net';
import { spawn, ChildProcess } from 'child_process';
import { getModernityBackendAccessToken } from './backendAuth';


const DAEMON_RUNTIME_FILE = '/tmp/modernity-workspace/daemon.json';
const WORKSPACE_ROOT = '/tmp/modernity-workspace';

let sandboxDaemonProcess: ChildProcess | undefined;
let sandboxDaemonTraceAccessToken: string | undefined;
let staleDaemonWarned = false;
let channel: vscode.OutputChannel | undefined;

const modernityCommand = process.env.MODERNITY_CLI || 'modernity';

function log(msg: string): void {
	if (!channel) {
		channel = vscode.window.createOutputChannel('Modernity Sandbox');
	}
	channel.appendLine(`[Modernity] ${msg}`);
	console.log(`[Modernity] ${msg}`);
}

interface IDaemonRuntime {
	readonly host: string;
	readonly port: number;
	readonly token: string;
}

function readDaemonRuntime(): IDaemonRuntime | undefined {
	try {
		const data = JSON.parse(fs.readFileSync(DAEMON_RUNTIME_FILE, 'utf8'));
		if (typeof data.port !== 'number') {
			return undefined;
		}
		return {
			host: typeof data.host === 'string' && data.host ? data.host : '127.0.0.1',
			port: data.port,
			token: typeof data.token === 'string' ? data.token : '',
		};
	} catch {
		return undefined;
	}
}

function readDaemonPort(): number | undefined {
	return readDaemonRuntime()?.port;
}

/** Result of daemon-owned project provisioning. */
export interface IProvisionedProject {
	readonly project_path: string;
	readonly sandbox_id: string;
	readonly commit_sha: string;
}

/**
 * Scaffold one durable mod project from the pinned NeoForge template.
 *
 * The daemon owns template personalization, the Modernity manifest, the baseline
 * commit, and the optional GitHub push, so the IDE never hand-authors build files.
 */
export async function provisionModernityProject(
	context: vscode.ExtensionContext,
	payload: Record<string, string>,
	timeoutMs = 10 * 60 * 1000,
): Promise<IProvisionedProject> {
	await ensureSandboxDaemon(context);
	const runtime = readDaemonRuntime();
	if (!runtime) {
		throw new Error(vscode.l10n.t('The Modernity sandbox daemon is not running, so a new project cannot be scaffolded.'));
	}
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const response = await fetch(`http://${runtime.host}:${runtime.port}/v1/projects/provision`, {
			method: 'POST',
			headers: {
				'Accept': 'application/json',
				'Authorization': `Bearer ${runtime.token}`,
				'Content-Type': 'application/json',
			},
			body: JSON.stringify(payload),
			signal: controller.signal,
		});
		const body = await response.json() as { error?: { message?: string } } & Partial<IProvisionedProject>;
		if (!response.ok) {
			throw new Error(body.error?.message || vscode.l10n.t('The sandbox daemon rejected the project setup.'));
		}
		if (typeof body.project_path !== 'string') {
			throw new Error(vscode.l10n.t('The sandbox daemon returned an unexpected project setup response.'));
		}
		return body as IProvisionedProject;
	} finally {
		clearTimeout(timer);
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
export async function ensureSandboxDaemon(context: vscode.ExtensionContext, traceAccessToken?: string): Promise<void> {
	const desiredTraceAccessToken = traceAccessToken ?? await getModernityBackendAccessToken(context);
	if (await isDaemonHealthy()) {
		if (sandboxDaemonProcess && sandboxDaemonTraceAccessToken !== desiredTraceAccessToken) {
			await restartOwnedSandboxDaemon(context, desiredTraceAccessToken);
			return;
		}
		log('Sandbox daemon already running');
		return;
	}
	if (sandboxDaemonProcess) {
		// A start is already in flight; just wait for it to bind.
		for (let i = 0; i < 20; i++) {
			await delay(500);
			if (await isDaemonHealthy()) {
				if (sandboxDaemonTraceAccessToken !== desiredTraceAccessToken) {
					await restartOwnedSandboxDaemon(context, desiredTraceAccessToken);
				}
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
	const daemonEnvironment: NodeJS.ProcessEnv = {
		...process.env,
		SSL_CERT_FILE: process.env.SSL_CERT_FILE || '/etc/ssl/cert.pem',
	};
	if (desiredTraceAccessToken) {
		daemonEnvironment.MODERNITY_TRACE_ACCESS_TOKEN = desiredTraceAccessToken;
	} else {
		delete daemonEnvironment.MODERNITY_TRACE_ACCESS_TOKEN;
	}
	const child = spawn(modernityCommand, args, {
		env: daemonEnvironment,
		stdio: ['ignore', 'pipe', 'pipe'],
		detached: false
	});
	sandboxDaemonProcess = child;
	sandboxDaemonTraceAccessToken = desiredTraceAccessToken;
	child.stdout?.on('data', (data: Buffer) => log(`daemon: ${data.toString().trim()}`));
	child.stderr?.on('data', (data: Buffer) => log(`daemon(err): ${data.toString().trim()}`));
	child.on('error', error => {
		log(`Failed to start sandbox daemon: ${error.message}`);
		if (sandboxDaemonProcess === child) {
			sandboxDaemonProcess = undefined;
			sandboxDaemonTraceAccessToken = undefined;
		}
	});
	child.on('exit', code => {
		log(`Sandbox daemon exited with code ${code}`);
		if (sandboxDaemonProcess === child) {
			sandboxDaemonProcess = undefined;
			sandboxDaemonTraceAccessToken = undefined;
		}
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

/**
 * Give the running daemon a refreshed trace bearer.
 *
 * Rotating the uploader in place keeps live sandboxes alive; a restart is the
 * fallback for an owned daemon too old to rotate.
 */
export async function refreshSandboxDaemonTraceAccessToken(context: vscode.ExtensionContext, accessToken: string): Promise<void> {
	const token = accessToken.trim();
	if (!token || sandboxDaemonTraceAccessToken === token) {
		return;
	}
	if (await isDaemonHealthy()) {
		if (await rotateDaemonTraceAccessToken(token)) {
			sandboxDaemonTraceAccessToken = token;
			return;
		}
		if (!sandboxDaemonProcess) {
			// A daemon that outlived the window that started it is adopted as healthy on
			// every reload, so it can never re-authenticate itself: say so out loud.
			log('A separately managed sandbox daemon could not rotate its trace bearer; it must be restarted to upload traces as the signed-in account');
			void warnAboutStaleDaemon(context);
			return;
		}
		await restartOwnedSandboxDaemon(context, token);
		return;
	}
	await ensureSandboxDaemon(context, token);
}

/** Prompt once per window when an adopted daemon cannot authenticate its uploads. */
async function warnAboutStaleDaemon(context: vscode.ExtensionContext): Promise<void> {
	if (staleDaemonWarned) {
		return;
	}
	staleDaemonWarned = true;
	const restart = vscode.l10n.t('Restart Sandbox Daemon');
	const chosen = await vscode.window.showWarningMessage(
		vscode.l10n.t('The running Modernity sandbox daemon predates this window and cannot refresh its credentials, so traces upload unauthenticated and stay out of your project. Restarting it stops any running sandbox.'),
		restart,
	);
	if (chosen === restart) {
		await restartSandboxDaemon(context);
	}
}

/**
 * Replace the running daemon with one owned by this window.
 *
 * A foreign daemon is asked to shut itself down through its own API rather than
 * signalled, so it can release sandboxes and leases first.
 */
export async function restartSandboxDaemon(context: vscode.ExtensionContext): Promise<void> {
	if (sandboxDaemonProcess) {
		await restartOwnedSandboxDaemon(context, await getModernityBackendAccessToken(context));
		return;
	}
	if (await isDaemonHealthy() && !(await shutdownForeignDaemon())) {
		void vscode.window.showErrorMessage(vscode.l10n.t('The Modernity sandbox daemon did not shut down. Stop it manually with "modernity daemon stop".'));
		return;
	}
	staleDaemonWarned = false;
	await ensureSandboxDaemon(context);
	if (await isDaemonHealthy()) {
		void vscode.window.showInformationMessage(vscode.l10n.t('The Modernity sandbox daemon restarted with your signed-in account.'));
	}
}

/** Ask a daemon this window does not own to exit; false when it stays up. */
async function shutdownForeignDaemon(): Promise<boolean> {
	const runtime = readDaemonRuntime();
	if (!runtime) {
		return true;
	}
	try {
		await fetch(`http://${runtime.host}:${runtime.port}/v1/shutdown`, {
			method: 'POST',
			headers: { 'Accept': 'application/json', 'Authorization': `Bearer ${runtime.token}` },
			signal: AbortSignal.timeout(15000),
		});
	} catch {
		// A daemon that drops the connection while exiting still counts as stopping.
	}
	for (let attempt = 0; attempt < 40; attempt++) {
		await delay(250);
		if (!(await isDaemonHealthy())) {
			return true;
		}
	}
	return false;
}

/** Ask the daemon to swap its uploader bearer; false when it cannot. */
async function rotateDaemonTraceAccessToken(accessToken: string): Promise<boolean> {
	const runtime = readDaemonRuntime();
	if (!runtime) {
		return false;
	}
	try {
		const response = await fetch(`http://${runtime.host}:${runtime.port}/v1/traces/access-token`, {
			method: 'POST',
			headers: {
				'Accept': 'application/json',
				'Authorization': `Bearer ${runtime.token}`,
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({ access_token: accessToken }),
			signal: AbortSignal.timeout(5000),
		});
		return response.ok;
	} catch {
		return false;
	}
}

/**
 * Keep the daemon's uploader bearer fresh for the life of the window.
 *
 * Modernity access tokens last 15 minutes, so a daemon started with one would
 * otherwise stop uploading traces mid-session.
 */
export function startSandboxDaemonTraceTokenRefresh(
	context: vscode.ExtensionContext,
	readAccessToken: () => Promise<string | undefined>,
	intervalMs = 10 * 60 * 1000,
): vscode.Disposable {
	let disposed = false;
	const push = async (): Promise<boolean> => {
		try {
			const token = await readAccessToken();
			if (!token || !(await isDaemonHealthy())) {
				return false;
			}
			await refreshSandboxDaemonTraceAccessToken(context, token);
			return true;
		} catch (error) {
			log(`Could not refresh the daemon trace bearer: ${error instanceof Error ? error.message : error}`);
			return false;
		}
	};
	// The account session and the daemon both come up during startup, so the first
	// push retries briefly instead of leaving the uploader unauthenticated for a cycle.
	const warmUp = async () => {
		for (const wait of [0, 5_000, 30_000]) {
			if (disposed) {
				return;
			}
			if (wait) {
				await delay(wait);
			}
			if (await push()) {
				return;
			}
		}
	};
	const timer = setInterval(() => void push(), intervalMs);
	void warmUp();
	return new vscode.Disposable(() => {
		disposed = true;
		clearInterval(timer);
	});
}

async function restartOwnedSandboxDaemon(context: vscode.ExtensionContext, traceAccessToken: string | undefined): Promise<void> {
	const child = sandboxDaemonProcess;
	if (!child) {
		return;
	}
	try {
		child.kill();
	} catch {
		// The exit listener will reconcile a process that already terminated.
	}
	for (let i = 0; i < 20; i++) {
		await delay(250);
		if (!(await isDaemonHealthy())) {
			break;
		}
	}
	if (sandboxDaemonProcess === child) {
		sandboxDaemonProcess = undefined;
		sandboxDaemonTraceAccessToken = undefined;
	}
	await ensureSandboxDaemon(context, traceAccessToken);
}

export function stopSandboxDaemon(): void {
	if (sandboxDaemonProcess) {
		try {
			sandboxDaemonProcess.kill();
		} catch {
			// ignore
		}
		sandboxDaemonProcess = undefined;
		sandboxDaemonTraceAccessToken = undefined;
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
			await ensureSandboxDaemon(context);
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
