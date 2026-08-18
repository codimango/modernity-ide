/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import {
	parseCliJson,
	runWorkshop,
	workshopCommandFailureDetail,
	WorkshopCliError,
} from './workshopCli';

const WORKSHOP_DIRECTORY = path.join('.modernity', 'workshop');
const INSTRUCTION_FILE = 'instruction.md';
const GRADE_FEEDBACK_DIRECTORY = 'grade-feedback';
const TEST_REVIEW_FILE = 'qualitative-test-review.md';
const TEST_GUIDANCE_FILE = 'test-guidance.md';

export interface IEpisodeTaskCaptureRequest {
	readonly repositoryRoot: string;
	readonly sessionId: string;
	readonly model: string;
	readonly prompt: string;
	readonly expectedBaseCommit: string;
}

export interface IEpisodeTaskArtifactRequest {
	readonly repositoryRoot: string;
	readonly sessionId: string;
	readonly finalCommit: string;
	readonly projectSlug: string;
	readonly remoteName?: string;
	readonly complexity: 'S' | 'M' | 'L';
	readonly followups?: readonly string[];
}

export interface IEpisodeTestPreparationRequest {
	readonly repositoryRoot: string;
	readonly sessionId: string;
	readonly finalCommit: string;
	readonly reviewFile?: string;
	readonly guidanceFile?: string;
	readonly failureDirectory?: string;
}

export interface IEpisodeTestPreparation {
	readonly action: 'prepared' | 'validated';
	readonly commitSha: string;
	readonly treeSha: string;
	readonly receiptPath: string;
	readonly reviewPath: string;
	readonly reviewSha256: string;
}

export interface IEpisodeTaskArtifact {
	readonly taskName: string;
	readonly taskDirectory: string;
	readonly taskRepositoryRoot: string;
	readonly baseCommit: string;
	readonly finalCommit: string;
	readonly traceSessionId: string;
	readonly environmentVersion: number;
	readonly artifactFingerprint: string;
	readonly testReviewPath: string;
	readonly testReviewSha256: string;
	readonly failToPass: readonly string[];
	readonly passToPass: readonly string[];
}

export interface IEpisodeTaskResolutionRequest {
	readonly repositoryRoot: string;
	readonly taskRepositoryRoot?: string;
	readonly expectedBaseCommit: string;
	readonly expectedFinalCommit: string;
	readonly expectedTraceSessionId: string;
}

export interface IEpisodeTaskGrade {
	readonly status: string;
	readonly reportPath: string;
	readonly taskDirectory: string;
}

export interface IEpisodeTaskPublicationRequest {
	readonly gradeReportPath: string;
	readonly repositoryRoot: string;
	readonly branch: string;
	readonly expectedArtifactFingerprint: string;
}

export interface IEpisodeTaskPublication {
	readonly status: 'ready' | 'published' | 'already_published' | 'push_pending';
	readonly taskName: string;
	readonly destination: string;
	readonly repositoryRoot: string;
	readonly branch: string;
	readonly artifactFingerprint: string;
	readonly commitSha?: string;
	readonly pushError?: string;
}

/** Qualitative feedback that can be resolved by replacing hidden tests only. */
export interface IEpisodeTestRevisionAnalysis {
	readonly route: 'test_revision';
	readonly review: string;
}

/** Qualitative feedback that requires implementation or instruction changes. */
export interface IEpisodeCandidateRevisionAnalysis {
	readonly route: 'candidate_revision';
	readonly summary: string;
}

/** Structured routing decision parsed from a fingerprint-bound grade report. */
export type EpisodeGradeFeedbackAnalysis = IEpisodeTestRevisionAnalysis | IEpisodeCandidateRevisionAnalysis;

/** Prepared feedback, including persisted guidance when tests may be revised. */
export type IEpisodeGradeFeedback = IEpisodeCandidateRevisionAnalysis | (IEpisodeTestRevisionAnalysis & {
	readonly reviewPath: string;
	readonly guidancePath: string;
});

