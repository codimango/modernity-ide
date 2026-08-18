/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as fs from 'fs/promises';
import * as path from 'path';

export const EPISODE_BUNDLE_DIRECTORY = path.join('.modernity', 'episodes');

const PLAN_EVENT_TYPE = 'planner.plan.generated';
const PLAN_TASK_EVENT_TYPE = 'planner.task.planned';
const UNSAFE_SEGMENT = /[^A-Za-z0-9._-]+/g;

export interface ITraceEventRecord {
	readonly event_type?: string;
	readonly [key: string]: unknown;
}

export interface IEpisodeBundle {
	readonly taskId: string;
	readonly episode: object;
	readonly events: readonly ITraceEventRecord[];
	readonly corrections: readonly object[];
	readonly instruction: string;
	readonly patch?: string;
}

/**
 * Write one sealed episode bundle into the project's Git-ignored episode folder.
 *
 * The folder is ignored so a submitted trace never dirties the worktree that the
 * accept flow requires to stay clean, and never lands in the feature commit.
 */
export async function writeEpisodeBundle(repositoryRoot: string, bundle: IEpisodeBundle): Promise<string> {
	const root = path.join(repositoryRoot, EPISODE_BUNDLE_DIRECTORY);
	const directory = path.join(root, safeSegment(bundle.taskId));
	await fs.mkdir(directory, { recursive: true });
	await writeIgnoreGuard(root);

	await fs.writeFile(path.join(directory, 'episode.json'), `${JSON.stringify(bundle.episode, null, 2)}\n`, 'utf8');
	await fs.writeFile(
		path.join(directory, 'trace.jsonl'),
		bundle.events.map(event => JSON.stringify(event)).join('\n') + (bundle.events.length ? '\n' : ''),
		'utf8',
	);
	await fs.writeFile(path.join(directory, 'corrections.json'), `${JSON.stringify(bundle.corrections, null, 2)}\n`, 'utf8');
	await fs.writeFile(
		path.join(directory, 'instruction.md'),
		bundle.instruction.endsWith('\n') ? bundle.instruction : `${bundle.instruction}\n`,
		'utf8',
	);

	const plan = plannerEvidence(bundle.events);
	if (plan.length > 0) {
		await fs.writeFile(path.join(directory, 'plan.json'), `${JSON.stringify(plan, null, 2)}\n`, 'utf8');
	}
	if (bundle.patch) {
		await fs.writeFile(path.join(directory, 'task.patch'), bundle.patch, 'utf8');
		await fs.writeFile(path.join(directory, 'golden.txt'), bundle.patch, 'utf8');
	}
	return directory;
}

/** Return the planner plan and task events a planner agent published to this trace. */
export function plannerEvidence(events: readonly ITraceEventRecord[]): readonly ITraceEventRecord[] {
	return events.filter(event => event.event_type === PLAN_EVENT_TYPE || event.event_type === PLAN_TASK_EVENT_TYPE);
}

function safeSegment(value: string): string {
	const safe = value.replace(UNSAFE_SEGMENT, '-').replace(/^[-.]+/, '').slice(0, 128);
	return safe || 'episode';
}

async function writeIgnoreGuard(root: string): Promise<void> {
	const ignorePath = path.join(root, '.gitignore');
	try {
		await fs.access(ignorePath);
	} catch {
		await fs.writeFile(ignorePath, '# Modernity episode bundles are local evidence, not project source.\n*\n', 'utf8');
	}
}
