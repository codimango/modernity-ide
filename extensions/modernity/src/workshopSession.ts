/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

/**
 * Tracks the workshop session the window is currently collecting for.
 *
 * A session brackets one feature: it pins a base commit at the start and is
 * harvested into a SWE-Bench task at the end. While it is active, the prompt
 * and any later clarifications accumulate in `instruction.md` inside the
 * session directory, which is what the emitted task ships verbatim.
 */

const WORKSHOP_DIR = path.join('.modernity', 'workshop');
const INSTRUCTION_FILE = 'instruction.md';
const ACTIVE_SESSION_KEY = 'modernity.workshop.activeSession';

export interface ActiveSession {
	readonly projectPath: string;
	readonly sessionId: string;
	readonly baseCommit: string;
}

export function sessionDirectory(session: ActiveSession): string {
	return path.join(session.projectPath, WORKSHOP_DIR, session.sessionId);
}

export function instructionPath(session: ActiveSession): string {
	return path.join(sessionDirectory(session), INSTRUCTION_FILE);
}

/**
 * Remembers the active session across window reloads.
 *
 * Scoped to the workspace, since a session belongs to one mod project.
 */
export class WorkshopSessionStore {

	constructor(private readonly memento: vscode.Memento) { }

	get(): ActiveSession | undefined {
		const stored = this.memento.get<ActiveSession>(ACTIVE_SESSION_KEY);
		if (!stored || !fs.existsSync(sessionDirectory(stored))) {
			return undefined;
		}
		return stored;
	}

	async set(session: ActiveSession): Promise<void> {
		await this.memento.update(ACTIVE_SESSION_KEY, session);
		await vscode.commands.executeCommand('setContext', 'modernity.workshop.sessionActive', true);
	}

	async clear(): Promise<void> {
		await this.memento.update(ACTIVE_SESSION_KEY, undefined);
		await vscode.commands.executeCommand('setContext', 'modernity.workshop.sessionActive', false);
	}

	/** Restore the context key after a reload so menus reflect reality. */
	async restoreContext(): Promise<void> {
		await vscode.commands.executeCommand(
			'setContext',
			'modernity.workshop.sessionActive',
			this.get() !== undefined
		);
	}
}

/**
 * Append user-authored text to the session instruction.
 *
 * Only text the user typed goes in here. `instruction.md` becomes the prompt
 * the evaluated model sees, so model-generated wording must never reach it.
 */
export function appendInstruction(session: ActiveSession, text: string): void {
	const trimmed = text.trim();
	if (trimmed.length === 0) {
		return;
	}
	const target = instructionPath(session);
	fs.mkdirSync(path.dirname(target), { recursive: true });
	const existing = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : '';
	const separator = existing.trim().length > 0 ? '\n\n' : '';
	fs.writeFileSync(target, `${existing.replace(/\s+$/, '')}${separator}${trimmed}\n`, 'utf8');
}

export function readInstruction(session: ActiveSession): string {
	const target = instructionPath(session);
	return fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : '';
}

/** Open the instruction in an editor so the user can refine it directly. */
export async function openInstruction(session: ActiveSession): Promise<void> {
	const target = instructionPath(session);
	fs.mkdirSync(path.dirname(target), { recursive: true });
	if (!fs.existsSync(target)) {
		fs.writeFileSync(target, '', 'utf8');
	}
	const document = await vscode.workspace.openTextDocument(vscode.Uri.file(target));
	await vscode.window.showTextDocument(document, { preview: false });
}
