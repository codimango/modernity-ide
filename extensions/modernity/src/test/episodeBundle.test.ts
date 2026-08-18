/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as assert from 'assert';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import { suite, test } from 'mocha';
import * as os from 'os';
import * as path from 'path';
import { EPISODE_BUNDLE_DIRECTORY, plannerEvidence, writeEpisodeBundle } from '../episodeBundle';

function temporaryRepository(): string {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'modernity-episode-bundle-'));
	execFileSync('git', ['init', '-b', 'main', root]);
	fs.writeFileSync(path.join(root, 'README.md'), 'base\n', 'utf8');
	execFileSync('git', ['-C', root, 'add', '-A']);
	execFileSync('git', [
		'-C', root,
		'-c', 'user.name=Modernity',
		'-c', 'user.email=modernity@users.noreply.github.com',
		'commit', '-m', 'base',
	]);
	return root;
}

suite('Modernity Episode Bundle', () => {
	test('writes the sealed session into a Git-ignored project folder', async () => {
		const root = temporaryRepository();
		try {
			const directory = await writeEpisodeBundle(root, {
				taskId: 'delversfeast-2026-08-08-ab12cd34',
				episode: { id: 'episode-1', lifecycle_status: 'accepted_candidate' },
				events: [
					{ event_id: 'event-1', event_type: 'user.message' },
					{ event_id: 'event-2', event_type: 'planner.plan.generated', payload: { plan_id: 'p0' } },
					{ event_id: 'event-3', event_type: 'planner.task.planned', payload: { plan_id: 'p0' } },
				],
				corrections: [{ id: 'correction-1', ordinal: 1 }],
				instruction: 'Add a data-driven lantern.\n',
				patch: 'diff --git a/A.java b/A.java\n',
			});
			const read = (name: string) => fs.readFileSync(path.join(directory, name), 'utf8');

			assert.deepStrictEqual({
				directory: path.relative(root, directory),
				traceLines: read('trace.jsonl').trimEnd().split('\n').length,
				episodeId: JSON.parse(read('episode.json')).id,
				corrections: JSON.parse(read('corrections.json')).length,
				planEvents: JSON.parse(read('plan.json')).length,
				instruction: read('instruction.md'),
				patch: read('task.patch'),
				golden: read('golden.txt'),
				gitStatus: execFileSync('git', ['-C', root, 'status', '--porcelain=v1', '--untracked-files=all'], { encoding: 'utf8' }),
			}, {
				directory: path.join(EPISODE_BUNDLE_DIRECTORY, 'delversfeast-2026-08-08-ab12cd34'),
				traceLines: 3,
				episodeId: 'episode-1',
				corrections: 1,
				planEvents: 2,
				instruction: 'Add a data-driven lantern.\n',
				patch: 'diff --git a/A.java b/A.java\n',
				golden: 'diff --git a/A.java b/A.java\n',
				gitStatus: '',
			});
		} finally {
			fs.rmSync(root, { recursive: true, force: true });
		}
	});

	test('omits optional evidence and keeps the task id inside the episode folder', async () => {
		const root = temporaryRepository();
		try {
			const directory = await writeEpisodeBundle(root, {
				taskId: '../../escaped id',
				episode: {},
				events: [],
				corrections: [],
				instruction: 'Create a mod.\n',
			});

			assert.deepStrictEqual({
				contained: directory.startsWith(path.join(root, EPISODE_BUNDLE_DIRECTORY) + path.sep),
				name: path.basename(directory),
				trace: fs.readFileSync(path.join(directory, 'trace.jsonl'), 'utf8'),
				plan: fs.existsSync(path.join(directory, 'plan.json')),
				patch: fs.existsSync(path.join(directory, 'task.patch')),
				golden: fs.existsSync(path.join(directory, 'golden.txt')),
			}, {
				contained: true,
				name: 'escaped-id',
				trace: '',
				plan: false,
				patch: false,
				golden: false,
			});
		} finally {
			fs.rmSync(root, { recursive: true, force: true });
		}
	});

	test('selects only planner evidence from a trace', () => {
		assert.deepStrictEqual(plannerEvidence([
			{ event_type: 'user.message' },
			{ event_type: 'planner.task.planned', event_id: 'task' },
			{ event_type: 'tooling.tool.completed' },
			{ event_type: 'planner.plan.generated', event_id: 'plan' },
		]), [
			{ event_type: 'planner.task.planned', event_id: 'task' },
			{ event_type: 'planner.plan.generated', event_id: 'plan' },
		]);
	});
});