/** Normalized issue emitted by Codimango qualitative validation. */
interface IQualitativeIssue {
	readonly severity: string;
	readonly category: string;
	readonly finding: string;
	readonly evidence?: string;
}

/** Pin the workshop base commit used later to split and grade the episode patch. */
export async function beginEpisodeTaskCapture(
	extensionPath: string,
	request: IEpisodeTaskCaptureRequest,
): Promise<void> {
	const result = await runWorkshop(extensionPath, [
		'begin',
		request.repositoryRoot,
		'--session-id', request.sessionId,
		'--model', request.model,
		'--dirty-policy', 'require_clean',
	]);
	const payload = parseCliJson(result.stdout);
	if (result.exitCode !== 0 || payload.status !== 'ok') {
		throw workshopFailure(vscode.l10n.t('Could not pin the benchmark base commit.'), result.stderr, payload);
	}
	if (payload.base_commit !== request.expectedBaseCommit) {
		throw new WorkshopCliError(vscode.l10n.t(
			'Workshop pinned base commit {0}, but the episode expected {1}.',
			String(payload.base_commit ?? 'unknown').slice(0, 12),
			request.expectedBaseCommit.slice(0, 12),
		));
	}
	const instructionPath = episodeInstructionPath(request.repositoryRoot, request.sessionId);
	await fs.mkdir(path.dirname(instructionPath), { recursive: true });
	await fs.writeFile(
		instructionPath,
		request.prompt.endsWith('\n') ? request.prompt : `${request.prompt}\n`,
		'utf8',
	);
}

/** Remove a workshop record when episode creation fails before collection begins. */
export async function discardEpisodeTaskCapture(repositoryRoot: string, sessionId: string): Promise<void> {
	await fs.rm(path.join(repositoryRoot, WORKSHOP_DIRECTORY, sessionId), { recursive: true, force: true });
}

/** Prepare provenance-safe hidden GameTests before deriving or emitting task artifacts. */
export async function prepareEpisodeTests(
	extensionPath: string,
	request: IEpisodeTestPreparationRequest,
	onProgress?: (message: string) => void,
): Promise<IEpisodeTestPreparation> {
	onProgress?.(vscode.l10n.t('Validating and preparing first-party GameTests…'));
	const args = [
		'prepare-tests', request.repositoryRoot,
		'--session-id', request.sessionId,
		'--final-commit', request.finalCommit,
	];
	if (request.reviewFile) {
		args.push('--review-file', request.reviewFile);
	}
	if (request.guidanceFile) {
		args.push('--guidance-file', request.guidanceFile);
	}
	if (request.failureDirectory) {
		args.push('--failure-directory', request.failureDirectory);
	}
	const result = await runWorkshop(extensionPath, args);
	const payload = parseCliJson(result.stdout);
	if (result.exitCode !== 0 || payload.status !== 'ok') {
		throw workshopFailure(
			vscode.l10n.t('Could not prepare provenance-safe GameTests.'),
			result.stderr,
			payload,
		);
	}
	return parseEpisodeTestPreparation(payload, request.finalCommit);
}

/** Verify that an exact passed_local artifact can be promoted without mutating the target. */
export async function preflightEpisodeTaskPublication(
	extensionPath: string,
	request: IEpisodeTaskPublicationRequest,
): Promise<IEpisodeTaskPublication> {
	return runEpisodeTaskPublication(extensionPath, request, true);
}

/** Commit and push the exact artifact authenticated by the passed_local report. */
export async function publishEpisodeTask(
	extensionPath: string,
	request: IEpisodeTaskPublicationRequest,
): Promise<IEpisodeTaskPublication> {
	return runEpisodeTaskPublication(extensionPath, request, false);
}

