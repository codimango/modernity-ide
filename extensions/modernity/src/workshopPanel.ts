/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as crypto from 'crypto';
import * as vscode from 'vscode';
import { WorkshopTaskBundle } from './workshopTask';

export const WORKSHOP_VIEW_ID = 'modernity.workshopSubmission';

/**
 * Side panel that shows the instruction and metadata of the task a workshop
 * session just produced, so the author can review exactly what would be
 * submitted before pushing it to Codimango.
 */
export class WorkshopSubmissionViewProvider implements vscode.WebviewViewProvider {

	private view: vscode.WebviewView | undefined;
	private bundle: WorkshopTaskBundle | undefined;
	private status: string | undefined;

	resolveWebviewView(webviewView: vscode.WebviewView): void {
		this.view = webviewView;
		webviewView.webview.options = { enableScripts: false };
		this.render();
	}

	/** Show a task bundle, revealing the view if it is hidden. */
	show(bundle: WorkshopTaskBundle): void {
		this.bundle = bundle;
		this.status = undefined;
		this.render();
		this.view?.show?.(true);
	}

	/** Replace the panel body with a progress or error message. */
	setStatus(message: string): void {
		this.status = message;
		this.render();
		this.view?.show?.(true);
	}

	private render(): void {
		if (this.view) {
			this.view.webview.html = this.html();
		}
	}

	private html(): string {
		const nonce = crypto.randomBytes(16).toString('base64');
		const csp = `default-src 'none'; style-src 'nonce-${nonce}';`;
		return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style nonce="${nonce}">${STYLES}</style>
</head>
<body>${this.body()}</body>
</html>`;
	}

	private body(): string {
		if (this.status) {
			return `<p class="empty">${escapeHtml(this.status)}</p>`;
		}
		const bundle = this.bundle;
		if (!bundle) {
			return '<p class="empty">Submit a workshop session to review the task it produced.</p>';
		}

		const verdict = bundle.submittable
			? '<div class="verdict ready">Ready to submit</div>'
			: `<div class="verdict blocked">${bundle.blockers.length} blocker${bundle.blockers.length === 1 ? '' : 's'}</div>`;
		const blockers = bundle.blockers.length > 0
			? `<ul class="blockers">${bundle.blockers.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
			: '';
		const provenance = bundle.provenance.generatedProse
			? 'Contains generated prose.'
			: `Verbatim from ${bundle.provenance.sources.length || 1} user-authored block(s).`;

		return `
<h1>${escapeHtml(bundle.taskName)}</h1>
${verdict}
${blockers}

<h2>Instruction <span class="count">${bundle.provenance.chars} chars</span></h2>
<pre>${escapeHtml(bundle.instruction)}</pre>
<p class="muted">${escapeHtml(provenance)}</p>

<h2>Commit</h2>
${facts([
			['Repository', bundle.repository, true],
			['Base', shortCommit(bundle.baseCommit), true],
			['Final', shortCommit(bundle.finalCommit), true],
			['Branch', bundle.defaultBranch, true],
			['Instance', bundle.instanceId, true]
		])}

<h2>Grading</h2>
${testList('fail_to_pass', bundle.failToPass)}
${testList('pass_to_pass', bundle.passToPass)}

<h2>Metadata</h2>
${facts([
			['Author', bundle.metadata.authorName, false],
			['Difficulty', bundle.metadata.difficulty, false],
			['Reward', bundle.metadata.rewardType, false],
			['Format', bundle.metadata.taskFormat, true],
			['Workstream', bundle.metadata.workstream, true],
			['Use Case', bundle.metadata.categoryUsecase, true],
			['Sub-Domain', bundle.metadata.categorySubdomain, true]
		])}

<h2>Environment</h2>
${facts([
			['Toolchain', bundle.environment.toolchainMode, true],
			['Minecraft', bundle.environment.minecraftVersion, false],
			['NeoForge', bundle.environment.neoforgeVersion, false],
			['Java', bundle.environment.javaVersion, false],
			['Base Image', bundle.environment.fromImage, true]
		])}

<h2>Location</h2>
<p class="path">${escapeHtml(bundle.directory)}</p>`;
	}
}

function shortCommit(value: string | undefined): string | undefined {
	return value ? value.slice(0, 10) : undefined;
}

function facts(rows: readonly [string, string | undefined, boolean][]): string {
	const cells = rows.map(([label, value, mono]) => {
		const rendered = value ? escapeHtml(value) : '&mdash;';
		return `<div><dt>${escapeHtml(label)}</dt><dd${mono ? ' class="mono"' : ''}>${rendered}</dd></div>`;
	});
	return `<dl>${cells.join('')}</dl>`;
}

function testList(title: string, tests: readonly string[]): string {
	const body = tests.length === 0
		? '<p class="muted">None recorded.</p>'
		: `<ul class="tests">${tests.map(test => `<li>${escapeHtml(test)}</li>`).join('')}</ul>`;
	return `<h3>${escapeHtml(title)} <span class="count">${tests.length}</span></h3>${body}`;
}

function escapeHtml(value: string): string {
	return value
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

const STYLES = `
body {
	font-family: var(--vscode-font-family);
	font-size: var(--vscode-font-size);
	color: var(--vscode-foreground);
	padding: 12px;
	line-height: 1.5;
}
h1 { font-size: 1em; margin: 0 0 10px; word-break: break-all; font-family: var(--vscode-editor-font-family); }
h2 {
	font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.05em;
	color: var(--vscode-descriptionForeground);
	margin: 18px 0 6px; display: flex; align-items: center; gap: 8px;
}
h3 { font-size: 0.82em; margin: 12px 0 4px; font-family: var(--vscode-editor-font-family); display: flex; gap: 8px; }
.count { margin-left: auto; color: var(--vscode-descriptionForeground); font-weight: normal; }
.empty, .muted { color: var(--vscode-descriptionForeground); font-size: 0.9em; }
.verdict { padding: 6px 10px; border-radius: 4px; font-weight: 600; font-size: 0.88em; }
.verdict.ready { background: var(--vscode-testing-iconPassed); color: var(--vscode-editor-background); }
.verdict.blocked {
	background: var(--vscode-inputValidation-warningBackground);
	border: 1px solid var(--vscode-inputValidation-warningBorder);
}
.blockers { margin: 8px 0 0; padding-left: 18px; font-size: 0.85em; color: var(--vscode-descriptionForeground); }
.blockers li { margin-bottom: 4px; }
pre {
	background: var(--vscode-textCodeBlock-background);
	border: 1px solid var(--vscode-panel-border);
	border-radius: 4px; padding: 10px; margin: 0;
	font-family: var(--vscode-editor-font-family); font-size: 0.86em;
	white-space: pre-wrap; word-break: break-word; max-height: 280px; overflow-y: auto;
}
dl { margin: 0; display: flex; flex-direction: column; gap: 5px; }
dl > div { display: flex; gap: 10px; align-items: baseline; }
dt { flex: 0 0 88px; color: var(--vscode-descriptionForeground); font-size: 0.85em; }
dd { margin: 0; flex: 1; min-width: 0; font-size: 0.88em; overflow-wrap: anywhere; }
dd.mono { font-family: var(--vscode-editor-font-family); font-size: 0.84em; }
.tests { margin: 0; padding-left: 18px; font-family: var(--vscode-editor-font-family); font-size: 0.84em; }
.path {
	font-family: var(--vscode-editor-font-family); font-size: 0.8em;
	color: var(--vscode-descriptionForeground); overflow-wrap: anywhere; margin: 0;
}
`;
