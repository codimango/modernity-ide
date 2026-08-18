/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as crypto from 'crypto';
import * as vscode from 'vscode';
import { runWorkshop } from './workshopCli';

export const WORKSHOP_HISTORY_VIEW_ID = 'modernity.workshopHistory';

/** One session's outcome, as `services.workshop.ledger` records it. */
export interface LedgerEntry {
	readonly session_id: string;
	readonly base_commit: string;
	readonly final_commit: string;
	readonly task: string;
	readonly output: string;
	readonly archive: string;
	readonly route: string;
	readonly fail_to_pass: readonly string[];
	readonly pass_to_pass: readonly string[];
	readonly submittable: boolean;
	readonly recorded_at: string;
	readonly routed_at: string;
	readonly profile: { readonly runs?: readonly ModelRun[] };
}

export interface ModelRun {
	readonly agent: string;
	readonly model: string;
	readonly trials: number;
	readonly passed: number;
	readonly pass_rate: number;
	readonly discounted: boolean;
	readonly discount_reason: string;
}

export interface HistoryNode {
	readonly sha: string;
	readonly short: string;
	readonly subject: string;
	readonly author: string;
	readonly date: string;
	readonly label: string;
	readonly hasTask: boolean;
	readonly entry: LedgerEntry | null;
}

export interface History {
	readonly nodes: readonly HistoryNode[];
	readonly orphans: readonly LedgerEntry[];
}

/**
 * Commit history with the task each session produced hanging off it.
 *
 * Laid out as a bento: the commit line on the left, detail for the selected
 * node on the right. The whole history is handed to the webview at once and
 * selection is handled in the page, because a history is small and a round
 * trip per click would only add latency.
 */
export class WorkshopHistoryViewProvider implements vscode.WebviewViewProvider {

	private view: vscode.WebviewView | undefined;
	private history: History | undefined;
	private status: string | undefined;

	constructor(private readonly extensionPath: string) { }

	resolveWebviewView(webviewView: vscode.WebviewView): void {
		this.view = webviewView;
		webviewView.webview.options = { enableScripts: true };
		webviewView.webview.onDidReceiveMessage(message => this.onMessage(message));
		void this.refresh();
	}

	/** Re-read the history for the open project. */
	async refresh(): Promise<void> {
		const project = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
		if (!project) {
			this.status = 'Open a mod project to see its history.';
			this.history = undefined;
			this.render();
			return;
		}
		this.status = 'Reading history…';
		this.render();
		try {
			const result = await runWorkshop(this.extensionPath, ['history', project]);
			if (result.exitCode !== 0) {
				this.status = `Could not read history: ${result.stderr.trim() || result.stdout.trim()}`;
				this.history = undefined;
			} else {
				this.history = JSON.parse(result.stdout) as History;
				this.status = undefined;
			}
		} catch (error) {
			this.status = `Could not read history: ${error instanceof Error ? error.message : String(error)}`;
			this.history = undefined;
		}
		this.render();
	}

	private async onMessage(message: { type?: string; path?: string }): Promise<void> {
		if (message?.type !== 'reveal' || !message.path) {
			return;
		}
		const uri = vscode.Uri.file(message.path);
		try {
			await vscode.commands.executeCommand('revealFileInOS', uri);
		} catch {
			vscode.window.showWarningMessage(`Could not open ${message.path}`);
		}
	}

	private render(): void {
		if (this.view) {
			this.view.webview.html = this.html();
		}
	}