async function runEpisodeTaskPublication(
	extensionPath: string,
	request: IEpisodeTaskPublicationRequest,
	checkOnly: boolean,
): Promise<IEpisodeTaskPublication> {
	const args = [
		'publish-task',
		'--grade-report', request.gradeReportPath,
		'--repository', request.repositoryRoot,
		'--branch', request.branch,
	];
	if (checkOnly) {
		args.push('--check-only');
	}
	const result = await runWorkshop(extensionPath, args);
	const payload = parseCliJson(result.stdout);
	if (result.exitCode !== 0 && payload.status !== 'push_pending') {
		throw workshopFailure(
			vscode.l10n.t('Could not publish the passed SWE-Bench task.'),
			result.stderr,
			payload,
		);
	}
	const publication = parseEpisodeTaskPublication(
		payload,
		request.expectedArtifactFingerprint,
	);
	return publication;
}

export function parseEpisodeTaskPublication(
	payload: Record<string, unknown>,
	expectedArtifactFingerprint: string,
): IEpisodeTaskPublication {
	const status = nonEmptyString(payload.status);
	if (!status || !['ready', 'published', 'already_published', 'push_pending'].includes(status)) {
		throw new WorkshopCliError(vscode.l10n.t('Workshop returned an invalid task publication status.'));
	}
	const artifactFingerprint = sha256(payload.artifact_fingerprint);
	if (!artifactFingerprint || artifactFingerprint !== expectedArtifactFingerprint) {
		throw new WorkshopCliError(vscode.l10n.t('Task publication fingerprint does not match the graded artifact.'));
	}
	const taskName = nonEmptyString(payload.task);
	const destination = nonEmptyString(payload.destination);
	const repositoryRoot = nonEmptyString(payload.repository);
	const branch = nonEmptyString(payload.branch);
	if (!taskName || !destination || !repositoryRoot || !branch) {
		throw new WorkshopCliError(vscode.l10n.t('Workshop returned incomplete task publication metadata.'));
	}
	return {
		status: status as IEpisodeTaskPublication['status'],
		taskName,
		destination,
		repositoryRoot,
		branch,
		artifactFingerprint,
		commitSha: nonEmptyString(payload.commit),
		pushError: nonEmptyString(payload.push_error),
	};
}

/** Persist actionable qualitative test feedback for a provenance-safe revision. */
export async function prepareEpisodeGradeFeedback(
	repositoryRoot: string,
	sessionId: string,
	reportPath: string,
	artifact: IEpisodeTaskArtifact,
): Promise<IEpisodeGradeFeedback | undefined> {
	let payload: Record<string, unknown>;
	try {
		const parsed: unknown = JSON.parse(await fs.readFile(reportPath, 'utf8'));
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
			return undefined;
		}
		payload = parsed as Record<string, unknown>;
	} catch {
		return undefined;
	}
	const analysis = parseEpisodeGradeFeedback(payload, reportPath, artifact);
	if (!analysis || analysis.route === 'candidate_revision') {
		return analysis;
	}
	const review = analysis.review;
	if (!review) {
		return undefined;
	}
	const directory = path.join(
		repositoryRoot,
		WORKSHOP_DIRECTORY,
		sessionId,
		GRADE_FEEDBACK_DIRECTORY,
		artifact.artifactFingerprint,
	);
	const reviewPath = path.join(directory, TEST_REVIEW_FILE);
	const guidancePath = path.join(directory, TEST_GUIDANCE_FILE);
	await fs.mkdir(directory, { recursive: true });
	await Promise.all([
		fs.writeFile(reviewPath, review.endsWith('\n') ? review : `${review}\n`, 'utf8'),
		fs.writeFile(guidancePath, qualitativeTestGuidance(), 'utf8'),
	]);
	return { ...analysis, reviewPath, guidancePath };
}

