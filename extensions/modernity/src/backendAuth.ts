/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

export const MODERNITY_BACKEND_ACCESS_TOKEN_KEY = 'modernity.backendAccessToken';

const SESSION_TOKEN_COMMAND = '_modernity.auth.getAccessToken';

/**
 * Return the bearer of the signed-in Modernity account, if there is a session.
 *
 * The workbench account owns refresh, so this is read per request rather than
 * cached: a 15-minute access token is renewed before it is handed over.
 */
export async function getModernitySessionAccessToken(): Promise<string | undefined> {
	try {
		const token = await vscode.commands.executeCommand<string | undefined>(SESSION_TOKEN_COMMAND);
		return typeof token === 'string' && token.trim() ? token.trim() : undefined;
	} catch {
		// A workbench without the account bridge falls back to an explicit token.
		return undefined;
	}
}

/** Return the configured backend bearer without exposing it outside the extension host. */
export async function getModernityBackendAccessToken(context: vscode.ExtensionContext): Promise<string | undefined> {
	const value = process.env.MODERNITY_ACCESS_TOKEN?.trim()
		|| await getModernitySessionAccessToken()
		|| await context.secrets.get(MODERNITY_BACKEND_ACCESS_TOKEN_KEY);
	return value?.trim() || undefined;
}
