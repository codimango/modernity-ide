/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { ModernityLanguageModelProvider } from './modernityProvider';

// Node-only sandbox tooling is loaded lazily so the browser bundle never runs it.
let stopSandbox: (() => void) | undefined;
let episodeWorkflow: (vscode.Disposable & { isBenchmarkEpisodeSession(sessionId: string): boolean }) | undefined;

export interface IModernityExtensionApi {
	isBenchmarkEpisodeSession(sessionId: string): boolean;
}

export async function activate(context: vscode.ExtensionContext): Promise<IModernityExtensionApi> {
	const provider = new ModernityLanguageModelProvider(context);

	// Register vendor modernity through languageModelChatProviders
	const registration = vscode.lm.registerLanguageModelChatProvider('modernity', provider);
	context.subscriptions.push(registration);

	// Optional: log activation so users know provider is ready
	const output = vscode.window.createOutputChannel('Modernity', { log: true });
	output.info('Modernity model provider activated');

	context.subscriptions.push(output);

	// Expose the sandbox/tooling MCP server (compile / boot / create_sandbox / gametest /
	// rcon / ...) to the agent, and ensure the sandbox daemon it depends on is running.
	// Desktop (Node) only — the browser extension host has no child processes or sockets.
	const isNode = typeof process !== 'undefined' && !!process.versions?.node;
	if (isNode) {
		try {
			const episodes = await import('./episodeWorkflow');
			episodeWorkflow = episodes.registerEpisodeWorkflow(context, output);
			context.subscriptions.push(episodeWorkflow);
		} catch (err) {
			output.warn(`Benchmark episode workflow unavailable: ${err instanceof Error ? err.message : err}`);
		}
		void import('./sandboxTools').then(async sandbox => {
			const auth = await import('./backendAuth');
			context.subscriptions.push(sandbox.registerSandboxMcpProvider(context));
			context.subscriptions.push(sandbox.startSandboxDaemonTraceTokenRefresh(
				context,
				() => auth.getModernityBackendAccessToken(context),
			));
			context.subscriptions.push(vscode.commands.registerCommand(
				'modernity.restartSandboxDaemon',
				() => sandbox.restartSandboxDaemon(context),
			));
			stopSandbox = sandbox.stopSandboxDaemon;
			return sandbox.ensureSandboxDaemon(context);
		}).catch(err => output.warn(`Sandbox tooling unavailable: ${err?.message ?? err}`));
	}

	return {
		isBenchmarkEpisodeSession: sessionId => episodeWorkflow?.isBenchmarkEpisodeSession(sessionId) === true,
	};
}

export function deactivate(): void {
	stopSandbox?.();
}