/** Route qualitative grade feedback to either hidden tests or the task candidate. */
export function parseEpisodeGradeFeedback(
	payload: Record<string, unknown>,
	reportPath: string,
	artifact: IEpisodeTaskArtifact,
): EpisodeGradeFeedbackAnalysis | undefined {
	if (!matchesGradeArtifact(payload, reportPath, artifact)) {
		return undefined;
	}
	const commands = Array.isArray(payload.commands) ? payload.commands : [];
	for (const commandValue of [...commands].reverse()) {
		const command = record(commandValue);
		if (
			(command?.name !== 'validate' && command?.name !== 'validate_vanilla')
			|| typeof command.stdout !== 'string'
		) {
			continue;
		}
		let validation: Record<string, unknown> | undefined;
		try {
			validation = record(JSON.parse(command.stdout));
		} catch {
			continue;
		}
		const qualitative = record(validation?.qualitative);
		if (!qualitative || qualitative.verdict !== 'Revise') {
			continue;
		}
		const issues = (Array.isArray(qualitative.issues) ? qualitative.issues : [])
			.map(record)
			.filter((issue): issue is Record<string, unknown> => Boolean(issue))
			.map(parseQualitativeIssue);
		if (issues.length === 0) {
			return undefined;
		}
		const testIssues = issues.filter(issue => isTestIssue(issue));
		const materialCandidateIssues = issues.filter(issue => !isTestIssue(issue) && isMaterialIssue(issue));
		if (testIssues.length === 0 || materialCandidateIssues.length > 0) {
			return {
				route: 'candidate_revision',
				summary: [
					'Codimango qualitative validation found issues that require an implementation or instruction revision.',
					'',
					...issues.map(formatQualitativeIssue),
				].join('\n'),
			};
		}
		const contextualIssues = issues.filter(issue => isTestIssue(issue) || isSpecificationIssue(issue));
		return {
			route: 'test_revision',
			review: [
				'Codimango qualitative validation requested a hidden-GameTest revision.',
				'',
				...contextualIssues.map(formatQualitativeIssue),
			].join('\n'),
		};
	}
	return undefined;
}

/** Normalize one loosely typed qualitative issue. */
function parseQualitativeIssue(issue: Record<string, unknown>): IQualitativeIssue {
	return {
		severity: nonEmptyString(issue.severity) ?? 'Unspecified',
		category: nonEmptyString(issue.category) ?? 'Uncategorized',
		finding: nonEmptyString(issue.issue) ?? 'Qualitative validation issue',
		evidence: nonEmptyString(issue.evidence),
	};
}

/** Return whether an issue can be handled by hidden-test authorship. */
function isTestIssue(issue: IQualitativeIssue): boolean {
	return issue.category.toLowerCase().includes('test');
}

/** Return whether a non-blocking issue provides useful test-revision context. */
function isSpecificationIssue(issue: IQualitativeIssue): boolean {
	const category = issue.category.toLowerCase();
	return category.includes('spec') || category.includes('instruction');
}

/** Return whether an issue is too severe for an automatic test-only revision. */
function isMaterialIssue(issue: IQualitativeIssue): boolean {
	const severity = issue.severity.toLowerCase();
	return severity !== 'low' && severity !== 'info' && severity !== 'good';
}

/** Format one issue for the persisted revision brief or user-facing log. */
function formatQualitativeIssue(issue: IQualitativeIssue): string {
	return issue.evidence
		? `- ${issue.severity} ${issue.category}: ${issue.finding}\n  Evidence: ${issue.evidence}`
		: `- ${issue.severity} ${issue.category}: ${issue.finding}`;
}

function matchesGradeArtifact(
	payload: Record<string, unknown>,
	reportPath: string,
	artifact: IEpisodeTaskArtifact,
): boolean {
	const sourceTask = nonEmptyString(payload.source_task);
	const reportedPath = nonEmptyString(payload.report_path);
	const fingerprint = record(payload.artifact_fingerprint);
	return payload.status === 'revise'
		&& payload.verdict === 'revise'
		&& payload.task === artifact.taskName
		&& sourceTask !== undefined
		&& path.resolve(sourceTask) === path.resolve(artifact.taskDirectory)
		&& reportedPath !== undefined
		&& path.resolve(reportedPath) === path.resolve(reportPath)
		&& fingerprint?.verified === true
		&& sha256(fingerprint.expected_digest) === artifact.artifactFingerprint
		&& sha256(fingerprint.actual_digest) === artifact.artifactFingerprint;
}