	private html(): string {
		const nonce = crypto.randomBytes(16).toString('base64');
		const csp = `default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';`;
		// Serialized rather than templated into markup: the page builds its own
		// DOM with textContent, so no field can inject markup.
		const payload = JSON.stringify(this.history ?? { nodes: [], orphans: [] })
			.replace(/</g, '\\u003c');
		const status = JSON.stringify(this.status ?? null).replace(/</g, '\\u003c');
		return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style nonce="${nonce}">${STYLES}</style>
</head>
<body>
<div id="bento">
	<div id="line" role="listbox" aria-label="Session history"></div>
	<div id="detail" role="region" aria-label="Session detail"></div>
</div>
<script nonce="${nonce}">
const HISTORY = ${payload};
const STATUS = ${status};
${SCRIPT}
</script>
</body>
</html>`;
	}
}

const STYLES = `
* { box-sizing: border-box; }
body {
	margin: 0;
	font-family: var(--vscode-font-family);
	font-size: var(--vscode-font-size);
	color: var(--vscode-foreground);
}
#bento { display: grid; grid-template-columns: minmax(160px, 40%) 1fr; height: 100vh; }
#line { overflow-y: auto; padding: 8px 0; border-right: 1px solid var(--vscode-panel-border); }
#detail { overflow-y: auto; padding: 12px 14px; }

.node {
	display: grid;
	grid-template-columns: 20px 1fr;
	align-items: start;
	gap: 6px;
	padding: 2px 8px 2px 4px;
	cursor: pointer;
	border: none;
	background: none;
	width: 100%;
	text-align: left;
	color: inherit;
	font: inherit;
}
.node:hover { background: var(--vscode-list-hoverBackground); }
.node[aria-selected="true"] { background: var(--vscode-list-activeSelectionBackground); }
.node[aria-selected="true"] .label { color: var(--vscode-list-activeSelectionForeground); }

/* The rail: a dot on a vertical line drawn by the cell's own borders. */
.rail { position: relative; width: 20px; align-self: stretch; min-height: 34px; }
.rail::before {
	content: '';
	position: absolute;
	left: 9px; top: 0; bottom: 0;
	width: 2px;
	background: var(--vscode-panel-border);
}
.node:first-child .rail::before { top: 12px; }
.node:last-child .rail::before { bottom: calc(100% - 12px); }
.dot {
	position: absolute;
	left: 4px; top: 7px;
	width: 12px; height: 12px;
	border-radius: 50%;
	background: var(--vscode-editor-background);
	border: 2px solid var(--vscode-panel-border);
}
.dot.task { border-color: var(--vscode-charts-blue); background: var(--vscode-charts-blue); }
.dot.swe_bench { border-color: var(--vscode-charts-green); background: var(--vscode-charts-green); }
.dot.opt { border-color: var(--vscode-charts-purple); background: var(--vscode-charts-purple); }
.dot.revise { border-color: var(--vscode-charts-orange); background: var(--vscode-charts-orange); }

.body { padding: 2px 0 6px; min-width: 0; }
.label { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.label.task { font-weight: 600; }
.meta { color: var(--vscode-descriptionForeground); font-size: 0.85em; }

h2 { font-size: 1.05em; margin: 0 0 2px; overflow-wrap: anywhere; }
h3 { font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.04em;
	color: var(--vscode-descriptionForeground); margin: 16px 0 6px; }
.subtitle { color: var(--vscode-descriptionForeground); margin: 0 0 12px; font-size: 0.9em; }
.empty { color: var(--vscode-descriptionForeground); padding: 12px 0; }

.badge {
	display: inline-block; padding: 1px 8px; border-radius: 10px;
	font-size: 0.8em; font-weight: 600; margin-bottom: 10px;
	background: var(--vscode-badge-background); color: var(--vscode-badge-foreground);
}
.badge.swe_bench { background: var(--vscode-charts-green); color: var(--vscode-editor-background); }
.badge.opt { background: var(--vscode-charts-purple); color: var(--vscode-editor-background); }
.badge.revise { background: var(--vscode-charts-orange); color: var(--vscode-editor-background); }

dl { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; margin: 0; }
dt { color: var(--vscode-descriptionForeground); }
dd { margin: 0; overflow-wrap: anywhere; font-family: var(--vscode-editor-font-family); font-size: 0.9em; }

table { border-collapse: collapse; width: 100%; font-size: 0.9em; }
th, td { text-align: left; padding: 3px 8px 3px 0; }
th { color: var(--vscode-descriptionForeground); font-weight: normal; }
td.rate { font-family: var(--vscode-editor-font-family); }
tr.discounted td { color: var(--vscode-descriptionForeground); text-decoration: line-through; }
.note { color: var(--vscode-descriptionForeground); font-size: 0.85em; margin-top: 6px; }

ul.ids { margin: 0; padding-left: 18px; }
ul.ids li { font-family: var(--vscode-editor-font-family); font-size: 0.9em; overflow-wrap: anywhere; }

button.link {
	background: none; border: none; padding: 0; cursor: pointer;
	color: var(--vscode-textLink-foreground); font: inherit; text-align: left;
}
button.link:hover { text-decoration: underline; }
`;

const SCRIPT = `
const vscode = acquireVsCodeApi();
const line = document.getElementById('line');
const detail = document.getElementById('detail');
let selected = null;

function el(tag, className, text) {
	const node = document.createElement(tag);
	if (className) { node.className = className; }
	if (text !== undefined && text !== null) { node.textContent = String(text); }
	return node;
}

function routeLabel(route) {
	if (route === 'swe_bench') { return 'SWE-Bench'; }
	if (route === 'opt') { return 'OPT (preference training)'; }
	if (route === 'revise') { return 'Needs revision'; }
	if (route === 'insufficient') { return 'Not measured'; }
	return 'Not routed yet';
}

function renderLine() {
	line.textContent = '';
	if (STATUS) { line.appendChild(el('p', 'empty', STATUS)); return; }
	if (!HISTORY.nodes.length) { line.appendChild(el('p', 'empty', 'No commits yet.')); return; }

	HISTORY.nodes.forEach((node, index) => {
		const button = el('button', 'node');
		button.setAttribute('role', 'option');
		button.setAttribute('aria-selected', String(index === 0));

		const rail = el('div', 'rail');
		let dotClass = 'dot';
		if (node.entry) { dotClass += ' ' + (node.entry.route || 'task'); }
		rail.appendChild(el('div', dotClass));
		button.appendChild(rail);

		const body = el('div', 'body');
		body.appendChild(el('span', node.hasTask ? 'label task' : 'label', node.label));
		body.appendChild(el('span', 'meta', node.short + ' · ' + node.date.slice(0, 10)));
		button.appendChild(body);

		button.addEventListener('click', () => select(index));
		line.appendChild(button);
	});
	select(0);
}

function select(index) {
	selected = index;
	Array.from(line.querySelectorAll('.node')).forEach((node, i) =>
		node.setAttribute('aria-selected', String(i === index)));
	renderDetail(HISTORY.nodes[index]);
}

function addPair(list, term, value) {
	list.appendChild(el('dt', null, term));
	list.appendChild(el('dd', null, value));
}

function addPath(list, term, value) {
	list.appendChild(el('dt', null, term));
	const dd = el('dd');
	const button = el('button', 'link', value);
	button.title = 'Reveal in Finder';
	button.addEventListener('click', () => vscode.postMessage({ type: 'reveal', path: value }));
	dd.appendChild(button);
	list.appendChild(dd);
}

function renderDetail(node) {
	detail.textContent = '';
	if (!node) { detail.appendChild(el('p', 'empty', 'Select a commit.')); return; }

	detail.appendChild(el('h2', null, node.subject));
	detail.appendChild(el('p', 'subtitle', node.short + ' · ' + node.author + ' · ' + node.date));

	const entry = node.entry;
	if (!entry) {
		detail.appendChild(el('p', 'empty', 'No session produced a task at this commit.'));
		return;
	}

	detail.appendChild(el('span', 'badge ' + (entry.route || ''), routeLabel(entry.route)));

	detail.appendChild(el('h3', null, 'Saved data'));
	const where = el('dl');
	addPair(where, 'Task', entry.task || '—');
	if (entry.output) { addPath(where, 'Directory', entry.output); }
	if (entry.archive) { addPath(where, 'Archive', entry.archive); }
	addPair(where, 'Session', entry.session_id);
	addPair(where, 'Submittable', entry.submittable ? 'yes' : 'no — has blockers');
	if (entry.recorded_at) { addPair(where, 'Emitted', entry.recorded_at); }
	if (entry.routed_at) { addPair(where, 'Routed', entry.routed_at); }
	detail.appendChild(where);

	const runs = (entry.profile && entry.profile.runs) || [];
	if (runs.length) {
		detail.appendChild(el('h3', null, 'Benchmark results'));
		const table = el('table');
		const head = el('tr');
		['Model', 'Passed', 'Rate'].forEach(h => head.appendChild(el('th', null, h)));
		table.appendChild(head);
		runs.forEach(run => {
			const row = el('tr', run.discounted ? 'discounted' : null);
			row.appendChild(el('td', null, run.model));
			row.appendChild(el('td', 'rate', run.passed + ' / ' + run.trials));
			row.appendChild(el('td', 'rate', Math.round(run.pass_rate * 100) + '%'));
			if (run.discounted) { row.title = run.discount_reason; }
			table.appendChild(row);
		});
		detail.appendChild(table);
		const discounted = runs.filter(r => r.discounted);
		if (discounted.length) {
			detail.appendChild(el('p', 'note',
				'Struck-through runs were discounted: ' + discounted[0].discount_reason));
		}
	} else if (entry.route) {
		detail.appendChild(el('p', 'note', 'Routed without recorded benchmark runs.'));
	}

	if (entry.fail_to_pass.length) {
		detail.appendChild(el('h3', null, 'fail_to_pass'));
		const list = el('ul', 'ids');
		entry.fail_to_pass.forEach(id => list.appendChild(el('li', null, id)));
		detail.appendChild(list);
	}
	if (entry.pass_to_pass.length) {
		detail.appendChild(el('h3', null, 'pass_to_pass'));
		const list = el('ul', 'ids');
		entry.pass_to_pass.forEach(id => list.appendChild(el('li', null, id)));
		detail.appendChild(list);
	}
}

renderLine();
`;
