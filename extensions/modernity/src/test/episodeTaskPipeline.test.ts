/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as assert from 'assert';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import { suite, test } from 'mocha';
import {
	parseEpisodeGradeFeedback,
	parseEpisodeTaskArtifact,
	parseEpisodeTaskPublication,
	parseEpisodeTestPreparation,
	prepareEpisodeGradeFeedback,
} from '../episodeTaskPipeline';

suite('Modernity Episode Task Pipeline', () => {
	test('parses fingerprint-bound task publication states', () => {
		const fingerprint = 'a'.repeat(64);
		assert.deepStrictEqual(
			parseEpisodeTaskPublication({
				status: 'push_pending',
				task: 'example_feature',
				destination: '/tmp/tasks/example_feature',
				repository: '/tmp/tasks',
				branch: 'main',
				artifact_fingerprint: fingerprint,
				commit: 'b'.repeat(40),
				push_error: 'remote rejected the push',
			}, fingerprint),
			{
				status: 'push_pending',
				taskName: 'example_feature',
				destination: '/tmp/tasks/example_feature',
				repositoryRoot: '/tmp/tasks',
				branch: 'main',
				artifactFingerprint: fingerprint,
				commitSha: 'b'.repeat(40),
				pushError: 'remote rejected the push',
			},
		);
		assert.throws(() => parseEpisodeTaskPublication({
			status: 'published',
			task: 'example_feature',
			destination: '/tmp/tasks/example_feature',
			repository: '/tmp/tasks',
			branch: 'main',
			artifact_fingerprint: 'c'.repeat(64),
		}, fingerprint));
	});

	test('routes qualitative revisions to tests or candidate blockers', () => {
		const taskName = 'owner__repo-abcdef0-v1';
		const taskDirectory = path.resolve('tmp', 'tasks', taskName);
		const reportPath = path.resolve('tmp', 'grades', taskName, 'grade-report.json');
		const fingerprint = 'a'.repeat(64);
		const artifact = {
			taskName,
			taskDirectory,
			taskRepositoryRoot: path.dirname(taskDirectory),
			baseCommit: 'b'.repeat(40),
			finalCommit: 'c'.repeat(40),
			traceSessionId: 'trace-session',
			environmentVersion: 1,
			artifactFingerprint: fingerprint,
			testReviewPath: path.resolve('tmp', 'reviews', taskName, 'first-party-tests.md'),
			testReviewSha256: 'd'.repeat(64),
			failToPass: ['mod:feature'],
			passToPass: ['mod:baseline'],
		};
		const identity = {
			status: 'revise',
			verdict: 'revise',
			task: taskName,
			source_task: taskDirectory,
			report_path: reportPath,
			artifact_fingerprint: {
				verified: true,
				expected_digest: fingerprint,
				actual_digest: fingerprint,
			},
		};
		const report = (issues: readonly Record<string, string>[]) => ({
			...identity,
			commands: [
				{
					name: 'validate',
					stdout: JSON.stringify({ qualitative: { error: 'incomplete validation' } }),
				},
				{
					name: 'validate_vanilla',
					stdout: JSON.stringify({ qualitative: { verdict: 'Revise', issues } }),
				},
			],
		});
		const testIssue = {
			severity: 'High',
			category: 'Tests',
			issue: 'Tests leak the solution skeleton',
			evidence: 'Exact private class names are asserted',
		};
		const reportWithTestIssue = report([testIssue]);

		assert.deepStrictEqual([
			parseEpisodeGradeFeedback(reportWithTestIssue, reportPath, artifact),
			parseEpisodeGradeFeedback(report([
				testIssue,
				{
					severity: 'Medium',
					category: 'Spec',
					issue: 'The instruction omits a required boundary',
				},
			]), reportPath, artifact),
			parseEpisodeGradeFeedback(report([
				testIssue,
				{
					severity: 'Low',
					category: 'Spec',
					issue: 'Tests can phrase one assertion more clearly',
				},
			]), reportPath, artifact),
			parseEpisodeGradeFeedback(report([{
				severity: 'High',
				category: 'Patch',
				issue: 'Implementation is incomplete',
			}]), reportPath, artifact),
			parseEpisodeGradeFeedback({ ...reportWithTestIssue, task: 'other-task' }, reportPath, artifact),
			parseEpisodeGradeFeedback({ ...reportWithTestIssue, source_task: path.resolve('tmp', 'stale-task') }, reportPath, artifact),
			parseEpisodeGradeFeedback({ ...reportWithTestIssue, report_path: path.resolve('tmp', 'stale-report.json') }, reportPath, artifact),
			parseEpisodeGradeFeedback({
				...reportWithTestIssue,
				artifact_fingerprint: { ...identity.artifact_fingerprint, actual_digest: 'e'.repeat(64) },
			}, reportPath, artifact),
			parseEpisodeGradeFeedback({
				...reportWithTestIssue,
				artifact_fingerprint: { ...identity.artifact_fingerprint, expected_digest: 'e'.repeat(64) },
			}, reportPath, artifact),
			parseEpisodeGradeFeedback({
				...reportWithTestIssue,
				artifact_fingerprint: { ...identity.artifact_fingerprint, verified: false },
			}, reportPath, artifact),
		], [
			{
				route: 'test_revision',
				review: [
					'Codimango qualitative validation requested a hidden-GameTest revision.',
					'',
					'- High Tests: Tests leak the solution skeleton',
					'  Evidence: Exact private class names are asserted',
				].join('\n'),
			},
			{
				route: 'candidate_revision',
				summary: [
					'Codimango qualitative validation found issues that require an implementation or instruction revision.',
					'',
					'- High Tests: Tests leak the solution skeleton',
					'  Evidence: Exact private class names are asserted',
					'- Medium Spec: The instruction omits a required boundary',
				].join('\n'),
			},
			{
				route: 'test_revision',
				review: [
					'Codimango qualitative validation requested a hidden-GameTest revision.',
					'',
					'- High Tests: Tests leak the solution skeleton',
					'  Evidence: Exact private class names are asserted',
					'- Low Spec: Tests can phrase one assertion more clearly',
				].join('\n'),
			},
			{
				route: 'candidate_revision',
				summary: [
					'Codimango qualitative validation found issues that require an implementation or instruction revision.',
					'',
					'- High Patch: Implementation is incomplete',
				].join('\n'),
			},
			undefined,
			undefined,
			undefined,
			undefined,
			undefined,
			undefined,
		]);
	});

	test('persists strengthened hidden-test guidance for automatic test revision', async () => {
		const repositoryRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'modernity-grade-feedback-'));
		try {
			const taskName = 'owner__repo-abcdef0-v1';
			const taskDirectory = path.join(repositoryRoot, 'tasks', taskName);
			const reportPath = path.join(repositoryRoot, 'grades', taskName, 'grade-report.json');
			const fingerprint = 'a'.repeat(64);
			const artifact = {
				taskName,
				taskDirectory,
				taskRepositoryRoot: path.dirname(taskDirectory),
				baseCommit: 'b'.repeat(40),
				finalCommit: 'c'.repeat(40),
				traceSessionId: 'trace-session',
				environmentVersion: 1,
				artifactFingerprint: fingerprint,
				testReviewPath: path.join(repositoryRoot, 'reviews', 'first-party-tests.md'),
				testReviewSha256: 'd'.repeat(64),
				failToPass: ['mod:feature'],
				passToPass: ['mod:baseline'],
			};
			await fs.mkdir(path.dirname(reportPath), { recursive: true });
			await fs.writeFile(reportPath, JSON.stringify({
				status: 'revise',
				verdict: 'revise',
				task: taskName,
				source_task: taskDirectory,
				report_path: reportPath,
				artifact_fingerprint: {
					verified: true,
					expected_digest: fingerprint,
					actual_digest: fingerprint,
				},
				commands: [{
					name: 'validate_vanilla',
					stdout: JSON.stringify({
						qualitative: {
							verdict: 'Revise',
							issues: [{ severity: 'High', category: 'Tests', issue: 'Boundary coverage is weak' }],
						},
					}),
				}],
			}), 'utf8');

			const feedback = await prepareEpisodeGradeFeedback(
				repositoryRoot,
				'trace-session',
				reportPath,
				artifact,
			);
			const guidance = feedback?.route === 'test_revision'
				? await fs.readFile(feedback.guidancePath, 'utf8')
				: '';
			assert.deepStrictEqual({
				route: feedback?.route,
				hasCollisionGuidance: guidance.includes('collision-resistant hidden package, class, and runtime test identifiers'),
				hasBoundaryGuidance: guidance.includes('just below, exactly at, and just above the boundary'),
				hasBoundednessGuidance: guidance.includes('supported, mutable sentinels at and just outside the boundary'),
				hasAlternativesGuidance: guidance.includes('alternative class layouts, registry wiring, and internal architectures'),
			}, {
				route: 'test_revision',
				hasCollisionGuidance: true,
				hasBoundaryGuidance: true,
				hasBoundednessGuidance: true,
				hasAlternativesGuidance: true,
			});
		} finally {
			await fs.rm(repositoryRoot, { recursive: true, force: true });
		}
	});

	test('parses prepared and already-validated GameTest commits', () => {
		assert.deepStrictEqual([
			parseEpisodeTestPreparation({
				action: 'prepared',
				raw_commit: 'raw',
				prepared_commit: 'prepared',
				prepared_tree: 'tree-one',
				receipt: '/tmp/prepared.json',
				review_path: '/tmp/review/first-party-tests.md',
				review_sha256: 'a'.repeat(64),
			}, 'raw'),
			parseEpisodeTestPreparation({
				action: 'validated',
				raw_commit: 'same',
				prepared_commit: 'same',
				prepared_tree: 'tree-two',
				receipt: '/tmp/validated.json',
				review_path: '/tmp/review/first-party-tests.md',
				review_sha256: 'b'.repeat(64),
			}, 'same'),
		], [
			{
				action: 'prepared',
				commitSha: 'prepared',
				treeSha: 'tree-one',
				receiptPath: '/tmp/prepared.json',
				reviewPath: '/tmp/review/first-party-tests.md',
				reviewSha256: 'a'.repeat(64),
			},
			{
				action: 'validated',
				commitSha: 'same',
				treeSha: 'tree-two',
				receiptPath: '/tmp/validated.json',
				reviewPath: '/tmp/review/first-party-tests.md',
				reviewSha256: 'b'.repeat(64),
			},
		]);
	});

	test('rejects stale or incomplete preparation responses', () => {
		assert.deepStrictEqual([
			captureError(() => parseEpisodeTestPreparation({
				action: 'validated',
				raw_commit: 'stale',
				prepared_commit: 'stale',
				prepared_tree: 'tree',
				receipt: '/tmp/receipt.json',
				review_path: '/tmp/review/first-party-tests.md',
				review_sha256: 'a'.repeat(64),
			}, 'expected')),
			captureError(() => parseEpisodeTestPreparation({
				action: 'prepared',
				raw_commit: 'raw',
				prepared_commit: 'prepared',
				prepared_tree: 'tree',
			}, 'raw')),
			captureError(() => parseEpisodeTestPreparation({ action: 'skipped' }, 'raw')),
		], [
			'GameTest preparation used commit stale, but Modernity expected expected.',
			'GameTest preparation completed without a raw commit, prepared commit, tree, receipt, or fingerprinted first-party review.',
			'GameTest preparation reported an unsupported action: skipped.',
		]);
	});

	test('parses a fingerprint-verified task inspection response', () => {
		assert.deepStrictEqual(parseEpisodeTaskArtifact({
			task: 'author_owner__repo-abcdef0-v2',
			base_commit: 'a'.repeat(40),
			final_commit: 'b'.repeat(40),
			trace_session_id: 'trace-session',
			environment_version: 2,
			artifact_fingerprint: {
				schema_version: 1,
				algorithm: 'sha256',
				digest: 'c'.repeat(64),
			},
			test_review_path: '/tmp/tasks/.modernity/reviews/task-v2/first-party-tests.md',
			test_review_sha256: 'd'.repeat(64),
			fail_to_pass: ['mod:feature'],
			pass_to_pass: ['mod:regression'],
		}, '/tmp/tasks/task-v2', '/tmp/tasks'), {
			taskName: 'author_owner__repo-abcdef0-v2',
			taskDirectory: '/tmp/tasks/task-v2',
			taskRepositoryRoot: '/tmp/tasks',
			baseCommit: 'a'.repeat(40),
			finalCommit: 'b'.repeat(40),
			traceSessionId: 'trace-session',
			environmentVersion: 2,
			artifactFingerprint: 'c'.repeat(64),
			testReviewPath: '/tmp/tasks/.modernity/reviews/task-v2/first-party-tests.md',
			testReviewSha256: 'd'.repeat(64),
			failToPass: ['mod:feature'],
			passToPass: ['mod:regression'],
		});
	});

	test('rejects incomplete or malformed task inspection identity', () => {
		assert.deepStrictEqual([
			captureError(() => parseEpisodeTaskArtifact({
				task: 'task',
				base_commit: 'a'.repeat(40),
				final_commit: 'b'.repeat(40),
				trace_session_id: 'trace',
				environment_version: 1,
				artifact_fingerprint: { digest: 'not-a-sha' },
				test_review_path: '/tmp/review.md',
				test_review_sha256: 'd'.repeat(64),
			}, '/tmp/task', '/tmp')),
			captureError(() => parseEpisodeTaskArtifact({
				task: 'task',
				base_commit: 'a'.repeat(40),
				final_commit: 'b'.repeat(40),
				trace_session_id: 'trace',
				environment_version: 0,
				artifact_fingerprint: 'c'.repeat(64),
				test_review_path: '/tmp/review.md',
				test_review_sha256: 'd'.repeat(64),
			}, '/tmp/task', '/tmp')),
		], [
			'Task artifact metadata is missing a complete identity, artifact fingerprint, or first-party test review.',
			'Task artifact metadata is missing a complete identity, artifact fingerprint, or first-party test review.',
		]);
	});
});

function captureError(callback: () => void): string | undefined {
	try {
		callback();
	} catch (error) {
		return error instanceof Error ? error.message : String(error);
	}
	return undefined;
}