/** Validate the commit identity returned by `prepare-tests`. */
export function parseEpisodeTestPreparation(
	payload: Record<string, unknown>,
	expectedRawCommit: string,
): IEpisodeTestPreparation {
	const action = payload.action;
	if (action !== 'prepared' && action !== 'validated') {
		throw new WorkshopCliError(vscode.l10n.t(
			'GameTest preparation reported an unsupported action: {0}.',
			String(action ?? 'missing'),
		));
	}
	const rawCommit = nonEmptyString(payload.raw_commit);
	const commitSha = nonEmptyString(payload.prepared_commit);
	const treeSha = nonEmptyString(payload.prepared_tree);
	const receiptPath = nonEmptyString(payload.receipt);
	const reviewPath = nonEmptyString(payload.review_path);
	const reviewSha256 = sha256(payload.review_sha256);
	if (!rawCommit || !commitSha || !treeSha || !receiptPath || !reviewPath || !reviewSha256) {
		throw new WorkshopCliError(vscode.l10n.t(
			'GameTest preparation completed without a raw commit, prepared commit, tree, receipt, or fingerprinted first-party review.',
		));
	}
	if (rawCommit !== expectedRawCommit) {
		throw new WorkshopCliError(vscode.l10n.t(
			'GameTest preparation used commit {0}, but Modernity expected {1}.',
			rawCommit.slice(0, 12),
			expectedRawCommit.slice(0, 12),
		));
	}
	return { action, commitSha, treeSha, receiptPath, reviewPath, reviewSha256 };
}

