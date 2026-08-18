/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { parseCliJson, runWorkshop, WorkshopCliError } from './workshopCli';
import { WorkshopSubmissionViewProvider } from './workshopPanel';
import { findLatestTaskDirectory, readTaskBundle, WorkshopTaskBundle, WorkshopTaskError } from './workshopTask';

const WORKSHOP_STATE_DIR = path.join('.modernity', 'workshop');
const SESSION_FILE = 'session.json';

interface SessionRecord {
	readonly sessionId: string;
	readonly baseCommit: string;
	readonly startedAt: string;
}

/** Where the caller already knows which session is being submitted. */
export interface SubmitContext {
	readonly projectPath: string;
	readonly sessionId: string;
	readonly promptFile: string;
}

interface SubmitAnswers {
	readonly categoryUsecase: string;
	readonly failToPass: string[];
	readonly passToPass: string[];
}

interface DerivedTests {
	readonly failToPass: string[];
	readonly passToPass: string[];
	readonly gradeable: boolean;
	readonly rejected: Record<string, string>;
}

function asList(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((x): x is string => typeof x === 'string') : [];
}

/**
 * Run the tests at base and at final to work out which ones the fix changes.
 *
 * Typing these lists by hand is guesswork: a test that already passes without
 * the fix proves nothing, and only running both sides can tell the difference.
 */
async function deriveTests(
	extensionPath: string,
	context: SubmitContext,
	stream: vscode.ChatResponseStream | undefined
): Promise<DerivedTests | undefined> {
	stream?.progress('Running the tests at base and final to derive fail_to_pass…');
	const result = await runWorkshop(extensionPath, [
		'test-matrix', context.projectPath, '--session-id', context.sessionId
	]);
	const payload = parseCliJson(result.stdout);
	return {
		failToPass: asList(payload.fail_to_pass),
		passToPass: asList(payload.pass_to_pass),
		gradeable: payload.gradeable === true,
		rejected: (payload.rejected ?? {}) as Record<string, string>
	};
}

/** Read every recorded workshop session for a project, newest first. */
function readSessions(projectPath: string): SessionRecord[] {
	const root = path.join(projectPath, WORKSHOP_STATE_DIR);
	let entries: fs.Dirent[];
	try {
		entries = fs.readdirSync(root, { withFileTypes: true });
	} catch {
		return [];
	}
	const sessions: SessionRecord[] = [];
	for (const entry of entries) {
		if (!entry.isDirectory()) {
			continue;
		}
		try {
			const raw = fs.readFileSync(path.join(root, entry.name, SESSION_FILE), 'utf8');
			const parsed = JSON.parse(raw) as { session_id?: string; base_commit?: string; started_at?: string };
			if (parsed.session_id && parsed.base_commit) {
				sessions.push({
					sessionId: parsed.session_id,
					baseCommit: parsed.base_commit,
					startedAt: parsed.started_at ?? ''
				});
			}
		} catch {
			// A partially written session directory is not a session; skip it.
		}
	}
	return sessions.sort((left, right) => right.startedAt.localeCompare(left.startedAt));
}

async function askSubmitAnswers(derived?: DerivedTests): Promise<SubmitAnswers | undefined> {
	const categoryUsecase = await vscode.window.showInputBox({
		title: 'Submit Workshop Session',
		prompt: 'Taxonomy use case (Layer 2). Run validate_task_toml.py --list for valid values.',
		placeHolder: 'extend_behavior',
		ignoreFocusOut: true
	});
	if (!categoryUsecase) {
		return undefined;
	}
	const failToPass = await vscode.window.showInputBox({
		title: 'Submit Workshop Session',
		prompt: derived
			? 'fail_to_pass, derived by running both sides. Edit only if you disagree.'
			: 'GameTests that fail before the fix and pass after, comma separated.',
		value: derived?.failToPass.join(', '),
		placeHolder: 'mymod:feature_works',
		ignoreFocusOut: true
	});
	if (!failToPass) {
		return undefined;
	}
	const passToPass = await vscode.window.showInputBox({
		title: 'Submit Workshop Session',
		prompt: derived
			? 'pass_to_pass, derived by running both sides.'
			: 'Regression GameTests that pass on both sides, comma separated. Optional.',
		value: derived?.passToPass.join(', '),
		placeHolder: 'mymod:mod_loads',
		ignoreFocusOut: true
	});
	const split = (value: string | undefined): string[] =>
		(value ?? '').split(',').map(item => item.trim()).filter(item => item.length > 0);
	return {
		categoryUsecase: categoryUsecase.trim(),
		failToPass: split(failToPass),
		passToPass: split(passToPass)
	};
}

function identity(): { unixname: string; authorName: string; authorEmail: string } {
	const config = vscode.workspace.getConfiguration('modernity.workshop');
	const unixname = config.get<string>('unixname') || os.userInfo().username;
	return {
		unixname,
		authorName: config.get<string>('authorName') || unixname,
		authorEmail: config.get<string>('authorEmail') || `${unixname}@meta.com`
	};
}

function outputRoot(projectPath: string): string {
	const configured = vscode.workspace.getConfiguration('modernity.workshop').get<string>('outputDirectory');
	if (configured && configured.trim().length > 0) {
		return configured.replace(/^~(?=$|\/)/, os.homedir());
	}
	return path.join(projectPath, '.modernity', 'workshop-tasks');
}

