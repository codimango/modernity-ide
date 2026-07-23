/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { ModernityLanguageModelProvider } from './modernityProvider';
import { ensureGatewayDaemon, stopGatewayDaemon } from './gatewayDaemon';

export async function activate(context: vscode.ExtensionContext) {
	const provider = new ModernityLanguageModelProvider(context);
	const disposable = vscode.lm.registerLanguageModelChatProvider('modernity', provider);
	context.subscriptions.push(disposable);
	context.subscriptions.push({ dispose: () => (provider as any)._onDidChange?.dispose?.() } as any);

	console.log('[Modernity] Language model chat provider registered for vendor "modernity"');

	// Auto-start the inference gateway daemon when the app starts.
	// Requirement: daemon should start automatically, not be stopped on launch.
	try {
		await ensureGatewayDaemon(context);
	} catch (e: any) {
		console.warn(`[Modernity] Failed to ensure gateway daemon: ${e?.message}`);
	}
}

export function deactivate() {
	try {
		stopGatewayDaemon();
	} catch {}
}