/** Derive the test matrix and materialize one unpacked Codimango task directory. */
export async function createEpisodeTaskArtifacts(
	extensionPath: string,
	request: IEpisodeTaskArtifactRequest,
	onProgress?: (message: string) => void,
): Promise<IEpisodeTaskArtifact> {
	onProgress?.(vscode.l10n.t('Deriving fail-to-pass and regression GameTests…'));
	const matrixResult = await runWorkshop(extensionPath, [
		'test-matrix',
		request.repositoryRoot,
		'--session-id', request.sessionId,
		'--final-commit', request.finalCommit,
	]);
	const matrix = parseCliJson(matrixResult.stdout);
	const matrixFailure = workshopCommandFailureDetail(matrixResult, matrix);
	if (matrixFailure) {
		throw new WorkshopCliError(vscode.l10n.t(
			'Could not derive the GameTest matrix: {0}',
			matrixFailure,
		));
	}
	if (matrixResult.exitCode !== 0 && typeof matrix.gradeable !== 'boolean') {
		throw new WorkshopCliError(vscode.l10n.t(
			'The GameTest matrix command failed with exit code {0} and did not report a matrix.',
			matrixResult.exitCode,
		));
	}
	const failToPass = stringList(matrix.fail_to_pass);
	const passToPass = stringList(matrix.pass_to_pass);
	if (matrix.gradeable !== true || failToPass.length === 0) {
		const rejected = recordStrings(matrix.rejected);
		const detail = Object.entries(rejected).map(([test, reason]) => `${test}: ${reason}`).join('; ');
		throw new WorkshopCliError(detail
			? vscode.l10n.t('The task is not gradeable: {0}', detail)
			: vscode.l10n.t('The task is not gradeable because no GameTest fails at the base and passes at the final commit.'));
	}

	const repository = repositoryIdentity(request.remoteName, request.projectSlug);
	const taskRepositoryRoot = path.join(path.dirname(request.repositoryRoot), `${request.projectSlug}-codimango`);
	const identity = authorIdentity();
	const followupFiles = await writeFollowupFiles(
		request.repositoryRoot,
		request.sessionId,
		request.followups ?? [],
	);
	const args = [
		'end', request.repositoryRoot,
		'--session-id', request.sessionId,
		'--final-commit', request.finalCommit,
		'--output', taskRepositoryRoot,
		'--prompt-file', episodeInstructionPath(request.repositoryRoot, request.sessionId),
		'--owner', repository.owner,
		'--repo', repository.name,
		'--unixname', identity.unixname,
		'--author-name', identity.authorName,
		'--author-email', identity.authorEmail,
		'--category-usecase', 'extend_behavior',
		'--difficulty', request.complexity === 'L' ? 'hard' : 'medium',
		'--toolchain-mode', 'self_contained',
		'--directory-only',
		'--auto-environment-version',
	];
	for (const followupFile of followupFiles) {
		args.push('--followup-file', followupFile);
	}
	for (const test of failToPass) {
		args.push('--fail-to-pass', test);
	}
	for (const test of passToPass) {
		args.push('--pass-to-pass', test);
	}

	onProgress?.(vscode.l10n.t('Writing the unpacked Codimango task…'));
	const emittedResult = await runWorkshop(extensionPath, args);
	const emitted = parseCliJson(emittedResult.stdout);
	const blockers = stringList(emitted.blockers);
	if (emittedResult.exitCode !== 0 || emitted.status !== 'ok' || blockers.length > 0) {
		throw workshopFailure(
			blockers.length > 0
				? vscode.l10n.t('Task emission is blocked: {0}', blockers.join('; '))
				: vscode.l10n.t('Could not emit the Codimango task.'),
			emittedResult.stderr,
			emitted,
		);
	}
	if (typeof emitted.directory !== 'string' || typeof emitted.task !== 'string') {
		throw new WorkshopCliError(vscode.l10n.t('Task emission completed without reporting its directory.'));
	}
	return parseEpisodeTaskArtifact({
		...emitted,
		trace_session_id: request.sessionId,
		fail_to_pass: failToPass,
		pass_to_pass: passToPass,
	}, emitted.directory, taskRepositoryRoot);
}

/** Resolve the newest verified task artifact that still belongs to this episode commit. */
export async function resolveEpisodeTaskArtifact(
	extensionPath: string,
	request: IEpisodeTaskResolutionRequest,
): Promise<IEpisodeTaskArtifact> {
	const args = [
		'resolve-task-artifact',
		'--project', request.repositoryRoot,
		'--session-id', request.expectedTraceSessionId,
		'--base-commit', request.expectedBaseCommit,
		'--final-commit', request.expectedFinalCommit,
	];
	if (request.taskRepositoryRoot) {
		args.push('--task-root', request.taskRepositoryRoot);
	}
	const result = await runWorkshop(extensionPath, args);
	const payload = parseCliJson(result.stdout);
	if (result.exitCode !== 0 || payload.status !== 'ok' || payload.verified !== true) {
		throw workshopFailure(vscode.l10n.t('Could not resolve a fingerprint-verified Codimango task artifact.'), result.stderr, payload);
	}
	const taskDirectory = nonEmptyString(payload.directory);
	const taskRepositoryRoot = nonEmptyString(payload.task_repository_root);
	if (!taskDirectory || !taskRepositoryRoot) {
		throw new WorkshopCliError(vscode.l10n.t('Task resolution completed without an artifact directory and repository root.'));
	}
	const artifact = parseEpisodeTaskArtifact(payload, taskDirectory, taskRepositoryRoot);
	if (
		artifact.baseCommit !== request.expectedBaseCommit
		|| artifact.finalCommit !== request.expectedFinalCommit
		|| artifact.traceSessionId !== request.expectedTraceSessionId
	) {
		throw new WorkshopCliError(vscode.l10n.t(
			'Task resolution returned an artifact for a different episode identity.',
		));
	}
	return artifact;
}