/** Resolve which session to submit, asking only when the caller does not know. */
async function resolveContext(context: SubmitContext | undefined): Promise<SubmitContext | undefined> {
	if (context) {
		return context;
	}
	const folder = vscode.workspace.workspaceFolders?.[0];
	if (!folder) {
		void vscode.window.showErrorMessage('Open a mod project before submitting a workshop session.');
		return undefined;
	}
	const projectPath = folder.uri.fsPath;
	const sessions = readSessions(projectPath);
	if (sessions.length === 0) {
		void vscode.window.showErrorMessage('No workshop session found. Run /swe-session first.');
		return undefined;
	}
	const session = sessions.length === 1
		? sessions[0]
		: await vscode.window.showQuickPick(
			sessions.map(item => ({
				label: item.sessionId,
				description: item.baseCommit.slice(0, 10),
				detail: item.startedAt,
				session: item
			})),
			{ title: 'Select Workshop Session', ignoreFocusOut: true }
		).then(picked => picked?.session);
	if (!session) {
		return undefined;
	}
	const recorded = path.join(projectPath, WORKSHOP_STATE_DIR, session.sessionId, 'instruction.md');
	if (fs.existsSync(recorded)) {
		return { projectPath, sessionId: session.sessionId, promptFile: recorded };
	}
	const picked = await vscode.window.showOpenDialog({
		title: 'Select the Session Prompt File',
		openLabel: 'Use as Instruction',
		canSelectMany: false,
		filters: { Markdown: ['md', 'txt'] }
	});
	if (!picked || picked.length === 0) {
		return undefined;
	}
	return { projectPath, sessionId: session.sessionId, promptFile: picked[0].fsPath };
}

/**
 * Run `workshop end` for a session and show the resulting task.
 *
 * The prompt for `fail_to_pass` is temporary: once the base-versus-final test
 * matrix lands, those lists are derived from real GameTest runs instead.
 */
export async function submitWorkshopSession(
	extensionPath: string,
	view: WorkshopSubmissionViewProvider,
	context?: SubmitContext,
	stream?: vscode.ChatResponseStream
): Promise<WorkshopTaskBundle | undefined> {
	const resolved = await resolveContext(context);
	if (!resolved) {
		return undefined;
	}

	let derived: DerivedTests | undefined;
	try {
		derived = await deriveTests(extensionPath, resolved, stream);
	} catch (error) {
		// The matrix needs Docker and the toolchain image. Losing it costs the
		// derivation, not the submission, so fall back to asking.
		const message = error instanceof Error ? error.message : String(error);
		stream?.markdown(`Could not derive the test lists (${message}); enter them by hand.\n\n`);
	}
	if (derived && !derived.gradeable) {
		const detail = Object.entries(derived.rejected)
			.map(([test, why]) => `- \`${test}\`: ${why}`)
			.join('\n');
		stream?.markdown(
			'**This session is not gradeable.** No test fails before the fix and passes after, ' +
			'so the reference solution cannot be told apart from doing nothing.\n\n' +
			(detail || '- no test changed behaviour between the base and final commits') +
			'\n\nAdd a test that exercises the change, then run `/submit` again.'
		);
		return undefined;
	}

	const answers = await askSubmitAnswers(derived);
	if (!answers) {
		return undefined;
	}

	const who = identity();
	const destination = outputRoot(resolved.projectPath);
	const args = [
		'end', resolved.projectPath,
		'--session-id', resolved.sessionId,
		'--output', destination,
		'--prompt-file', resolved.promptFile,
		'--unixname', who.unixname,
		'--author-name', who.authorName,
		'--author-email', who.authorEmail,
		'--category-usecase', answers.categoryUsecase,
		'--keep-directory',
		'--overwrite'
	];
	for (const test of answers.failToPass) {
		args.push('--fail-to-pass', test);
	}
	for (const test of answers.passToPass) {
		args.push('--pass-to-pass', test);
	}

	view.setStatus('Emitting task from the workshop session…');
	try {
		await runWorkshop(extensionPath, args);
	} catch (error) {
		const message = error instanceof WorkshopCliError ? error.message : String(error);
		view.setStatus(`Submission failed: ${message}`);
		void vscode.window.showErrorMessage(`Workshop submit failed: ${message}`);
		return undefined;
	}

	const emitted = findLatestTaskDirectory(destination);
	if (!emitted) {
		view.setStatus(`No emitted task was found under ${destination}.`);
		return undefined;
	}
	return revealTask(emitted, view);
}

/** Load an already-emitted task directory into the panel. */
export function revealTask(
	directory: string,
	view: WorkshopSubmissionViewProvider
): WorkshopTaskBundle | undefined {
	try {
		const bundle = readTaskBundle(directory);
		view.show(bundle);
		return bundle;
	} catch (error) {
		const message = error instanceof WorkshopTaskError ? error.message : String(error);
		view.setStatus(message);
		void vscode.window.showErrorMessage(message);
		return undefined;
	}
}

/** Prompt for an emitted task directory and show it without re-running the CLI. */
export async function openWorkshopTask(view: WorkshopSubmissionViewProvider): Promise<void> {
	const picked = await vscode.window.showOpenDialog({
		title: 'Open Emitted Workshop Task',
		openLabel: 'Review Task',
		canSelectFiles: false,
		canSelectFolders: true,
		canSelectMany: false
	});
	if (picked && picked.length > 0) {
		revealTask(picked[0].fsPath, view);
	}
}
