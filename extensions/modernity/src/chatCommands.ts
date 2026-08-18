/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { parseCliJson, runWorkshop, WorkshopCliError } from './workshopCli';
import { WorkshopSubmissionViewProvider } from './workshopPanel';
import { submitWorkshopSession } from './workshopSubmit';
import {
	ActiveSession,
	appendInstruction,
	openInstruction,
	readInstruction,
	WorkshopSessionStore
} from './workshopSession';

/**
 * The `@modernity` chat participant.
 *
 * These commands do setup, not inference: none of them call a language model.
 * They exist so the workshop pipeline is a couple of slash commands rather than
 * a sequence of terminal invocations.
 */

export const PARTICIPANT_ID = 'modernity.workshop';

function text(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined;
}

function activeProject(): string | undefined {
	return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

/** `/start-project` — scaffold a new mod repository to farm sessions from. */
async function startProject(
	extensionPath: string,
	stream: vscode.ChatResponseStream,
	prompt: string
): Promise<void> {
	const modName = prompt.trim() || await vscode.window.showInputBox({
		title: 'New Mod Project',
		prompt: 'Mod display name',
		placeHolder: 'Copper Lantern',
		ignoreFocusOut: true
	});
	if (!modName) {
		stream.markdown('Cancelled.');
		return;
	}
	const picked = await vscode.window.showOpenDialog({
		title: 'Where should the project be created?',
		openLabel: 'Create Here',
		canSelectFiles: false,
		canSelectFolders: true,
		canSelectMany: false
	});
	if (!picked || picked.length === 0) {
		stream.markdown('Cancelled.');
		return;
	}
	const slug = modName.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
	const destination = path.join(picked[0].fsPath, slug || 'mod');

	const owner = vscode.workspace
		.getConfiguration('modernity.workshop')
		.get<string>('githubOwner') || 'codimango';

	stream.progress(`Scaffolding ${modName} at ${destination}…`);
	const result = await runWorkshop(extensionPath, [
		'init-project', destination, '--mod-name', modName, '--github-owner', owner
	]);
	const created = parseCliJson(result.stdout);

	stream.markdown(
		`Created **${modName}**\n\n` +
		`- Path: \`${text(created.path) ?? destination}\`\n` +
		`- Mod id: \`${text(created.mod_id) ?? ''}\`\n` +
		`- Baseline commit: \`${(text(created.baseline_commit) ?? '').slice(0, 10)}\`\n` +
		`- Origin: \`${text(created.remote_url) ?? 'none'}\` (set, not pushed)\n\n` +
		'Open it, then run `/swe-session` to start collecting a task.'
	);
	stream.button({
		command: 'vscode.openFolder',
		title: vscode.l10n.t('Open Project'),
		arguments: [vscode.Uri.file(text(created.path) ?? destination), { forceNewWindow: false }]
	});
}

/** `/swe-session` — put this window into SWE-Bench collection mode. */
async function startSession(
	extensionPath: string,
	store: WorkshopSessionStore,
	view: WorkshopSubmissionViewProvider,
	stream: vscode.ChatResponseStream,
	prompt: string,
	model: string
): Promise<void> {
	const projectPath = activeProject();
	if (!projectPath) {
		stream.markdown('Open a mod project first, or run `/start-project` to create one.');
		return;
	}
	const existing = store.get();
	if (existing) {
		stream.markdown(
			`A session is already active for this project (\`${existing.sessionId}\`, base ` +
			`\`${existing.baseCommit.slice(0, 10)}\`). Use \`/note\` to add detail, or \`/submit\` to finish it.`
		);
		return;
	}

	stream.progress('Pinning the repository for a new session…');
	const result = await runWorkshop(extensionPath, ['begin', projectPath, '--model', model]);
	const begun = parseCliJson(result.stdout);
	const sessionId = text(begun.session_id);
	const baseCommit = text(begun.base_commit);
	if (!sessionId || !baseCommit) {
		throw new WorkshopCliError('workshop begin did not report a session');
	}

	const session: ActiveSession = { projectPath, sessionId, baseCommit, model };
	await store.set(session);
	if (prompt.trim().length > 0) {
		appendInstruction(session, prompt);
	}
	await openInstruction(session);
	view.setStatus(
		`Collecting session ${sessionId} from base ${baseCommit.slice(0, 10)}. ` +
		'Run /submit when the feature is finished.'
	);

	const dirty = text(begun.dirty_resolution);
	stream.markdown(
		`**SWE-Bench session started.**\n\n` +
		`- Session: \`${sessionId}\`\n` +
		`- Base commit: \`${baseCommit.slice(0, 10)}\`` +
		(dirty && dirty !== 'clean' ? ` (pre-existing work: ${dirty.replace(/_/g, ' ')})` : '') +
		`\n- Model: \`${model}\`\n\n` +
		'Carry on exactly as normal — streaming chat, the sandbox daemon and the visual ' +
		'capture tools are all unchanged. Everything you build from here becomes one task. ' +
		'`instruction.md` is open; it is the prompt the evaluated model will see, so keep it ' +
		'in your own words. Add to it with `/note`, and finish with `/submit`.'
	);
}

/** `/note` — append a user-authored clarification to the instruction. */
async function addNote(
	store: WorkshopSessionStore,
	stream: vscode.ChatResponseStream,
	prompt: string
): Promise<void> {
	const session = store.get();
	if (!session) {
		stream.markdown('No active session. Run `/swe-session` first.');
		return;
	}
	if (prompt.trim().length === 0) {
		stream.markdown('Give the note some text, for example `/note the lantern must be waterloggable`.');
		return;
	}
	appendInstruction(session, prompt);
	const chars = readInstruction(session).trim().length;
	stream.markdown(`Added to \`instruction.md\` (${chars} chars).`);
	stream.button({
		command: 'modernity.workshop.openInstruction',
		title: vscode.l10n.t('Open Instruction')
	});
}

/** `/submit` — harvest the session into a Codimango task and show the panel. */
async function submit(
	extensionPath: string,
	store: WorkshopSessionStore,
	view: WorkshopSubmissionViewProvider,
	stream: vscode.ChatResponseStream,
	model: string
): Promise<void> {
	const session = store.get();
	if (!session) {
		stream.markdown('No active session. Run `/swe-session` first.');
		return;
	}
	const instruction = readInstruction(session).trim();
	if (instruction.length === 0) {
		stream.markdown(
			'`instruction.md` is empty. Describe the task in your own words before submitting — ' +
			'it is the prompt the evaluated model sees.'
		);
		stream.button({ command: 'modernity.workshop.openInstruction', title: vscode.l10n.t('Open Instruction') });
		return;
	}
	if (session.model && session.model !== model) {
		// Whether the tests may ship depends on who wrote them, so a mid-session
		// model switch is worth surfacing rather than silently recording the
		// model the session started with.
		stream.markdown(
			`Note: this session was started on \`${session.model}\` but the picker is now ` +
			`\`${model}\`. The session model decides whether its tests can ship; rerun ` +
			'`/swe-session` if the recorded one is wrong.\n\n'
		);
	}
	const emitted = await submitWorkshopSession(
		extensionPath,
		view,
		{
			projectPath: session.projectPath,
			sessionId: session.sessionId,
			promptFile: path.join(
				session.projectPath, '.modernity', 'workshop', session.sessionId, 'instruction.md'
			)
		},
		stream
	);
	if (!emitted) {
		stream.markdown('Submission cancelled.');
		return;
	}
	await store.clear();
	stream.markdown(
		emitted.submittable
			? `**${emitted.taskName}** is ready to submit. See the Submission Review panel.`
			: `**${emitted.taskName}** was emitted with ${emitted.blockers.length} blocker(s). ` +
			'See the Submission Review panel for what is missing.'
	);
}

/** `/status` — what is being collected right now. */
function status(store: WorkshopSessionStore, stream: vscode.ChatResponseStream, model: string): void {
	const session = store.get();
	if (!session) {
		stream.markdown('No active session. `/swe-session` starts one, `/start-project` creates a project.');
		return;
	}
	const instruction = readInstruction(session).trim();
	stream.markdown(
		`Collecting session \`${session.sessionId}\`\n\n` +
		`- Project: \`${session.projectPath}\`\n` +
		`- Base commit: \`${session.baseCommit.slice(0, 10)}\`\n` +
		`- Session model: \`${session.model ?? 'unrecorded'}\`` +
		(session.model && session.model !== model ? ` (picker is now \`${model}\`)` : '') +
		'\n' +
		`- Instruction: ${instruction.length > 0 ? `${instruction.length} chars` : '_empty_'}\n`
	);
}

export function registerChatCommands(
	context: vscode.ExtensionContext,
	view: WorkshopSubmissionViewProvider
): vscode.Disposable[] {
	const store = new WorkshopSessionStore(context.workspaceState);
	void store.restoreContext();

	const participant = vscode.chat.createChatParticipant(PARTICIPANT_ID, async (request, _ctx, stream) => {
		try {
			switch (request.command) {
				case 'start-project':
					await startProject(context.extensionPath, stream, request.prompt);
					return;
				case 'swe-session':
					// `request.model` is whatever the user has selected in the chat
					// model picker for this request.
					await startSession(
						context.extensionPath, store, view, stream, request.prompt, request.model.id
					);
					return;
				case 'note':
					await addNote(store, stream, request.prompt);
					return;
				case 'submit':
					await submit(context.extensionPath, store, view, stream, request.model.id);
					return;
				case 'status':
					status(store, stream, request.model.id);
					return;
				default:
					stream.markdown(
						'Workshop commands:\n\n' +
						'- `/start-project` — scaffold a new mod repository\n' +
						'- `/swe-session` — start collecting a SWE-Bench task\n' +
						'- `/note` — add a clarification to `instruction.md`\n' +
						'- `/submit` — emit the task and open the review panel\n' +
						'- `/status` — show what is being collected\n'
					);
			}
		} catch (error) {
			const message = error instanceof WorkshopCliError || error instanceof Error
				? error.message
				: String(error);
			stream.markdown(`Failed: ${message}`);
		}
	});
	participant.iconPath = new vscode.ThemeIcon('package');

	const openInstructionCommand = vscode.commands.registerCommand(
		'modernity.workshop.openInstruction',
		async () => {
			const session = store.get();
			if (session) {
				await openInstruction(session);
			}
		}
	);

	return [participant, openInstructionCommand];
}

/** Exposed so the submit command can find the session the panel is showing. */
export function sessionInstructionExists(session: ActiveSession): boolean {
	return fs.existsSync(path.join(
		session.projectPath, '.modernity', 'workshop', session.sessionId, 'instruction.md'
	));
}