/** Parse one complete emitted or cryptographically verified task artifact contract. */
export function parseEpisodeTaskArtifact(
	payload: Record<string, unknown>,
	taskDirectory: string,
	taskRepositoryRoot: string,
): IEpisodeTaskArtifact {
	const taskName = nonEmptyString(payload.task);
	const baseCommit = nonEmptyString(payload.base_commit);
	const finalCommit = nonEmptyString(payload.final_commit);
	const traceSessionId = nonEmptyString(payload.trace_session_id);
	const environmentVersion = positiveInteger(payload.environment_version);
	const artifactFingerprint = parseArtifactFingerprint(payload.artifact_fingerprint);
	const testReviewPath = nonEmptyString(payload.test_review_path);
	const testReviewSha256 = sha256(payload.test_review_sha256);
	if (!taskName || !baseCommit || !finalCommit || !traceSessionId || !environmentVersion || !artifactFingerprint || !testReviewPath || !testReviewSha256) {
		throw new WorkshopCliError(vscode.l10n.t(
			'Task artifact metadata is missing a complete identity, artifact fingerprint, or first-party test review.',
		));
	}
	return {
		taskName,
		taskDirectory: path.resolve(taskDirectory),
		taskRepositoryRoot: path.resolve(taskRepositoryRoot),
		baseCommit,
		finalCommit,
		traceSessionId,
		environmentVersion,
		artifactFingerprint,
		testReviewPath: path.resolve(testReviewPath),
		testReviewSha256,
		failToPass: stringList(payload.fail_to_pass),
		passToPass: stringList(payload.pass_to_pass),
	};
}

/** Run the local Codimango quality panel for the current fingerprinted candidate. */
export async function gradeEpisodeTask(
	extensionPath: string,
	artifact: IEpisodeTaskArtifact,
	repositoryRoot: string,
	sessionId: string,
	onProgress?: (message: string) => void,
): Promise<IEpisodeTaskGrade> {
	onProgress?.(vscode.l10n.t('Running Codimango validation and solver benchmarks…'));
	const result = await runWorkshop(extensionPath, [
		'grade-task',
		artifact.taskDirectory,
		'--project', repositoryRoot,
		'--session-id', sessionId,
	]);
	const payload = parseCliJson(result.stdout);
	if (result.exitCode !== 0 && payload.status === 'fail') {
		throw workshopFailure(vscode.l10n.t('Codimango grading could not complete.'), result.stderr, payload);
	}
	if (typeof payload.report_path !== 'string' || typeof payload.status !== 'string') {
		throw new WorkshopCliError(vscode.l10n.t('Codimango grading completed without a grade report.'));
	}
	return {
		status: payload.status,
		reportPath: payload.report_path,
		taskDirectory: artifact.taskDirectory,
	};
}

function episodeInstructionPath(repositoryRoot: string, sessionId: string): string {
	return path.join(repositoryRoot, WORKSHOP_DIRECTORY, sessionId, INSTRUCTION_FILE);
}

async function writeFollowupFiles(
	repositoryRoot: string,
	sessionId: string,
	followups: readonly string[],
): Promise<readonly string[]> {
	const directory = path.join(repositoryRoot, WORKSHOP_DIRECTORY, sessionId);
	const files: string[] = [];
	for (const [index, followup] of followups.entries()) {
		const file = path.join(directory, `followup-${String(index + 1).padStart(3, '0')}.md`);
		await fs.writeFile(file, followup.endsWith('\n') ? followup : `${followup}\n`, 'utf8');
		files.push(file);
	}
	return files;
}

function authorIdentity(): { unixname: string; authorName: string; authorEmail: string } {
	const unixname = os.userInfo().username;
	return {
		unixname,
		authorName: unixname,
		authorEmail: `${unixname}@meta.com`,
	};
}

