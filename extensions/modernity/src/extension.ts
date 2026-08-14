/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { ModernityLanguageModelProvider } from './modernityProvider';

// Node-only sandbox tooling is loaded lazily so the browser bundle never runs it.
let stopSandbox: (() => void) | undefined;

export function activate(context: vscode.ExtensionContext): void {
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
		// Workshop submission review reads emitted task bundles from disk and
		// shells out to the workshop CLI, so it is desktop-only too.
		void import('./workshopPanel').then(async panel => {
			const view = new panel.WorkshopSubmissionViewProvider();
			context.subscriptions.push(
				vscode.window.registerWebviewViewProvider(panel.WORKSHOP_VIEW_ID, view)
			);
			const submit = await import('./workshopSubmit');
			context.subscriptions.push(
				vscode.commands.registerCommand('modernity.workshop.submit', () =>
					submit.submitWorkshopSession(context.extensionPath, view)),
				vscode.commands.registerCommand('modernity.workshop.openTask', () =>
					submit.openWorkshopTask(view))
			);

			// `@modernity` slash commands drive the workshop pipeline. They do
			// setup only — none of them call a language model.
			const chat = await import('./chatCommands');
			context.subscriptions.push(...chat.registerChatCommands(context, view));
			output.info('Workshop submission review and chat commands registered');
		}).catch(err => output.warn(`Workshop panel unavailable: ${err?.message ?? err}`));
	}
	if (isNode) {
		void import('./sandboxTools').then(sandbox => {
			context.subscriptions.push(sandbox.registerSandboxMcpProvider(context));
			stopSandbox = sandbox.stopSandboxDaemon;
			return sandbox.ensureSandboxDaemon();
		}).catch(err => output.warn(`Sandbox tooling unavailable: ${err?.message ?? err}`));
	}
}

export function deactivate(): void {
	stopSandbox?.();
}
