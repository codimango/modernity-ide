/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { ModernityLanguageModelProvider } from './modernityProvider';

export function activate(context: vscode.ExtensionContext): void {
	const provider = new ModernityLanguageModelProvider(context);

	// Register vendor modernity through languageModelChatProviders
	const registration = vscode.lm.registerLanguageModelChatProvider('modernity', provider);
	context.subscriptions.push(registration);

	// Optional: log activation so users know provider is ready
	const output = vscode.window.createOutputChannel('Modernity', { log: true });
	output.info(`Modernity model provider activated (session ${ (provider as any)._sessionId ?? 'unknown' })`);

	context.subscriptions.push(output);
}

export function deactivate(): void {
	// no-op
}