function repositoryIdentity(remoteName: string | undefined, projectSlug: string): { owner: string; name: string } {
	const [owner, name, ...extra] = remoteName?.split('/') ?? [];
	if (owner && name && extra.length === 0) {
		return { owner, name };
	}
	return { owner: 'codimango', name: projectSlug };
}

function stringList(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function nonEmptyString(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined;
}

function positiveInteger(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : undefined;
}

function parseArtifactFingerprint(value: unknown): string | undefined {
	const digest = typeof value === 'string'
		? value
		: value && typeof value === 'object' && !Array.isArray(value)
			? (value as Record<string, unknown>).digest
			: undefined;
	return sha256(digest);
}

function sha256(value: unknown): string | undefined {
	return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value) ? value : undefined;
}

function recordStrings(value: unknown): Record<string, string> {
	if (!value || typeof value !== 'object' || Array.isArray(value)) {
		return {};
	}
	return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === 'string'));
}

function record(value: unknown): Record<string, unknown> | undefined {
	return value && typeof value === 'object' && !Array.isArray(value)
		? value as Record<string, unknown>
		: undefined;
}

function qualitativeTestGuidance(): string {
	return [
		'Design black-box NeoForge GameTests for the user-visible feature.',
		'',
		'- Use only base-visible APIs plus runtime registry and resource lookup.',
		'- Do not require exact solution class, field, constant, or private method names.',
		'- Do not reflect over solution-only class or member names.',
		'- Do not require exact registry IDs unless the user instruction states them.',
		'- Do not invent thresholds, bounds, constants, or identifiers absent from the instruction; report a specification blocker instead.',
		'- Use collision-resistant hidden package, class, and runtime test identifiers that can coexist with reasonable solver-authored GameTests.',
		'- Never use a predictable feature-only test class name that a solver is likely to choose.',
		'- Prefer registered content and observable server-world state over structural presence.',
		'- Registry existence may support coverage, but it must not be the primary reward signal.',
		'- Never replace an unstated exact ID with acceptance of any object in the mod namespace.',
		'- Accept alternative class layouts, registry wiring, and internal architectures whenever their observable behavior satisfies the instruction.',
		'- Candidate discovery must be followed by feature-specific observable behavior.',
		'- Generic place/remove/persist, non-air, item-form, or hardness checks are not feature behavior.',
		'- Include deterministic server-visible behavior for the feature core, such as world placement, state transitions, persistence, or bounded trigger effects.',
		'- For every stated threshold or range, test just below, exactly at, and just above the boundary when those cases have distinct outcomes.',
		'- Prove mutation bounds non-vacuously with supported, mutable sentinels at and just outside the boundary; do not use sentinels normal behavior would ignore anyway.',
		'- For spatial/world-generation features, do not assume the GameTest origin intersects the feature; derive a bounded search from the implementation and use public placement or lookup results to locate one footprint.',
		'- Translate client-only requirements into their observable server-side trigger or payload state; do not attempt visual assertions.',
		'- Avoid probabilistic sampling. Test deterministic invariants or controlled state transitions instead.',
		'- Reject tautologies and weak assertions that any registered or non-air object would satisfy.',
		'- Do not expose a solution skeleton that empty stubs can satisfy.',
		'- Do not throw during class loading, static initialization, or GameTest registration.',
		'- Keep every test deterministic, bounded, base-compatible, and self-registering.',
		'- Every newly registered feature test must fail at base; pass-to-pass is only for tests already present at base.',
		'- Do not attempt client-only visual checks in the headless GameTest server.',
		'- Each fail-to-pass test must fail by a named runtime assertion at base and pass at final.',
		'- Map every mandatory instruction requirement to a named assertion, or explicitly record why it is untestable or out of scope.',
		'',
	].join('\n');
}

function workshopFailure(prefix: string, stderr: string, payload: Record<string, unknown>): WorkshopCliError {
	const detail = typeof payload.error === 'string' ? payload.error : stderr.trim();
	return new WorkshopCliError(detail ? `${prefix} ${detail}` : prefix);
}
