/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { execFile } from 'child_process';
import { createHash, randomUUID } from 'crypto';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import { getModernityBackendAccessToken, getModernitySessionAccessToken, MODERNITY_BACKEND_ACCESS_TOKEN_KEY } from './backendAuth';
import { ITraceEventRecord, writeEpisodeBundle } from './episodeBundle';
import { isSelectedRepositoryRoot, sameNamedBranchPushRefspec } from './episodeGit';
import { createPortablePatch, IPortablePatch } from './episodePortablePatch';
import {
	beginEpisodeTaskCapture,
	createEpisodeTaskArtifacts,
	discardEpisodeTaskCapture,
	gradeEpisodeTask,
	IEpisodeGradeFeedback,
	IEpisodeTaskArtifact,
	IEpisodeTaskPublication,
	IEpisodeTaskPublicationRequest,
	preflightEpisodeTaskPublication,
	prepareEpisodeGradeFeedback,
	prepareEpisodeTests,
	publishEpisodeTask,
	resolveEpisodeTaskArtifact,
} from './episodeTaskPipeline';
import { provisionModernityProject, refreshSandboxDaemonTraceAccessToken } from './sandboxTools';

const ACTIVE_EPISODE_KEY = 'modernity.benchmarkEpisodes.active';
const PROJECT_ID_KEY = 'modernity.benchmarkEpisodes.projectId';
const TRACE_SESSION_IDS_KEY = 'modernity.benchmarkEpisodes.traceSessionIds';
const PENDING_SETUP_KEY = 'modernity.benchmarkEpisodes.pendingProjectSetup';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_EXPORTED_TRACE_EVENTS = 20000;
const MAX_AUTOMATIC_TEST_REVISIONS = 1;
const PENDING_SETUP_TTL_MS = 24 * 60 * 60 * 1000;
// Trace-correction consumers locate interventions by this prefix in the transcript.
const HINT_MARKER = '[Hint]';
const TEMPLATE = {
	id: 'neoforge',
	version: '26.2',
	minecraftVersion: '26.2',
	neoforgeVersion: '26.2.0.7-beta',
	javaVersion: '25',
	gradleVersion: '9.2.1',
	defaultBranch: 'main',
} as const;

type EpisodeCategory = 'world_generation' | 'item_generation' | 'new_mechanic';
type EpisodeComplexity = 'S' | 'M' | 'L';
type GithubMode = 'local' | 'create' | 'link';
type EpisodeStage = 'active' | 'committed_pending_accept' | 'accepted' | 'accepted_sync_pending';

interface IChoice<T> extends vscode.QuickPickItem {
	readonly value: T;
}

interface IRepositorySummary {
	readonly github_repository_id: string;
	readonly installation_id: string;
	readonly owner: string;
	readonly name: string;
	readonly full_name: string;
	readonly visibility: string;
	readonly default_branch: string;
	readonly clone_url: string;
}

interface IProject {
	readonly id: string;
	readonly name: string;
	readonly slug: string;
	readonly default_branch: string | null;
	readonly repository: IRepositorySummary | null;
}

interface IEpisode {
	readonly id: string;
	readonly project_id: string;
	readonly trace_session_id: string;
	readonly task_id: string;
	readonly lifecycle_status: string;
	readonly final_git: Record<string, unknown>;
	readonly version: number;
}

interface ICheckpoint {
	readonly sequence: number;
	readonly ref: string;
	readonly commitSha: string;
	readonly treeSha: string;
	readonly createdAt: string;
}

interface ICorrectionSegment {
	readonly id: string;
	readonly ordinal: number;
	readonly kind: string;
	readonly label: string;
}

interface IPendingProjectSetup {
	readonly schemaVersion: 1;
	readonly folderPath: string;
	readonly projectId: string;
	readonly projectName: string;
	readonly prompt: string;
	readonly createdAt: string;
}

interface IActiveEpisode {
	readonly schemaVersion: 1;
	readonly workspaceUri: string;
	readonly repositoryRoot: string;
	readonly projectId: string;
	readonly episodeId: string;
	readonly taskId: string;
	readonly projectSlug?: string;
	readonly traceSessionId: string;
	/** The chat that ran /swe-session; Grade and Submit are offered only there. */
	readonly chatSessionId: string;
	readonly prompt: string;
	readonly model: string;
	readonly category: EpisodeCategory;
	readonly complexity: EpisodeComplexity;
	readonly baseBranch: string;
	readonly branch: string;
	readonly baseCommit: string;
	readonly baseTree: string;
	readonly startedAt: string;
	readonly githubMode: GithubMode;
	readonly remoteName?: string;
	readonly checkpoints: readonly ICheckpoint[];
	readonly checkpointSequence: number;
	readonly version: number;
	readonly stage: EpisodeStage;
	readonly finalCommitSha?: string;
	readonly finalTreeSha?: string;
	readonly taskName?: string;
	readonly taskDirectory?: string;
	readonly taskRepositoryRoot?: string;
	readonly taskBaseCommit?: string;
	readonly taskFinalCommit?: string;
	readonly taskTraceSessionId?: string;
	readonly taskEnvironmentVersion?: number;
	readonly artifactFingerprint?: string;
	readonly failToPass?: readonly string[];
	readonly passToPass?: readonly string[];
	readonly firstPartyTestReviewPath?: string;
	readonly firstPartyTestReviewSha256?: string;
	readonly gradeStatus?: string;
	readonly gradeReportPath?: string;
	readonly taskPublication?: IEpisodeTaskPublication;
	readonly followups?: readonly string[];
}

interface IBeginSweSessionRequest {
	readonly prompt: string;
	readonly sessionId: string;
	readonly modelId?: string;
}

interface IEpisodeCommandRequest {
	readonly sessionId?: string;
}

interface IPreparedEpisodeCandidate {
	readonly active: IActiveEpisode;
	readonly artifact: IEpisodeTaskArtifact;
}

interface IProcessResult {
	readonly stdout: string;
	readonly stderr: string;
}

interface IProcessOptions {
	readonly cwd: string;
	readonly env?: NodeJS.ProcessEnv;
}

class ProcessFailure extends Error {
	constructor(
		message: string,
		readonly stdout: string,
		readonly stderr: string,
	) {
		super(message);
	}
}

class UserCancelledError extends Error { }

/** Setup continues in a reloaded window, so this chat cannot finish the episode. */
class ProjectSetupRestart extends Error { }

class ModernityApiError extends Error {
	constructor(
		message: string,
		readonly status: number,
		readonly code?: string,
	) {
		super(message);
	}
}

class ModernityApiClient {
	constructor(private readonly context: vscode.ExtensionContext) { }

	async setAccessToken(): Promise<boolean> {
		const value = await vscode.window.showInputBox({
			title: vscode.l10n.t('Modernity Backend Access Token'),
			prompt: vscode.l10n.t('Signing in from the Accounts menu is the usual path; this override is for a backend your signed-in account cannot reach. The token is stored in VS Code Secret Storage.'),
			password: true,
			ignoreFocusOut: true,
			validateInput: input => input.trim() ? undefined : vscode.l10n.t('An access token is required.'),
		});
		if (!value) {
			return false;
		}
		const token = value.trim();
		await this.context.secrets.store(MODERNITY_BACKEND_ACCESS_TOKEN_KEY, token);
		await refreshSandboxDaemonTraceAccessToken(this.context, token);
		return true;
	}

	async getProject(projectId: string): Promise<IProject> {
		return (await this.request<{ project: IProject }>(`/api/v1/projects/${encodeURIComponent(projectId)}`)).project;
	}

	async listProjects(): Promise<readonly IProject[]> {
		return (await this.request<{ items: readonly IProject[] }>('/api/v1/projects?limit=100')).items;
	}

	async createProject(body: object, idempotencyKey: string): Promise<IProject> {
		return (await this.request<{ project: IProject }>('/api/v1/projects', {
			method: 'POST',
			headers: { 'Idempotency-Key': idempotencyKey },
			body: JSON.stringify(body),
		})).project;
	}

	async createTraceSession(sessionId: string, projectId: string): Promise<void> {
		await this.request('/api/v1/traces/sessions', {
			method: 'POST',
			body: JSON.stringify({
				session_id: sessionId,
				identity_type: 'chat',
				project_id: projectId,
				content_policy: 'messages',
			}),
		});
	}

	async createEpisode(projectId: string, body: object): Promise<IEpisode> {
		return (await this.request<{ episode: IEpisode }>(`/api/v1/projects/${encodeURIComponent(projectId)}/episodes`, {
			method: 'POST',
			body: JSON.stringify(body),
		})).episode;
	}

	async acceptEpisode(episodeId: string, version: number, body: object): Promise<IEpisode> {
		return (await this.request<{ episode: IEpisode }>(`/api/v1/episodes/${encodeURIComponent(episodeId)}/accept`, {
			method: 'POST',
			headers: { 'If-Match': String(version) },
			body: JSON.stringify(body),
		})).episode;
	}

	async getEpisode(episodeId: string): Promise<IEpisode> {
		return (await this.request<{ episode: IEpisode }>(`/api/v1/episodes/${encodeURIComponent(episodeId)}`)).episode;
	}

	async listTraceEvents(sessionId: string): Promise<readonly ITraceEventRecord[]> {
		const events: ITraceEventRecord[] = [];
		let cursor: string | null = null;
		do {
			const query = new URLSearchParams({ limit: '100' });
			if (cursor !== null) {
				query.set('cursor', cursor);
			}
			const page: { items: readonly ITraceEventRecord[]; next_cursor: string | null } = await this.request(
				`/api/v1/traces/sessions/${encodeURIComponent(sessionId)}/events?${query}`,
			);
			events.push(...page.items);
			cursor = page.next_cursor;
		} while (cursor !== null && events.length < MAX_EXPORTED_TRACE_EVENTS);
		return events;
	}

	async addCorrection(episodeId: string, body: object): Promise<ICorrectionSegment> {
		return (await this.request<{ segment: ICorrectionSegment }>(
			`/api/v1/episodes/${encodeURIComponent(episodeId)}/corrections`,
			{ method: 'POST', body: JSON.stringify(body) },
		)).segment;
	}

	async listCorrections(episodeId: string): Promise<readonly object[]> {
		return (await this.request<{ items: readonly object[] }>(
			`/api/v1/episodes/${encodeURIComponent(episodeId)}/corrections`,
		)).items;
	}

	async getRepositoryCredential(projectId: string): Promise<{ username: string; password: string }> {
		return this.request<{ username: string; password: string }>(`/api/v1/projects/${encodeURIComponent(projectId)}/repository/git-credential`, {
			method: 'POST',
		});
	}

	private async request<T = object>(route: string, init?: RequestInit, allowRetry = true): Promise<T> {
		const token = await getModernityBackendAccessToken(this.context);
		if (!token) {
			const configured = await this.setAccessToken();
			if (!configured) {
				throw new UserCancelledError();
			}
			return this.request<T>(route, init, allowRetry);
		}
		const baseUrl = getBackendBaseUrl();
		const response = await fetch(`${baseUrl}${route}`, {
			...init,
			headers: {
				'Accept': 'application/json',
				'Authorization': `Bearer ${token}`,
				...(init?.body ? { 'Content-Type': 'application/json' } : {}),
				...init?.headers,
			},
		});
		if (!response.ok) {
			let message = response.statusText || vscode.l10n.t('Modernity request failed.');
			let code: string | undefined;
			try {
				const body = await response.json() as { error?: { message?: string; code?: string }; detail?: string; message?: string };
				message = body.error?.message ?? body.detail ?? body.message ?? message;
				code = body.error?.code;
			} catch {
				// The status and status text still provide a useful diagnostic.
			}
			if (response.status === 401) {
				// The signed-in account refreshes itself, so retry once with whatever it
				// now holds before blaming the user's credentials.
				const session = await getModernitySessionAccessToken();
				if (session) {
					if (allowRetry && session !== token) {
						return this.request<T>(route, init, false);
					}
					message = vscode.l10n.t('Your Modernity sign-in is no longer valid. Sign out and back in from the Accounts menu, then try again.');
				} else {
					await this.context.secrets.delete(MODERNITY_BACKEND_ACCESS_TOKEN_KEY);
					message = vscode.l10n.t('You are not signed in to Modernity. Sign in from the Accounts menu, or run "Modernity: Set Backend Access Token".');
				}
			}
			throw new ModernityApiError(message, response.status, code);
		}
		if (response.status === 204) {
			// The caller chose a no-content endpoint, so the generic result is intentionally empty.
			// eslint-disable-next-line local/code-no-dangerous-type-assertions
			return {} as T;
		}
		return await response.json() as T;
	}
}

class GitEpisodeRepository {
	constructor(readonly root: string) { }

	static async openOrInitialize(folder: vscode.WorkspaceFolder): Promise<GitEpisodeRepository> {
		const selectedRealPath = await fs.realpath(folder.uri.fsPath);
		let gitRoot: string | undefined;
		try {
			gitRoot = (await runGit(folder.uri.fsPath, ['rev-parse', '--show-toplevel'])).stdout.trim();
		} catch {
			// A missing repository is handled by the explicit initialization flow below.
		}

		let root: string;
		if (gitRoot) {
			const repositoryRealPath = await fs.realpath(gitRoot);
			if (!isSelectedRepositoryRoot(selectedRealPath, repositoryRealPath)) {
				root = await GitEpisodeRepository.initializeIsolatedRepository(
					folder,
					selectedRealPath,
					vscode.l10n.t('This mod folder is inside the parent Git repository `{0}`. Initialize an isolated nested repository here before creating its immutable benchmark baseline?', repositoryRealPath),
				);
			} else {
				root = repositoryRealPath;
			}
		} else {
			root = await GitEpisodeRepository.initializeIsolatedRepository(
				folder,
				selectedRealPath,
				vscode.l10n.t('Benchmark episodes require Git. Initialize this folder and create its immutable baseline commit?'),
			);
		}

		const repository = new GitEpisodeRepository(root);
		if (!(await repository.hasHead())) {
			await GitEpisodeRepository.commitBaseline(root);
		}
		await repository.settleWorktree();
		return repository;
	}

	/**
	 * Fold pre-existing edits into the baseline, or set them aside.
	 *
	 * An episode has to start from an immutable commit: work that was already in the
	 * worktree was not produced by the traced session, so it must not end up inside
	 * the accepted feature commit as if the agent had written it.
	 */
	async settleWorktree(): Promise<void> {
		let status = await this.status();
		if (status.length === 0) {
			return;
		}
		const commit = vscode.l10n.t('Commit as Baseline');
		const stash = vscode.l10n.t('Stash Changes');
		const chosen = await vscode.window.showWarningMessage(
			vscode.l10n.t("This project has {0} uncommitted {1}. A collection session must start from a clean commit so that only the agent's work lands in the feature commit.", status.length, status.length === 1 ? 'change' : 'changes'),
			{
				modal: true,
				detail: vscode.l10n.t(
					'Commit as Baseline keeps the work and starts the session on top of it.\nStash Changes sets it aside in `git stash` so you can restore it later.\n\n{0}',
					status.slice(0, 20).join('\n'),
				),
			},
			commit,
			stash,
		);
		if (chosen === commit) {
			await runGit(this.root, ['add', '-A']);
			await runGit(this.root, commitIdentityArguments([
				'commit', '--no-verify', '-m', 'chore: baseline before Modernity data collection',
			]));
		} else if (chosen === stash) {
			await runGit(this.root, ['stash', 'push', '--include-untracked', '-m', 'Modernity: set aside before data collection']);
		} else {
			throw new UserCancelledError();
		}

		status = await this.status();
		if (status.length > 0) {
			throw new Error(vscode.l10n.t('The project is still not clean: {0}', status.slice(0, 8).join(', ')));
		}
	}

	private static async initializeIsolatedRepository(folder: vscode.WorkspaceFolder, selectedRealPath: string, prompt: string): Promise<string> {
		const initialize = await vscode.window.showInformationMessage(
			prompt,
			{ modal: true },
			vscode.l10n.t('Initialize Isolated Repository'),
		);
		if (!initialize) {
			throw new UserCancelledError();
		}
		await runGit(folder.uri.fsPath, ['init', '-b', 'main']);
		const initializedRoot = (await runGit(folder.uri.fsPath, ['rev-parse', '--show-toplevel'])).stdout.trim();
		const initializedRealPath = await fs.realpath(initializedRoot);
		if (!isSelectedRepositoryRoot(selectedRealPath, initializedRealPath)) {
			throw new Error(vscode.l10n.t('Git initialization did not isolate the selected folder. No files were added; open `{0}` as a standalone repository and try again.', selectedRealPath));
		}
		await GitEpisodeRepository.commitBaseline(initializedRealPath);
		return initializedRealPath;
	}

	private static async commitBaseline(root: string): Promise<void> {
		await runGit(root, ['add', '-A']);
		await runGit(root, commitIdentityArguments(['commit', '--no-verify', '--allow-empty', '-m', 'Initial Modernity project']));
	}

	async status(): Promise<readonly string[]> {
		const output = (await runGit(this.root, ['status', '--porcelain=v1', '--untracked-files=all'])).stdout;
		return output.split('\n').filter(Boolean);
	}

	async hasHead(): Promise<boolean> {
		try {
			await runGit(this.root, ['rev-parse', '--verify', 'HEAD']);
			return true;
		} catch {
			return false;
		}
	}

	async head(): Promise<string> {
		return (await runGit(this.root, ['rev-parse', 'HEAD'])).stdout.trim();
	}

	async tree(revision = 'HEAD'): Promise<string> {
		return (await runGit(this.root, ['rev-parse', `${revision}^{tree}`])).stdout.trim();
	}

	async branch(): Promise<string> {
		return (await runGit(this.root, ['symbolic-ref', '--short', 'HEAD'])).stdout.trim();
	}

	async createEpisodeBranch(branch: string): Promise<void> {
		await runGit(this.root, ['switch', '-c', branch]);
	}

	async discardUnstartedEpisodeBranch(baseBranch: string, episodeBranch: string, baseCommit: string): Promise<void> {
		if (await this.branch() !== episodeBranch || await this.head() !== baseCommit || (await this.status()).length > 0) {
			return;
		}
		await runGit(this.root, ['switch', baseBranch]);
		await runGit(this.root, ['branch', '-D', episodeBranch]);
	}

	async createCheckpoint(episodeId: string, sequence: number, storageRoot: string): Promise<ICheckpoint> {
		const indexDirectory = path.join(storageRoot, 'episode-indices');
		await fs.mkdir(indexDirectory, { recursive: true });
		const indexPath = path.join(indexDirectory, `${episodeId}-${sequence}.index`);
		await fs.rm(indexPath, { force: true });
		const environment: NodeJS.ProcessEnv = {
			...process.env,
			GIT_INDEX_FILE: indexPath,
			GIT_AUTHOR_NAME: 'Modernity Checkpoint',
			GIT_AUTHOR_EMAIL: 'modernity@users.noreply.github.com',
			GIT_COMMITTER_NAME: 'Modernity Checkpoint',
			GIT_COMMITTER_EMAIL: 'modernity@users.noreply.github.com',
		};
		try {
			await runGit(this.root, ['read-tree', 'HEAD'], environment);
			await runGit(this.root, ['add', '-A'], environment);
			const treeSha = (await runGit(this.root, ['write-tree'], environment)).stdout.trim();
			const parent = await this.head();
			const commitSha = (await runGit(this.root, ['commit-tree', treeSha, '-p', parent, '-m', `Modernity episode checkpoint ${sequence}`], environment)).stdout.trim();
			const ref = `refs/modernity/episodes/${episodeId}/checkpoints/${sequence}`;
			await runGit(this.root, ['update-ref', ref, commitSha]);
			return { sequence, ref, commitSha, treeSha, createdAt: new Date().toISOString() };
		} finally {
			await fs.rm(indexPath, { force: true });
		}
	}

	async commitFeature(message: string): Promise<{ commitSha: string; treeSha: string }> {
		await runGit(this.root, ['add', '-A']);
		await runGit(this.root, commitIdentityArguments(['commit', '--no-verify', '-m', message]));
		return { commitSha: await this.head(), treeSha: await this.tree() };
	}

	async amendFeature(): Promise<{ commitSha: string; treeSha: string }> {
		await runGit(this.root, ['add', '-A']);
		await runGit(this.root, commitIdentityArguments(['commit', '--amend', '--no-edit', '--no-verify']));
		return { commitSha: await this.head(), treeSha: await this.tree() };
	}

	async changedFiles(base: string, revision = 'HEAD'): Promise<readonly string[]> {
		const output = (await runGit(this.root, ['diff', '--name-only', `${base}..${revision}`])).stdout;
		return output.split('\n').filter(Boolean);
	}

	async diffStat(base: string, revision = 'HEAD'): Promise<string> {
		return (await runGit(this.root, ['diff', '--stat', `${base}..${revision}`])).stdout.trim();
	}

	async configureRemote(repository: IRepositorySummary): Promise<void> {
		let origin: string | undefined;
		try {
			origin = (await runGit(this.root, ['remote', 'get-url', 'origin'])).stdout.trim();
		} catch {
			// A missing origin is expected for new local projects.
		}
		if (!origin) {
			await runGit(this.root, ['remote', 'add', 'origin', repository.clone_url]);
			return;
		}
		if (normalizeRemote(origin) !== normalizeRemote(repository.clone_url)) {
			throw new Error(vscode.l10n.t('The existing origin remote does not match {0}.', repository.full_name));
		}
	}

	async portablePatch(base: string, revision: string, contentLimit: number): Promise<IPortablePatch> {
		const patch = (await runGit(this.root, ['diff', '--binary', '--full-index', base, revision])).stdout;
		return createPortablePatch(revision, patch, contentLimit);
	}

	async portableCheckpointPatches(base: string, checkpoints: readonly ICheckpoint[]): Promise<readonly object[]> {
		let remainingBytes = 512 * 1024;
		const snapshots: object[] = [];
		for (const checkpoint of checkpoints) {
			const limit = Math.min(64 * 1024, remainingBytes);
			const portable = await this.portablePatch(base, checkpoint.commitSha, Math.max(0, limit));
			if (portable.content) {
				remainingBytes -= Buffer.byteLength(portable.content, 'utf8');
			}
			snapshots.push({
				sequence: checkpoint.sequence,
				ref: checkpoint.ref,
				tree_sha: checkpoint.treeSha,
				...portable,
			});
		}
		return snapshots;
	}

	async pushEpisode(branch: string, credential: { username: string; password: string }): Promise<void> {
		await runGit(this.root, [
			'push',
			'--set-upstream',
			'origin',
			sameNamedBranchPushRefspec(branch),
		], gitCredentialEnvironment(credential));
	}

	async isBranchPublished(branch: string, credential: { username: string; password: string }): Promise<boolean> {
		return await this.remoteHead(branch, credential) === await this.head();
	}

	/**
	 * Publish the local baseline, fast-forwarding the remote when it is behind.
	 *
	 * Local commits the remote has not seen are the normal case; only a remote that
	 * carries commits this baseline lacks is a genuine conflict to reconcile.
	 */
	async pushBaseline(branch: string, credential: { username: string; password: string }): Promise<void> {
		const remoteHead = await this.remoteHead(branch, credential);
		const localHead = await this.head();
		if (remoteHead === localHead) {
			return;
		}
		if (remoteHead && !(await this.isAncestor(remoteHead, localHead))) {
			throw new Error(vscode.l10n.t('The GitHub branch `{0}` has commits that this local baseline does not contain ({1}). Pull or reconcile that repository before starting a session.', branch, remoteHead.slice(0, 12)));
		}
		await runGit(this.root, ['push', 'origin', sameNamedBranchPushRefspec(branch)], gitCredentialEnvironment(credential));
	}

	/** True when `ancestor` is reachable from `descendant` in local history. */
	private async isAncestor(ancestor: string, descendant: string): Promise<boolean> {
		try {
			await runGit(this.root, ['merge-base', '--is-ancestor', ancestor, descendant]);
			return true;
		} catch {
			// A non-zero exit means "not an ancestor"; an unknown object means the
			// remote commit is not in this history, which is also a conflict.
			return false;
		}
	}

	private async remoteHead(branch: string, credential: { username: string; password: string }): Promise<string | undefined> {
		const output = (await runGit(this.root, ['ls-remote', '--heads', 'origin', `refs/heads/${branch}`], gitCredentialEnvironment(credential))).stdout.trim();
		return output ? output.split(/\s+/)[0] : undefined;
	}
}

class EpisodeWorkflow implements IEpisodeWorkflow {
	private readonly api: ModernityApiClient;
	private readonly disposables: vscode.Disposable[] = [];
	private active: IActiveEpisode | undefined;
	private watcher: vscode.FileSystemWatcher | undefined;
	private checkpointTimer: NodeJS.Timeout | undefined;
	private checkpointChain = Promise.resolve();
	private finalizationRunning = false;
	private readonly collectDataStatus: vscode.StatusBarItem;

	constructor(
		private readonly context: vscode.ExtensionContext,
		private readonly output: vscode.LogOutputChannel,
	) {
		this.api = new ModernityApiClient(context);
		this.active = context.workspaceState.get<IActiveEpisode>(ACTIVE_EPISODE_KEY);
		this.collectDataStatus = vscode.window.createStatusBarItem('modernity.collectData', vscode.StatusBarAlignment.Right, 99);
		this.collectDataStatus.name = vscode.l10n.t('Modernity Collect Data');
		this.collectDataStatus.command = 'modernity.toggleCollectData';
		this.disposables.push(this.collectDataStatus);
		this.disposables.push(vscode.workspace.onDidChangeConfiguration(change => {
			if (change.affectsConfiguration('modernity.benchmarkEpisodes.enabled')) {
				this.refreshCollectDataStatus();
			}
		}));
		this.registerCommands();
		this.refreshCollectDataStatus();
		void this.refreshContext();
		void this.resumePendingProjectSetup();
		if (isCandidateStage(this.active?.stage)) {
			this.startWatcher();
		}
	}

	dispose(): void {
		this.stopWatcher();
		for (const disposable of this.disposables) {
			disposable.dispose();
		}
	}

	isBenchmarkEpisodeSession(sessionId: string): boolean {
		return this.context.workspaceState.get<readonly string[]>(TRACE_SESSION_IDS_KEY, []).includes(canonicalUuid(sessionId));
	}

	private registerCommands(): void {
		const participant = vscode.chat.createChatParticipant('modernity.episodes', async (request, _chatContext, stream) => {
			if (request.command === 'start-project') {
				await this.createProject(request.prompt);
				stream.markdown(vscode.l10n.t('The new project wizard uses Modernity\'s pinned NeoForge template.'));
				return;
			}
			if (request.command === 'hint') {
				if (this.active?.chatSessionId !== request.sessionId) {
					stream.markdown(vscode.l10n.t('Hints belong to the chat that ran `/swe-session`. Open that session to steer its agent.'));
					return;
				}
				try {
					const segment = await this.addHint(request.prompt);
					if (!segment) {
						stream.markdown(vscode.l10n.t('Add the guidance after the command, for example `@modernity /hint use the existing validate() in utils.java`.'));
						return;
					}
					stream.markdown(vscode.l10n.t('Recorded hint #{0} and sent it to the agent.', segment.ordinal));
					stream.button({ command: 'modernity.gradeFeature', title: vscode.l10n.t('Grade') });
				} catch (error) {
					stream.markdown(vscode.l10n.t('The hint was not recorded: `{0}`', escapeMarkdown(error instanceof Error ? error.message : String(error))));
				}
				return;
			}
			// Re-offer the current lifecycle action inside the collecting chat; setup is a global
			// preflight slash command so the normal Agent handles the feature prompt.
			if (this.isEnabled() && this.active && isCandidateStage(this.active.stage) && this.active.chatSessionId === request.sessionId) {
				if (this.active.stage === 'committed_pending_accept' && this.active.gradeStatus === 'passed_local') {
					stream.markdown(vscode.l10n.t('Candidate `{0}` passed the local Codimango panel. Review the report, then use `/submit` to seal the episode.', this.active.taskId));
					stream.button({ command: 'modernity.acceptFeature', title: vscode.l10n.t('Submit') });
					return;
				}
				stream.markdown(vscode.l10n.t('Collecting `{0}` on branch `{1}`. Steer with `/hint <guidance>`, then use `/grade` to build and benchmark the current candidate. Use `/submit` only after the candidate passes local grading.', this.active.taskId, this.active.branch));
				stream.button({ command: 'modernity.gradeFeature', title: vscode.l10n.t('Grade') });
				return;
			}
			stream.markdown(vscode.l10n.t('Use `/swe-session <feature>` in Agent mode to collect a normal implementation session.'));
		});
		this.disposables.push(participant);
		this.disposables.push(vscode.commands.registerCommand('modernity.sweSession', () => this.openNewEpisodeChat()));
		this.disposables.push(vscode.commands.registerCommand('modernity.beginSweSession', async (request: IBeginSweSessionRequest) => {
			if (!request?.prompt?.trim() || !request.sessionId) {
				throw new Error(vscode.l10n.t('A feature prompt and chat session are required.'));
			}
			if (!this.isEnabled()) {
				await this.setCollectData(true);
			}
			return vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('Preparing benchmark collection…'),
			}, () => this.startEpisode(request.prompt, request.sessionId, request.modelId ?? 'unrecorded'));
		}));
		this.disposables.push(vscode.commands.registerCommand('modernity.enableBenchmarkEpisodes', async () => {
			await this.setCollectData(true);
			await this.openNewEpisodeChat();
		}));
		this.disposables.push(vscode.commands.registerCommand('modernity.toggleCollectData', () => this.toggleCollectData()));
		this.disposables.push(vscode.commands.registerCommand('modernity.createProject', (suggestedName?: string) => this.createProject(suggestedName)));
		this.disposables.push(vscode.commands.registerCommand('modernity.continueFeature', async (prompt?: string) => {
			const initialPrompt = prompt || this.active?.prompt;
			if (initialPrompt) {
				await vscode.commands.executeCommand('workbench.action.chat.open', { mode: 'agent', query: initialPrompt });
			}
		}));
		this.disposables.push(vscode.commands.registerCommand('modernity.addHint', () => this.promptForHint()));
		this.disposables.push(vscode.commands.registerCommand('modernity.acceptFeature', () => this.submitFeature()));
		this.disposables.push(vscode.commands.registerCommand('modernity.submitFeature', (request?: IEpisodeCommandRequest) => this.submitFeature(request)));
		this.disposables.push(vscode.commands.registerCommand('modernity.gradeFeature', (request?: IEpisodeCommandRequest) => this.gradeFeature(request)));
		this.disposables.push(vscode.commands.registerCommand('modernity.syncAcceptedFeature', () => this.syncAcceptedFeature()));
		this.disposables.push(vscode.commands.registerCommand('modernity.openProjectViewer', () => this.openProjectViewer()));
		this.disposables.push(vscode.commands.registerCommand('modernity.openEpisodeTrace', () => this.openTraceViewer()));
		this.disposables.push(vscode.commands.registerCommand('modernity.setBackendAccessToken', async () => {
			if (await this.api.setAccessToken()) {
				void vscode.window.showInformationMessage(vscode.l10n.t('Modernity access token saved securely.'));
			}
		}));
	}

	private async openNewEpisodeChat(prompt = ''): Promise<void> {
		const query = prompt.trim() ? `/swe-session ${prompt.trim()}` : '/swe-session ';
		await vscode.commands.executeCommand('workbench.action.chat.newChat');
		await vscode.commands.executeCommand('workbench.action.chat.open', { mode: 'agent', query, isPartialQuery: !prompt.trim() });
	}

	private async startEpisode(initialPrompt: string, chatSessionId: string, model: string): Promise<IActiveEpisode> {
		if (this.active && (this.active.stage === 'active' || this.active.stage === 'committed_pending_accept' || this.active.stage === 'accepted_sync_pending')) {
			throw new Error(vscode.l10n.t('This workspace already has an active episode. Accept it before starting another feature.'));
		}
		const folders = vscode.workspace.workspaceFolders ?? [];
		if (folders.length === 0) {
			throw new Error(vscode.l10n.t('No mod project is open. Run `/start-project` first, then start the SWE session in that project.'));
		}
		const folder = await chooseWorkspaceFolder(folders);
		const repository = await GitEpisodeRepository.openOrInitialize(folder);
		const prompt = initialPrompt || await requiredInput({
			title: vscode.l10n.t('Initial Feature Prompt'),
			prompt: vscode.l10n.t('Describe the one mod feature this session should implement.'),
			placeHolder: vscode.l10n.t('Add a mana system with regeneration and spell costs'),
		});
		const category = await chooseCategory();
		const complexity = await chooseComplexity();
		let project = await this.resolveProject(folder, repository);
		const remote = project.repository ?? undefined;
		const githubMode: GithubMode = remote ? 'link' : 'local';
		if (remote) {
			await repository.configureRemote(remote);
			const credential = await this.api.getRepositoryCredential(project.id);
			const currentBranch = await repository.branch();
			if (!(await repository.isBranchPublished(currentBranch, credential))) {
				await repository.pushBaseline(currentBranch, credential);
			}
			project = await this.api.getProject(project.id);
		}

		const baseCommit = await repository.head();
		const baseTree = await repository.tree();
		const baseBranch = await repository.branch();
		const traceSessionId = canonicalUuid(chatSessionId);
		const taskId = `${project.slug}-${new Date().toISOString().slice(0, 10)}-${randomUUID().slice(0, 8)}`;
		const branch = `modernity/episode/${taskId}`;
		const startedAt = new Date().toISOString();
		let episode: IEpisode;
		try {
			await beginEpisodeTaskCapture(this.context.extensionPath, {
				repositoryRoot: repository.root,
				sessionId: traceSessionId,
				model,
				prompt,
				expectedBaseCommit: baseCommit,
			});
			await repository.createEpisodeBranch(branch);
			await this.api.createTraceSession(traceSessionId, project.id);
			episode = await this.api.createEpisode(project.id, {
				trace_session_id: traceSessionId,
				task_id: taskId,
				category,
				prompt,
				rubric: {},
				complexity,
				outputs: {},
				human_judgement: null,
				model,
				platform_augmented: true,
				token: 0,
				completeness: false,
				speed: 0,
				checkpoint: baseCommit,
				base_git: {
					commit_sha: baseCommit,
					tree_sha: baseTree,
					branch: baseBranch,
					...(remote ? { repository: remote.full_name } : {}),
				},
				environment: await environmentManifest(this.context, repository),
			});
		} catch (error) {
			await discardEpisodeTaskCapture(repository.root, traceSessionId).catch(cleanupError => {
				this.output.warn(`Could not clean up unstarted workshop capture: ${cleanupError instanceof Error ? cleanupError.message : cleanupError}`);
			});
			try {
				await repository.discardUnstartedEpisodeBranch(baseBranch, branch, baseCommit);
			} catch (cleanupError) {
				this.output.warn(`Could not clean up unstarted episode branch: ${cleanupError instanceof Error ? cleanupError.message : cleanupError}`);
			}
			throw error;
		}

		this.active = {
			schemaVersion: 1,
			workspaceUri: folder.uri.toString(),
			repositoryRoot: repository.root,
			projectId: project.id,
			episodeId: episode.id,
			taskId,
			projectSlug: project.slug,
			traceSessionId,
			chatSessionId,
			prompt,
			model,
			category,
			complexity,
			baseBranch,
			branch,
			baseCommit,
			baseTree,
			startedAt,
			githubMode,
			remoteName: remote?.full_name,
			checkpoints: [],
			checkpointSequence: 0,
			version: episode.version,
			stage: 'active',
		};
		await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, this.active);
		const traceSessionIds = this.context.workspaceState.get<readonly string[]>(TRACE_SESSION_IDS_KEY, []);
		await this.context.workspaceState.update(TRACE_SESSION_IDS_KEY, [...new Set([...traceSessionIds, traceSessionId])].slice(-100));
		await this.context.workspaceState.update(PROJECT_ID_KEY, project.id);
		await this.refreshContext();
		this.startWatcher();
		return this.active;
	}

	private async resolveProject(folder: vscode.WorkspaceFolder, repository: GitEpisodeRepository): Promise<IProject> {
		const associatedId = this.context.workspaceState.get<string>(PROJECT_ID_KEY) ?? await readManifestProjectId(folder.uri.fsPath);
		if (associatedId) {
			try {
				const existing = await this.api.getProject(associatedId);
				await this.context.workspaceState.update(PROJECT_ID_KEY, existing.id);
				return existing;
			} catch (error) {
				if (!(error instanceof ModernityApiError) || error.status !== 404) {
					throw error;
				}
			}
		}

		const name = await requiredInput({
			title: vscode.l10n.t('Modernity Project Name'),
			prompt: vscode.l10n.t('Name the mod project represented by this repository.'),
			value: humanize(folder.name),
		});
		const modId = await chooseModId(slugify(name));
		return this.createOrFindProject({
			name,
			modId,
			visibility: 'private',
			defaultBranch: await repository.branch(),
			identity: folder.uri.toString(),
		});
	}

	/** Create the backend project record, tolerating a slug another session already used. */
	private async createOrFindProject(options: {
		name: string;
		modId: string;
		visibility: string;
		defaultBranch: string;
		identity: string;
	}): Promise<IProject> {
		const slug = slugify(options.name);
		try {
			const project = await this.api.createProject({
				name: options.name,
				slug,
				description: vscode.l10n.t('Modernity benchmark episode project'),
				mod_id: options.modId,
				mod_name: options.name,
				group_id: `com.modernity.${options.modId}`,
				mod_version: '1.0.0',
				license: 'All Rights Reserved',
				template_id: TEMPLATE.id,
				template_version: TEMPLATE.version,
				minecraft_version: TEMPLATE.minecraftVersion,
				neoforge_version: TEMPLATE.neoforgeVersion,
				java_version: TEMPLATE.javaVersion,
				gradle_version: TEMPLATE.gradleVersion,
				visibility: options.visibility,
				default_branch: options.defaultBranch,
				settings: { benchmark_episodes_enabled: true },
			}, canonicalUuid(`${options.identity}|${slug}|${options.modId}`));
			await this.context.workspaceState.update(PROJECT_ID_KEY, project.id);
			return project;
		} catch (error) {
			if (!(error instanceof ModernityApiError) || error.status !== 409) {
				throw error;
			}
			const match = (await this.api.listProjects()).find(project => project.slug === slug);
			if (!match) {
				throw error;
			}
			await this.context.workspaceState.update(PROJECT_ID_KEY, match.id);
			return match;
		}
	}

	/** Run the new-project wizard on demand, from any window. */
	private async createProject(suggestedName = ''): Promise<void> {
		try {
			await this.createProjectInNewFolder('', suggestedName);
		} catch (error) {
			if (error instanceof UserCancelledError || error instanceof ProjectSetupRestart) {
				return;
			}
			const message = error instanceof Error ? error.message : String(error);
			this.output.error(`Project setup failed: ${message}`);
			void vscode.window.showErrorMessage(vscode.l10n.t('Could not set up the mod project: {0}', message));
		}
	}

	/** Scaffold a brand-new mod project, then reopen the window on it. */
	private async createProjectInNewFolder(initialPrompt: string, suggestedName = ''): Promise<never> {
		const name = await requiredInput({
			title: vscode.l10n.t('Mod Project Name'),
			prompt: vscode.l10n.t('Name the mod this project builds.'),
			placeHolder: vscode.l10n.t("Delver's Feast"),
			value: suggestedName.trim() || undefined,
		});
		const slug = slugify(name);
		const modId = await chooseModId(slug);
		const [parent] = await vscode.window.showOpenDialog({
			title: vscode.l10n.t('Choose Where to Create {0}', name),
			openLabel: vscode.l10n.t('Create Project Here'),
			canSelectFiles: false,
			canSelectFolders: true,
			canSelectMany: false,
			defaultUri: vscode.Uri.file(os.homedir()),
		}) ?? [];
		if (!parent) {
			throw new UserCancelledError();
		}
		const destination = path.join(parent.fsPath, slug);
		if (await hasEntries(destination)) {
			throw new Error(vscode.l10n.t('`{0}` already exists and is not empty. Choose another location or open that folder directly.', destination));
		}

		const project = await this.createOrFindProject({
			name,
			modId,
			visibility: 'private',
			defaultBranch: TEMPLATE.defaultBranch,
			identity: destination,
		});

		await vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: vscode.l10n.t('Setting up {0} from the pinned NeoForge template…', name),
		}, () => provisionModernityProject(this.context, {
			destination,
			project_id: project.id,
			mod_id: modId,
			mod_name: name,
			group_id: `com.modernity.${modId}`,
			mod_version: '1.0.0',
			license: 'All Rights Reserved',
			template_id: TEMPLATE.id,
			template_version: TEMPLATE.version,
			default_branch: TEMPLATE.defaultBranch,
			git_author_name: 'Modernity',
		}));

		const pending: IPendingProjectSetup = {
			schemaVersion: 1,
			folderPath: destination,
			projectId: project.id,
			projectName: name,
			prompt: initialPrompt.trim(),
			createdAt: new Date().toISOString(),
		};
		await this.context.globalState.update(PENDING_SETUP_KEY, pending);
		this.output.info(`Provisioned project ${name} at ${destination} (local Git only)`);
		await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(destination), { forceReuseWindow: true });
		throw new ProjectSetupRestart(vscode.l10n.t(
			'Created `{0}` at `{1}`. Opening it now — Modernity will offer to start the episode once the window reloads.',
			name,
			destination,
		));
	}

	/** Offer to start the first episode once a freshly created project finishes opening. */
	private async resumePendingProjectSetup(): Promise<void> {
		const pending = this.context.globalState.get<IPendingProjectSetup>(PENDING_SETUP_KEY);
		if (!pending) {
			return;
		}
		if (Date.now() - Date.parse(pending.createdAt) > PENDING_SETUP_TTL_MS) {
			await this.context.globalState.update(PENDING_SETUP_KEY, undefined);
			return;
		}
		const folder = (vscode.workspace.workspaceFolders ?? []).find(
			candidate => path.resolve(candidate.uri.fsPath) === path.resolve(pending.folderPath),
		);
		if (!folder) {
			return;
		}
		await this.context.globalState.update(PENDING_SETUP_KEY, undefined);
		await this.context.workspaceState.update(PROJECT_ID_KEY, pending.projectId);
		await this.refreshContext();
		const start = await vscode.window.showInformationMessage(
			vscode.l10n.t('{0} is ready. Start its first benchmark episode?', pending.projectName),
			vscode.l10n.t('Start Episode'),
		);
		if (start) {
			await this.openNewEpisodeChat(pending.prompt);
		}
	}

	private async submitFeature(request?: IEpisodeCommandRequest): Promise<void> {
		if (this.finalizationRunning) {
			void vscode.window.showInformationMessage(vscode.l10n.t('Modernity is already submitting or grading this episode.'));
			return;
		}
		this.finalizationRunning = true;
		try {
			await this.acceptFeature(request);
		} finally {
			this.finalizationRunning = false;
		}
	}

	private async gradeFeature(request?: IEpisodeCommandRequest): Promise<void> {
		if (this.finalizationRunning) {
			void vscode.window.showInformationMessage(vscode.l10n.t('Modernity is already submitting or grading this episode.'));
			return;
		}
		this.finalizationRunning = true;
		try {
			const active = this.active;
			if (request?.sessionId && active?.chatSessionId !== request.sessionId) {
				void vscode.window.showErrorMessage(vscode.l10n.t('Grade this episode from the chat that started it with `/swe-session`.'));
				return;
			}
			if (!active) {
				void vscode.window.showInformationMessage(vscode.l10n.t('There is no Modernity episode to grade.'));
				return;
			}
			let candidate: IPreparedEpisodeCandidate | undefined;
			if (isCandidateStage(active.stage)) {
				if (!this.isEnabled()) {
					void vscode.window.showInformationMessage(vscode.l10n.t('Collect Data is off, so this session cannot be graded. Turn it on from the status bar first.'));
					return;
				}
				candidate = await this.prepareGradeCandidate(active);
			} else {
				if (!active.finalCommitSha) {
					void vscode.window.showInformationMessage(vscode.l10n.t('This accepted episode predates Codimango task artifacts.'));
					return;
				}
				const artifact = await this.resolveTaskArtifact(active);
				const refreshed = adoptTaskArtifact(active, artifact);
				this.active = refreshed;
				await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, refreshed);
				candidate = { active: refreshed, artifact };
			}
			if (candidate) {
				await this.gradeTask(candidate.active, candidate.artifact);
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.output.error(`Codimango grade setup failed: ${message}`);
			void vscode.window.showErrorMessage(vscode.l10n.t('Could not prepare or grade the candidate: {0}. The local candidate is preserved and can be revised or retried.', message));
		} finally {
			this.finalizationRunning = false;
			if (isCandidateStage(this.active?.stage)) {
				this.startWatcher();
			}
			await this.refreshContext();
		}
	}

	private async prepareGradeCandidate(
		initial: IActiveEpisode,
		preparedGradeFeedback?: IEpisodeGradeFeedback,
	): Promise<IPreparedEpisodeCandidate | undefined> {
		const repository = newRepository(initial.repositoryRoot);
		if (await repository.branch() !== initial.branch) {
			void vscode.window.showErrorMessage(vscode.l10n.t('Switch back to episode branch `{0}` before grading the feature.', initial.branch));
			return undefined;
		}
		this.stopWatcher();
		await this.checkpointChain;
		await this.captureCheckpoint();
		let state = this.active;
		if (!state || state.episodeId !== initial.episodeId) {
			return undefined;
		}

		const workingChanges = await repository.status();
		if (!state.finalCommitSha) {
			if (await repository.head() !== state.baseCommit) {
				throw new Error(vscode.l10n.t('The episode branch contains a manual commit. Restore it to the immutable base commit `{0}` before grading; Modernity must create the only feature commit.', state.baseCommit.slice(0, 12)));
			}
			if (workingChanges.length === 0) {
				void vscode.window.showErrorMessage(vscode.l10n.t('This episode has no file changes. Empty episodes cannot be graded as benchmark candidates.'));
				return undefined;
			}
			const confirmation = await vscode.window.showInformationMessage(
				vscode.l10n.t('Grade this candidate? Modernity creates the sole feature commit, prepares provenance-safe GameTests, emits an unpacked task candidate, and runs the local Codimango benchmark panel. The episode remains open until `/submit`.'),
				{ modal: true, detail: workingChanges.slice(0, 20).join('\n') },
				vscode.l10n.t('Commit and Grade'),
			);
			if (!confirmation) {
				return undefined;
			}
			const message = await requiredInput({
				title: vscode.l10n.t('Feature Commit Message'),
				value: `feat: ${summarizePrompt(state.prompt)}`,
			});
			const committed = await repository.commitFeature(message);
			state = {
				...withoutTaskCandidate(state, false),
				finalCommitSha: committed.commitSha,
				finalTreeSha: committed.treeSha,
				stage: 'committed_pending_accept',
			};
			this.active = state;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, state);
		} else if (workingChanges.length > 0) {
			if (await repository.head() !== state.finalCommitSha) {
				throw new Error(vscode.l10n.t('The episode branch moved away from candidate commit `{0}`. Restore that commit before revising the candidate.', state.finalCommitSha.slice(0, 12)));
			}
			const confirmation = await vscode.window.showInformationMessage(
				vscode.l10n.t('Re-grade the revised candidate? Modernity amends the sole feature commit, invalidates the previous artifact and grade, then rebuilds the benchmark candidate.'),
				{ modal: true, detail: workingChanges.slice(0, 20).join('\n') },
				vscode.l10n.t('Amend and Grade'),
			);
			if (!confirmation) {
				return undefined;
			}
			const committed = await repository.amendFeature();
			state = {
				...withoutTaskCandidate(state, false),
				finalCommitSha: committed.commitSha,
				finalTreeSha: committed.treeSha,
				stage: 'committed_pending_accept',
			};
			this.active = state;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, state);
		}

		const candidateFinalCommit = state.finalCommitSha;
		if (!candidateFinalCommit) {
			throw new Error(vscode.l10n.t('The feature commit was not created.'));
		}
		if ((await repository.status()).length > 0) {
			throw new Error(vscode.l10n.t('The worktree changed after Modernity created candidate commit `{0}`. Re-run `/grade` after the edits settle.', candidateFinalCommit.slice(0, 12)));
		}

		const gradedArtifact = taskArtifactFromState(state);
		const gradeReportPath = state.gradeReportPath;
		const gradeFeedback = preparedGradeFeedback ?? (
			state.gradeStatus === 'revise' && gradeReportPath && gradedArtifact
				? await prepareEpisodeGradeFeedback(
					state.repositoryRoot,
					state.traceSessionId,
					gradeReportPath,
					gradedArtifact,
				)
				: undefined
		);
		if (gradeFeedback?.route === 'candidate_revision') {
			this.output.warn(gradeFeedback.summary);
			throw new Error(vscode.l10n.t('Codimango found implementation or instruction blockers in the current candidate. Revise the feature or task instruction before running `/grade` again.'));
		}
		if (gradeFeedback?.route === 'test_revision') {
			this.output.info(`Applying qualitative test feedback from ${gradeReportPath}.`);
			state = withoutTaskCandidate(state, false);
		}

		let artifact = taskArtifactFromState(state);
		const candidateHead = await repository.head();
		if (candidateHead !== candidateFinalCommit && (artifact || hasPreparedTestReview(state))) {
			throw new Error(vscode.l10n.t('The episode branch moved away from candidate commit `{0}`. Restore it before grading.', candidateFinalCommit.slice(0, 12)));
		}
		if (artifact) {
			artifact = await this.resolveTaskArtifact(state, artifact.taskRepositoryRoot);
			state = adoptTaskArtifact(state, artifact);
			this.active = state;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, state);
			return { active: state, artifact };
		}

		if (!hasPreparedTestReview(state)) {
			const headBeforePreparation = await repository.head();
			if (headBeforePreparation !== candidateFinalCommit) {
				// The CLI owns a hash-bound receipt that can recover the narrow crash
				// window where Git advanced but workspace state was not yet persisted.
				this.output.info(`Recovering GameTest preparation from ${candidateFinalCommit.slice(0, 12)} with HEAD at ${headBeforePreparation.slice(0, 12)}.`);
			}
			const preparationState = state;
			const rawFinalCommit = preparationState.finalCommitSha;
			if (!rawFinalCommit) {
				throw new Error(vscode.l10n.t('The feature commit was not created.'));
			}
			const prepared = await vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('Preparing benchmark GameTests…'),
				cancellable: false,
			}, async progress => prepareEpisodeTests(this.context.extensionPath, {
				repositoryRoot: preparationState.repositoryRoot,
				sessionId: preparationState.traceSessionId,
				finalCommit: rawFinalCommit,
				reviewFile: gradeFeedback?.route === 'test_revision' ? gradeFeedback.reviewPath : undefined,
				guidanceFile: gradeFeedback?.route === 'test_revision' ? gradeFeedback.guidancePath : undefined,
				failureDirectory: path.join(
					preparationState.repositoryRoot,
					'.modernity',
					'workshop',
					preparationState.traceSessionId,
					'failed-test-preparations',
				),
			}, message => {
				this.output.info(message);
				progress.report({ message });
			}));
			const preparedHead = await repository.head();
			const preparedTree = await repository.tree(prepared.commitSha);
			const preparedChanges = await repository.status();
			if (preparedHead !== prepared.commitSha || preparedTree !== prepared.treeSha || preparedChanges.length > 0) {
				throw new Error(vscode.l10n.t(
					'GameTest preparation did not leave the reported commit checked out with a clean worktree. Expected commit {0} and tree {1}; restore the episode branch and retry.',
					prepared.commitSha.slice(0, 12),
					prepared.treeSha.slice(0, 12),
				));
			}
			this.output.info(`GameTest preparation ${prepared.action}; receipt: ${prepared.receiptPath}`);
			if (prepared.commitSha !== rawFinalCommit) {
				state = adoptPreparedCommit(state, prepared.commitSha, prepared.treeSha);
			}
			state = {
				...state,
				firstPartyTestReviewPath: prepared.reviewPath,
				firstPartyTestReviewSha256: prepared.reviewSha256,
			};
			this.active = state;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, state);
		}

		const finalCommit = state.finalCommitSha;
		if (!finalCommit) {
			throw new Error(vscode.l10n.t('The task candidate state is missing its prepared feature commit.'));
		}
		const artifactState = state;
		artifact = await vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: vscode.l10n.t('Creating Codimango task candidate…'),
			cancellable: false,
		}, async progress => createEpisodeTaskArtifacts(this.context.extensionPath, {
			repositoryRoot: artifactState.repositoryRoot,
			sessionId: artifactState.traceSessionId,
			finalCommit,
			projectSlug: artifactState.projectSlug ?? path.basename(artifactState.repositoryRoot),
			remoteName: artifactState.remoteName,
			complexity: artifactState.complexity,
			followups: artifactState.followups,
		}, message => {
			this.output.info(message);
			progress.report({ message });
		}));
		artifact = await this.resolveTaskArtifact(state, artifact.taskRepositoryRoot);
		state = adoptTaskArtifact(state, artifact);
		this.active = state;
		await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, state);
		return { active: state, artifact };
	}

	private async resolveTaskArtifact(active: IActiveEpisode, taskRepositoryRoot = active.taskRepositoryRoot ?? defaultTaskRepositoryRoot(active)): Promise<IEpisodeTaskArtifact> {
		const finalCommitSha = active.finalCommitSha;
		if (!finalCommitSha) {
			throw new Error(vscode.l10n.t('The episode has no candidate commit to resolve.'));
		}
		return vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: vscode.l10n.t('Resolving the current Codimango task candidate…'),
			cancellable: false,
		}, () => resolveEpisodeTaskArtifact(this.context.extensionPath, {
			repositoryRoot: active.repositoryRoot,
			taskRepositoryRoot,
			expectedBaseCommit: active.baseCommit,
			expectedFinalCommit: finalCommitSha,
			expectedTraceSessionId: active.traceSessionId,
		}));
	}

	private async acceptFeature(request?: IEpisodeCommandRequest): Promise<void> {
		const active = this.active;
		if (request?.sessionId && active?.chatSessionId !== request.sessionId) {
			void vscode.window.showErrorMessage(vscode.l10n.t('Submit this episode from the chat that started it with `/swe-session`.'));
			return;
		}
		if (active?.stage === 'accepted_sync_pending') {
			await this.syncAcceptedFeature();
			return;
		}
		if (active?.stage === 'accepted') {
			if (!active.finalCommitSha) {
				void vscode.window.showInformationMessage(vscode.l10n.t('This accepted episode predates Codimango task artifacts.'));
				return;
			}
			try {
				const artifact = await resolveEpisodeTaskArtifact(this.context.extensionPath, {
					repositoryRoot: active.repositoryRoot,
					taskRepositoryRoot: active.taskRepositoryRoot ?? defaultTaskRepositoryRoot(active),
					expectedBaseCommit: active.baseCommit,
					expectedFinalCommit: active.finalCommitSha,
					expectedTraceSessionId: active.traceSessionId,
				});
				const refreshed = adoptTaskArtifact(active, artifact);
				this.active = refreshed;
				await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, refreshed);
				await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(artifact.taskDirectory));
			} catch (error) {
				void vscode.window.showErrorMessage(vscode.l10n.t(
					'Could not open a verified task artifact: {0}',
					error instanceof Error ? error.message : String(error),
				));
			}
			return;
		}
		if (!active) {
			void vscode.window.showInformationMessage(vscode.l10n.t('There is no active Modernity episode to submit.'));
			return;
		}
		if (!this.isEnabled()) {
			void vscode.window.showInformationMessage(vscode.l10n.t('Collect Data is off, so this session cannot be submitted. Turn it on from the status bar first.'));
			return;
		}
		if (!active.finalCommitSha || !taskArtifactFromState(active)) {
			void vscode.window.showInformationMessage(vscode.l10n.t('Run `/grade` first to create and evaluate the current task candidate.'));
			return;
		}
		if (active.gradeStatus !== 'passed_local') {
			void vscode.window.showWarningMessage(vscode.l10n.t('This candidate is not ready to submit. `/grade` must finish with `passed_local`; the current status is `{0}`.', active.gradeStatus ?? 'not graded'));
			return;
		}
		if (!active.gradeReportPath) {
			void vscode.window.showWarningMessage(vscode.l10n.t('The passing grade report is missing. Run `/grade` again before submitting.'));
			return;
		}
		try {
			await fs.access(active.gradeReportPath);
		} catch {
			void vscode.window.showWarningMessage(vscode.l10n.t('The passing grade report no longer exists on disk. Run `/grade` again before submitting.'));
			return;
		}
		const repository = newRepository(active.repositoryRoot);
		if (await repository.branch() !== active.branch) {
			void vscode.window.showErrorMessage(vscode.l10n.t('Switch back to episode branch `{0}` before submitting the feature.', active.branch));
			return;
		}
		this.stopWatcher();
		await this.checkpointChain;
		try {
			let state = this.active;
			if (!state || !state.finalCommitSha || state.gradeStatus !== 'passed_local') {
				throw new Error(vscode.l10n.t('The successfully graded candidate is no longer active. Run `/grade` again.'));
			}
			if (await repository.head() !== state.finalCommitSha || (await repository.status()).length > 0) {
				throw new Error(vscode.l10n.t('The worktree changed after grading candidate `{0}`. Re-run `/grade` before submitting.', state.finalCommitSha.slice(0, 12)));
			}
			const artifact = await this.resolveTaskArtifact(state);
			state = adoptTaskArtifact(state, artifact);
			if (state.gradeStatus !== 'passed_local') {
				throw new Error(vscode.l10n.t('The verified artifact differs from the graded candidate. Run `/grade` again before submitting.'));
			}
			this.active = state;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, state);
			const finalCommitSha = state.finalCommitSha;
			if (!finalCommitSha) {
				throw new Error(vscode.l10n.t('The verified candidate is missing its feature commit.'));
			}
			const publicationRequest = this.taskPublicationRequest(state);
			const publicationPreflight = await vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('Checking SWE-Bench publication target…'),
				cancellable: false,
			}, () => preflightEpisodeTaskPublication(
				this.context.extensionPath,
				publicationRequest,
			));
			state = { ...state, taskPublication: publicationPreflight };
			this.active = state;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, state);
			const confirmation = await vscode.window.showInformationMessage(
				vscode.l10n.t('Submit this locally-passed candidate? Modernity publishes the exact graded task, then seals the episode and trace at commit `{0}`. This cannot be revised afterward.', finalCommitSha.slice(0, 12)),
				{ modal: true, detail: await repository.diffStat(state.baseCommit, finalCommitSha) },
				vscode.l10n.t('Submit and Lock'),
			);
			if (!confirmation) {
				this.startWatcher();
				return;
			}
			if (await repository.head() !== finalCommitSha || (await repository.status()).length > 0) {
				throw new Error(vscode.l10n.t('The candidate changed during submission confirmation. Run `/grade` again before submitting.'));
			}
			const finalTreeSha = state.finalTreeSha ?? await repository.tree(finalCommitSha);
			const changedFiles = await repository.changedFiles(state.baseCommit, finalCommitSha);
			const diffStat = await repository.diffStat(state.baseCommit, finalCommitSha);
			const finalPatch = await repository.portablePatch(state.baseCommit, finalCommitSha, 512 * 1024);
			const checkpointSnapshots = await repository.portableCheckpointPatches(state.baseCommit, state.checkpoints);
			const elapsedSeconds = Math.max(0, Math.round((Date.now() - Date.parse(state.startedAt)) / 1000));
			const acceptedAt = new Date().toISOString();
			const acceptPayload = {
				final_git: {
					commit_sha: finalCommitSha,
					tree_sha: finalTreeSha,
					base_commit_sha: state.baseCommit,
					branch: state.branch,
					checkpoint_ref: state.checkpoints.at(-1)?.ref ?? null,
					...(state.remoteName ? { repository: state.remoteName } : {}),
				},
				outputs: {
					changed_files: changedFiles,
					diff_stat: diffStat,
					checkpoints: state.checkpoints,
					checkpoint_sequence_total: state.checkpointSequence,
					portable_patch: finalPatch,
					checkpoint_snapshots: checkpointSnapshots,
					trace_boundary: {
						started_at: state.startedAt,
						accepted_at: acceptedAt,
					},
				},
				completeness: true,
				speed: elapsedSeconds,
			};
			let accepted: IEpisode;
			try {
				accepted = await this.api.acceptEpisode(state.episodeId, state.version, acceptPayload);
			} catch (error) {
				if (!(error instanceof ModernityApiError) || error.status !== 409) {
					throw error;
				}
				const existing = await this.api.getEpisode(state.episodeId);
				if (existing.lifecycle_status === 'raw_episode' || existing.final_git.commit_sha !== finalCommitSha) {
					throw error;
				}
				accepted = existing;
			}
			await this.disableTraceContent(state.traceSessionId);
			let acceptedState: IActiveEpisode = { ...state, version: accepted.version, stage: 'accepted_sync_pending' };
			this.active = acceptedState;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, acceptedState);
			await this.refreshContext();
			const bundleDirectory = await this.exportEpisodeBundle(acceptedState, accepted, finalPatch);

			let syncPending = false;
			try {
				const publication = await vscode.window.withProgress({
					location: vscode.ProgressLocation.Notification,
					title: vscode.l10n.t('Publishing graded SWE-Bench task…'),
					cancellable: false,
				}, () => publishEpisodeTask(this.context.extensionPath, publicationRequest));
				acceptedState = { ...acceptedState, taskPublication: publication };
				if (publication.status === 'push_pending') {
					syncPending = true;
					void vscode.window.showWarningMessage(vscode.l10n.t('The task was committed locally, but its remote push is pending: {0}', publication.pushError ?? 'unknown Git error'));
				}
			} catch (error) {
				syncPending = true;
				this.output.error(`Task publication failed after episode acceptance: ${error instanceof Error ? error.message : String(error)}`);
			}
			if (state.githubMode !== 'local') {
				try {
					await this.pushAcceptedState(acceptedState, repository);
				} catch (error) {
					syncPending = true;
					const message = error instanceof Error ? error.message : String(error);
					void vscode.window.showWarningMessage(vscode.l10n.t('Feature accepted locally, but GitHub sync failed: {0}', message));
				}
			}
			acceptedState = { ...acceptedState, stage: syncPending ? 'accepted_sync_pending' : 'accepted' };
			this.active = acceptedState;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, acceptedState);
			await this.refreshContext();

			const openBundle = vscode.l10n.t('Open Saved Trace');
			const openTask = vscode.l10n.t('Open Codimango Task');
			const openTestReview = vscode.l10n.t('Open First-Party Test Review');
			const openProject = vscode.l10n.t('Open Project Viewer');
			const openTrace = vscode.l10n.t('Open Trace');
			const action = await vscode.window.showInformationMessage(
				bundleDirectory
					? vscode.l10n.t('Session submitted and locked. Commit {0} produced an unpacked Codimango task and its trace is saved in the project folder.', state.finalCommitSha?.slice(0, 12) ?? '')
					: vscode.l10n.t('Session submitted and locked. Commit {0} produced an unpacked Codimango task.', state.finalCommitSha?.slice(0, 12) ?? ''),
				...(bundleDirectory ? [openBundle] : []),
				openTask,
				...(state.firstPartyTestReviewPath ? [openTestReview] : []),
				openProject,
				openTrace,
			);
			if (action === openBundle && bundleDirectory) {
				await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(bundleDirectory));
			} else if (action === openTask) {
				await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(artifact.taskDirectory));
			} else if (action === openTestReview && state.firstPartyTestReviewPath) {
				await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(state.firstPartyTestReviewPath));
			} else if (action === openProject) {
				await this.openProjectViewer();
			} else if (action === openTrace) {
				await this.openTraceViewer();
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.output.error(`Submit failed: ${message}`);
			void vscode.window.showErrorMessage(vscode.l10n.t('Could not submit the session: {0}. The locally graded candidate is preserved and the operation can be retried safely.', message));
			if (isCandidateStage(this.active?.stage)) {
				this.startWatcher();
			}
			await this.refreshContext();
		}
	}

	private async gradeTask(
		active: IActiveEpisode,
		existing?: IEpisodeTaskArtifact,
		automaticTestRevisionsRemaining = MAX_AUTOMATIC_TEST_REVISIONS,
	): Promise<void> {
		const artifact = existing ?? taskArtifactFromState(active);
		if (!artifact) {
			void vscode.window.showErrorMessage(vscode.l10n.t('Modernity could not create a Codimango task candidate for this grade.'));
			return;
		}
		try {
			const gradingState = withoutGrade(this.active ?? active);
			this.active = gradingState;
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, gradingState);
			await this.refreshContext();
			const grade = await vscode.window.withProgress({
				location: vscode.ProgressLocation.Notification,
				title: vscode.l10n.t('Running local Codimango quality gates…'),
				cancellable: false,
			}, async progress => gradeEpisodeTask(
				this.context.extensionPath,
				artifact,
				active.repositoryRoot,
				active.traceSessionId,
				message => {
					this.output.info(message);
					progress.report({ message });
				},
			));
			const current = this.active ?? active;
			if (isCandidateStage(current.stage)) {
				const repository = newRepository(current.repositoryRoot);
				if (await repository.head() !== artifact.finalCommit || (await repository.status()).length > 0) {
					this.active = withoutGrade(current);
					await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, this.active);
					await this.refreshContext();
					const openReport = vscode.l10n.t('Open Grade Report');
					const action = await vscode.window.showWarningMessage(
						vscode.l10n.t('The candidate changed while local grading was running. This report applies to the previous commit; run `/grade` again for the current worktree.'),
						openReport,
					);
					if (action === openReport) {
						await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(grade.reportPath));
					}
					return;
				}
			}
			this.active = {
				...current,
				gradeStatus: grade.status,
				gradeReportPath: grade.reportPath,
			};
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, this.active);
			await this.refreshContext();
			const gradeFeedback = grade.status === 'revise'
				? await prepareEpisodeGradeFeedback(
					current.repositoryRoot,
					current.traceSessionId,
					grade.reportPath,
					artifact,
				)
				: undefined;
			if (gradeFeedback?.route === 'test_revision' && automaticTestRevisionsRemaining > 0) {
				this.output.info(`Automatically revising hidden GameTests from ${grade.reportPath}; ${automaticTestRevisionsRemaining} bounded retry remains.`);
				const retry = await this.prepareGradeCandidate(this.active, gradeFeedback);
				if (retry) {
					await this.gradeTask(
						retry.active,
						retry.artifact,
						automaticTestRevisionsRemaining - 1,
					);
					return;
				}
			}
			if (gradeFeedback?.route === 'candidate_revision') {
				this.output.warn(gradeFeedback.summary);
			}
			const openReport = vscode.l10n.t('Open Grade Report');
			const openTestReview = vscode.l10n.t('Open First-Party Test Review');
			let message: string;
			if (grade.status === 'passed_local') {
				message = vscode.l10n.t('Local Codimango gates place this candidate in band. It is ready for `/submit`; review the grade report and first-party tests before locking the episode.');
			} else if (gradeFeedback?.route === 'candidate_revision') {
				message = vscode.l10n.t('Local Codimango grade found implementation or instruction blockers. Revise the candidate, then run `/grade` again before submitting.');
			} else if (gradeFeedback?.route === 'test_revision' && automaticTestRevisionsRemaining === 0) {
				message = vscode.l10n.t('The automatic hidden-GameTest revision was exhausted and the candidate still needs test work. Review the report, then run `/grade` again after revising the task contract if needed.');
			} else {
				message = vscode.l10n.t('Local Codimango grade finished with status `{0}`. Revise the implementation, tests, or instruction as needed, then run `/grade` again before submitting.', grade.status);
			}
			const actions = [
				openReport,
				...(current.firstPartyTestReviewPath ? [openTestReview] : []),
			];
			const action = grade.status === 'passed_local'
				? await vscode.window.showInformationMessage(message, ...actions)
				: await vscode.window.showWarningMessage(message, ...actions);
			if (action === openReport) {
				await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(grade.reportPath));
			} else if (action === openTestReview && current.firstPartyTestReviewPath) {
				await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(current.firstPartyTestReviewPath));
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.output.error(`Codimango grade failed: ${message}`);
			void vscode.window.showErrorMessage(vscode.l10n.t('The candidate artifact is preserved, but local Codimango grading did not complete: {0}. Run `/grade` again after fixing the local setup.', message));
		}
	}

	/**
	 * Record one steering hint and hand it to the agent.
	 *
	 * The hint is stored as a correction segment and forwarded with the `[Hint]`
	 * marker, so the transcript carries the intervention where a trace-correction
	 * consumer expects to find it.
	 */
	private async addHint(hint: string): Promise<ICorrectionSegment | undefined> {
		const active = this.active;
		if (!this.isEnabled() || !active || !isCandidateStage(active.stage)) {
			void vscode.window.showInformationMessage(vscode.l10n.t('Hints are recorded only while a `/swe-session` remains open for grading.'));
			return undefined;
		}
		const text = hint.trim();
		if (!text) {
			return undefined;
		}
		const segment = await this.api.addCorrection(active.episodeId, {
			segment_id: randomUUID(),
			kind: 'steering_prompt',
			label: 'hint',
			correction_prompt: text,
			metadata: {
				source: 'ide_hint',
				marker: HINT_MARKER,
				recorded_at: new Date().toISOString(),
				chat_session_id: active.chatSessionId,
			},
		});
		const updated = {
			...active,
			followups: [...(active.followups ?? []), text],
		};
		this.active = active.finalCommitSha ? withoutTaskCandidate(updated, true) : updated;
		await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, this.active);
		await this.refreshContext();
		await vscode.commands.executeCommand('workbench.action.chat.open', {
			mode: 'agent',
			query: `${HINT_MARKER} ${text}`,
		});
		return segment;
	}

	/** Prompt for a hint, then record and send it. */
	private async promptForHint(): Promise<void> {
		if (!this.isEnabled() || !isCandidateStage(this.active?.stage)) {
			void vscode.window.showInformationMessage(vscode.l10n.t('Hints are recorded only while a `/swe-session` remains open for grading.'));
			return;
		}
		const hint = await vscode.window.showInputBox({
			title: vscode.l10n.t('Steer the Agent'),
			prompt: vscode.l10n.t('Be specific: name the file, function, or mistake. Vague hints make weak training data.'),
			placeHolder: vscode.l10n.t('Use the existing validate() in utils.java instead of writing a new one'),
			ignoreFocusOut: true,
		});
		if (!hint?.trim()) {
			return;
		}
		try {
			const segment = await this.addHint(hint);
			if (segment) {
				this.output.info(`Recorded hint #${segment.ordinal} on episode ${this.active?.taskId}`);
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.output.error(`Hint failed: ${message}`);
			void vscode.window.showErrorMessage(vscode.l10n.t('The hint was not recorded: {0}', message));
		}
	}

	/**
	 * Save the sealed session into the project's own folder.
	 *
	 * The trace is already durable in the backend, so a failed export downgrades to a
	 * warning instead of undoing a submitted episode.
	 */
	private async exportEpisodeBundle(
		active: IActiveEpisode,
		episode: IEpisode,
		patch: IPortablePatch,
	): Promise<string | undefined> {
		if (!this.exportsBundle()) {
			return undefined;
		}
		try {
			const [events, corrections] = await Promise.all([
				this.api.listTraceEvents(active.traceSessionId),
				this.api.listCorrections(active.episodeId).catch(() => []),
			]);
			const directory = await writeEpisodeBundle(active.repositoryRoot, {
				taskId: active.taskId,
				episode: {
					...episode,
					local: {
						prompt: active.prompt,
						model: active.model,
						category: active.category,
						complexity: active.complexity,
						branch: active.branch,
						base_branch: active.baseBranch,
						base_commit: active.baseCommit,
						base_tree: active.baseTree,
						final_commit: active.finalCommitSha ?? null,
						final_tree: active.finalTreeSha ?? null,
						github_mode: active.githubMode,
						repository: active.remoteName ?? null,
						codimango_task: active.taskDirectory ?? null,
						artifact_fingerprint: active.artifactFingerprint ?? null,
						first_party_test_review: active.firstPartyTestReviewPath ?? null,
						first_party_test_review_sha256: active.firstPartyTestReviewSha256 ?? null,
						grade_status: active.gradeStatus ?? null,
						grade_report: active.gradeReportPath ?? null,
						started_at: active.startedAt,
						submitted_at: new Date().toISOString(),
						checkpoints: active.checkpoints,
					},
				},
				events,
				corrections,
				instruction: active.prompt,
				patch: patch.content,
			});
			this.output.info(`Episode ${active.taskId} bundle written to ${directory} (${events.length} events)`);
			if (events.length >= MAX_EXPORTED_TRACE_EVENTS) {
				this.output.warn(`Episode ${active.taskId} trace was capped at ${MAX_EXPORTED_TRACE_EVENTS} saved events; the backend copy remains complete.`);
				void vscode.window.showWarningMessage(vscode.l10n.t('The saved trace was capped at {0} events. The complete trace is still in the Modernity backend.', MAX_EXPORTED_TRACE_EVENTS));
			}
			return directory;
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.output.warn(`Episode bundle export failed: ${message}`);
			void vscode.window.showWarningMessage(vscode.l10n.t('The session was submitted, but its trace could not be saved into the project folder: {0}', message));
			return undefined;
		}
	}

	private async syncAcceptedFeature(): Promise<void> {
		const active = this.active;
		if (!active || active.stage !== 'accepted_sync_pending') {
			void vscode.window.showInformationMessage(vscode.l10n.t('There is no accepted Modernity feature waiting for GitHub sync.'));
			return;
		}
		const repository = newRepository(active.repositoryRoot);
		try {
			let state = active;
			let pending = false;
			const publication = await publishEpisodeTask(
				this.context.extensionPath,
				this.taskPublicationRequest(state),
			);
			state = { ...state, taskPublication: publication };
			if (publication.status === 'push_pending') {
				pending = true;
			}
			if (state.githubMode !== 'local') {
				try {
					await this.pushAcceptedState(state, repository);
				} catch (error) {
					pending = true;
					this.output.error(`Accepted source sync failed: ${error instanceof Error ? error.message : String(error)}`);
				}
			}
			this.active = { ...state, stage: pending ? 'accepted_sync_pending' : 'accepted' };
			await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, this.active);
			await this.refreshContext();
			void vscode.window.showInformationMessage(pending
				? vscode.l10n.t('The accepted task or source branch is still waiting for remote sync.')
				: vscode.l10n.t('Accepted feature and SWE-Bench task synced to GitHub.'));
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			this.output.error(`Accepted feature sync failed: ${message}`);
			void vscode.window.showErrorMessage(vscode.l10n.t('GitHub sync failed: {0}. The accepted local commit is unchanged.', message));
		}
	}

	private async pushAcceptedState(active: IActiveEpisode, repository: GitEpisodeRepository): Promise<void> {
		if (!active.finalCommitSha) {
			throw new Error(vscode.l10n.t('The accepted episode is missing its Git commit metadata.'));
		}
		if (await repository.head() !== active.finalCommitSha || (await repository.status()).length > 0) {
			throw new Error(vscode.l10n.t('Restore accepted commit `{0}` with a clean worktree before syncing.', active.finalCommitSha.slice(0, 12)));
		}
		const credential = await this.api.getRepositoryCredential(active.projectId);
		await repository.pushEpisode(active.branch, credential);
	}

	private async disableTraceContent(traceSessionId: string): Promise<void> {
		const traceSessionIds = this.context.workspaceState.get<readonly string[]>(TRACE_SESSION_IDS_KEY, []);
		await this.context.workspaceState.update(TRACE_SESSION_IDS_KEY, traceSessionIds.filter(id => id !== traceSessionId));
	}

	private startWatcher(): void {
		this.stopWatcher();
		const active = this.active;
		if (!active || !isCandidateStage(active.stage)) {
			return;
		}
		const workspaceUri = vscode.Uri.parse(active.workspaceUri);
		this.watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(workspaceUri, '**/*'));
		const changed = (uri: vscode.Uri) => {
			const relative = path.relative(active.repositoryRoot, uri.fsPath);
			if (!relative || relative === '.git' || relative.startsWith(`.git${path.sep}`) || relative.startsWith(`..${path.sep}`)) {
				return;
			}
			if (this.checkpointTimer) {
				clearTimeout(this.checkpointTimer);
			}
			if (this.active?.gradeStatus) {
				void this.invalidateGradeIfDirty(active.episodeId).catch(error => {
					this.output.warn(`Could not re-check the graded candidate after a file change: ${error instanceof Error ? error.message : String(error)}`);
				});
			}
			this.checkpointTimer = setTimeout(() => {
				this.checkpointTimer = undefined;
				this.checkpointChain = this.checkpointChain.then(() => this.captureCheckpoint()).catch(error => {
					this.output.warn(`Episode checkpoint failed: ${error instanceof Error ? error.message : String(error)}`);
				});
			}, 1500);
		};
		this.watcher.onDidChange(changed);
		this.watcher.onDidCreate(changed);
		this.watcher.onDidDelete(changed);
	}

	private async invalidateGradeIfDirty(episodeId: string): Promise<void> {
		const active = this.active;
		if (!active || active.episodeId !== episodeId || !active.gradeStatus) {
			return;
		}
		if ((await newRepository(active.repositoryRoot).status()).length === 0) {
			return;
		}
		const current = this.active;
		if (!current || current.episodeId !== episodeId || !current.gradeStatus) {
			return;
		}
		this.active = withoutGrade(current);
		await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, this.active);
		await this.refreshContext();
	}

	private stopWatcher(): void {
		if (this.checkpointTimer) {
			clearTimeout(this.checkpointTimer);
			this.checkpointTimer = undefined;
		}
		this.watcher?.dispose();
		this.watcher = undefined;
	}

	private async captureCheckpoint(): Promise<void> {
		const active = this.active;
		if (!active || !isCandidateStage(active.stage)) {
			return;
		}
		const repository = newRepository(active.repositoryRoot);
		const sequence = active.checkpointSequence + 1;
		const checkpoint = await repository.createCheckpoint(active.episodeId, sequence, this.context.globalStorageUri.fsPath);
		const checkpoints = [...active.checkpoints, checkpoint].slice(-200);
		this.active = { ...active, checkpointSequence: sequence, checkpoints };
		await this.context.workspaceState.update(ACTIVE_EPISODE_KEY, this.active);
	}

	private async openProjectViewer(): Promise<void> {
		const projectId = this.active?.projectId ?? this.context.workspaceState.get<string>(PROJECT_ID_KEY);
		if (!projectId) {
			void vscode.window.showInformationMessage(vscode.l10n.t('No Modernity project is associated with this workspace.'));
			return;
		}
		await vscode.env.openExternal(vscode.Uri.parse(`${getWebBaseUrl()}/projects/${encodeURIComponent(projectId)}`));
	}

	private async openTraceViewer(): Promise<void> {
		if (!this.active?.traceSessionId) {
			void vscode.window.showInformationMessage(vscode.l10n.t('No benchmark episode trace is associated with this workspace.'));
			return;
		}
		await vscode.env.openExternal(vscode.Uri.parse(`${getWebBaseUrl()}/traces/${encodeURIComponent(this.active.traceSessionId)}`));
	}

	private isEnabled(): boolean {
		return vscode.workspace.getConfiguration('modernity').get<boolean>('benchmarkEpisodes.enabled', false);
	}

	private exportsBundle(): boolean {
		return vscode.workspace.getConfiguration('modernity').get<boolean>('benchmarkEpisodes.exportBundle', true);
	}

	private taskPublicationRequest(active: IActiveEpisode): IEpisodeTaskPublicationRequest {
		if (!active.gradeReportPath || !active.artifactFingerprint) {
			throw new Error(vscode.l10n.t('The passed candidate is missing its grade report or artifact fingerprint.'));
		}
		const configuration = vscode.workspace.getConfiguration('modernity');
		const configuredPath = (
			active.taskPublication?.repositoryRoot
			?? configuration.get<string>('benchmarkEpisodes.publishRepositoryPath', '')
		).trim();
		if (!configuredPath) {
			throw new Error(vscode.l10n.t('Configure `modernity.benchmarkEpisodes.publishRepositoryPath` to an existing SWE-Bench task repository checkout before submitting.'));
		}
		if (!path.isAbsolute(configuredPath)) {
			throw new Error(vscode.l10n.t('The SWE-Bench publication repository path must be absolute.'));
		}
		const branch = (
			active.taskPublication?.branch
			?? configuration.get<string>('benchmarkEpisodes.publishBranch', 'main')
		).trim();
		if (!branch) {
			throw new Error(vscode.l10n.t('The SWE-Bench publication branch cannot be empty.'));
		}
		return {
			gradeReportPath: active.gradeReportPath,
			repositoryRoot: path.resolve(configuredPath),
			branch,
			expectedArtifactFingerprint: active.artifactFingerprint,
		};
	}

	private async toggleCollectData(): Promise<void> {
		const enabled = !this.isEnabled();
		const active = this.active;
		if (!enabled && active && isCandidateStage(active.stage)) {
			const stop = await vscode.window.showWarningMessage(
				vscode.l10n.t('Episode `{0}` is still open. Turning Collect Data off hides Grade and Submit and stops capture; the local branch and commits are untouched.', active.taskId),
				{ modal: true },
				vscode.l10n.t('Turn Collect Data Off'),
			);
			if (!stop) {
				return;
			}
		}
		await this.setCollectData(enabled);
		void vscode.window.showInformationMessage(enabled
			? vscode.l10n.t('Collect Data is on. Episode sessions now show Grade, then Submit after a passing result.')
			: vscode.l10n.t('Collect Data is off. No new session content is captured.'));
	}

	private async setCollectData(enabled: boolean): Promise<void> {
		await vscode.workspace.getConfiguration('modernity').update('benchmarkEpisodes.enabled', enabled, vscode.ConfigurationTarget.Global);
		this.refreshCollectDataStatus();
	}

	private refreshCollectDataStatus(): void {
		const enabled = this.isEnabled();
		this.collectDataStatus.text = enabled
			? '$(record) ' + vscode.l10n.t('Collect Data: On')
			: '$(circle-large-outline) ' + vscode.l10n.t('Collect Data: Off');
		this.collectDataStatus.tooltip = enabled
			? vscode.l10n.t('Benchmark episode capture is on. Grade builds and evaluates the current task candidate; Submit seals only a locally-passed candidate. Click to turn off.')
			: vscode.l10n.t('Benchmark episode capture is off, so sessions have no Grade or Submit action. Click to turn on.');
		this.collectDataStatus.backgroundColor = enabled
			? new vscode.ThemeColor('statusBarItem.warningBackground')
			: undefined;
		this.collectDataStatus.show();
	}

	private async refreshContext(): Promise<void> {
		const active = isCandidateStage(this.active?.stage);
		const taskReady = Boolean(this.active?.taskDirectory);
		const submittable = this.active?.stage === 'committed_pending_accept' && this.active.gradeStatus === 'passed_local';
		await vscode.commands.executeCommand('setContext', 'modernity.episode.active', active);
		await vscode.commands.executeCommand('setContext', 'modernity.episode.taskReady', taskReady);
		await vscode.commands.executeCommand('setContext', 'modernity.episode.submittable', submittable);
		await vscode.commands.executeCommand('setContext', 'modernity.episode.syncPending', this.active?.stage === 'accepted_sync_pending');
		await vscode.commands.executeCommand('setContext', 'modernity.project.active', Boolean(this.active?.projectId || this.context.workspaceState.get<string>(PROJECT_ID_KEY)));
		// Scope Grade and Submit to the chat that ran /swe-session. An unknown session id (an
		// episode from before this was recorded) leaves the action hidden rather than
		// offering it everywhere.
		await vscode.commands.executeCommand(
			'_modernity.episode.setSessionId',
			active || taskReady ? this.active?.chatSessionId : undefined,
		).then(undefined, () => undefined);
	}
}

/** Public episode registry exposed to sibling built-in extensions. */
export interface IEpisodeWorkflow extends vscode.Disposable {
	isBenchmarkEpisodeSession(sessionId: string): boolean;
}

/** Register the benchmark episode workflow for the desktop Modernity extension. */
export function registerEpisodeWorkflow(context: vscode.ExtensionContext, output: vscode.LogOutputChannel): IEpisodeWorkflow {
	return new EpisodeWorkflow(context, output);
}

function newRepository(root: string): GitEpisodeRepository {
	return new GitEpisodeRepository(root);
}

function adoptPreparedCommit(active: IActiveEpisode, commitSha: string, treeSha: string): IActiveEpisode {
	const {
		taskName: _taskName,
		taskDirectory: _taskDirectory,
		taskRepositoryRoot: _taskRepositoryRoot,
		taskBaseCommit: _taskBaseCommit,
		taskFinalCommit: _taskFinalCommit,
		taskTraceSessionId: _taskTraceSessionId,
		taskEnvironmentVersion: _taskEnvironmentVersion,
		artifactFingerprint: _artifactFingerprint,
		failToPass: _failToPass,
		passToPass: _passToPass,
		firstPartyTestReviewPath: _firstPartyTestReviewPath,
		firstPartyTestReviewSha256: _firstPartyTestReviewSha256,
		gradeStatus: _gradeStatus,
		gradeReportPath: _gradeReportPath,
		taskPublication: _taskPublication,
		...episode
	} = active;
	return {
		...episode,
		finalCommitSha: commitSha,
		finalTreeSha: treeSha,
	};
}

function adoptTaskArtifact(active: IActiveEpisode, artifact: IEpisodeTaskArtifact): IActiveEpisode {
	const {
		gradeStatus: _gradeStatus,
		gradeReportPath: _gradeReportPath,
		taskPublication: _taskPublication,
		...withoutGrade
	} = active;
	const episode = active.artifactFingerprint === artifact.artifactFingerprint ? active : withoutGrade;
	return {
		...episode,
		taskName: artifact.taskName,
		taskDirectory: artifact.taskDirectory,
		taskRepositoryRoot: artifact.taskRepositoryRoot,
		taskBaseCommit: artifact.baseCommit,
		taskFinalCommit: artifact.finalCommit,
		taskTraceSessionId: artifact.traceSessionId,
		taskEnvironmentVersion: artifact.environmentVersion,
		artifactFingerprint: artifact.artifactFingerprint,
		firstPartyTestReviewPath: artifact.testReviewPath,
		firstPartyTestReviewSha256: artifact.testReviewSha256,
		failToPass: artifact.failToPass,
		passToPass: artifact.passToPass,
	};
}

function defaultTaskRepositoryRoot(active: IActiveEpisode): string {
	return path.join(
		path.dirname(active.repositoryRoot),
		`${active.projectSlug ?? path.basename(active.repositoryRoot)}-codimango`,
	);
}

function taskArtifactFromState(active: IActiveEpisode): IEpisodeTaskArtifact | undefined {
	if (
		!active.taskName
		|| !active.taskDirectory
		|| !active.taskRepositoryRoot
		|| !active.taskBaseCommit
		|| !active.taskFinalCommit
		|| !active.taskTraceSessionId
		|| !active.taskEnvironmentVersion
		|| !active.artifactFingerprint
		|| !active.firstPartyTestReviewPath
		|| !active.firstPartyTestReviewSha256
	) {
		return undefined;
	}
	return {
		taskName: active.taskName,
		taskDirectory: active.taskDirectory,
		taskRepositoryRoot: active.taskRepositoryRoot,
		baseCommit: active.taskBaseCommit,
		finalCommit: active.taskFinalCommit,
		traceSessionId: active.taskTraceSessionId,
		environmentVersion: active.taskEnvironmentVersion,
		artifactFingerprint: active.artifactFingerprint,
		testReviewPath: active.firstPartyTestReviewPath,
		testReviewSha256: active.firstPartyTestReviewSha256,
		failToPass: active.failToPass ?? [],
		passToPass: active.passToPass ?? [],
	};
}

function isCandidateStage(stage: EpisodeStage | undefined): boolean {
	return stage === 'active' || stage === 'committed_pending_accept';
}

function hasPreparedTestReview(active: IActiveEpisode): boolean {
	return Boolean(active.firstPartyTestReviewPath && active.firstPartyTestReviewSha256);
}

function withoutGrade(active: IActiveEpisode): IActiveEpisode {
	const {
		gradeStatus: _gradeStatus,
		gradeReportPath: _gradeReportPath,
		taskPublication: _taskPublication,
		...episode
	} = active;
	return episode;
}

function withoutTaskCandidate(active: IActiveEpisode, preserveTestReview: boolean): IActiveEpisode {
	const {
		taskName: _taskName,
		taskDirectory: _taskDirectory,
		taskRepositoryRoot: _taskRepositoryRoot,
		taskBaseCommit: _taskBaseCommit,
		taskFinalCommit: _taskFinalCommit,
		taskTraceSessionId: _taskTraceSessionId,
		taskEnvironmentVersion: _taskEnvironmentVersion,
		artifactFingerprint: _artifactFingerprint,
		failToPass: _failToPass,
		passToPass: _passToPass,
		firstPartyTestReviewPath,
		firstPartyTestReviewSha256,
		gradeStatus: _gradeStatus,
		gradeReportPath: _gradeReportPath,
		taskPublication: _taskPublication,
		...episode
	} = active;
	return preserveTestReview
		? { ...episode, firstPartyTestReviewPath, firstPartyTestReviewSha256 }
		: episode;
}

function runProcess(command: string, args: readonly string[], options: IProcessOptions): Promise<IProcessResult> {
	return new Promise((resolve, reject) => {
		execFile(command, [...args], {
			cwd: options.cwd,
			env: options.env,
			maxBuffer: 16 * 1024 * 1024,
		}, (error, stdout, stderr) => {
			const output = String(stdout ?? '');
			const errorOutput = String(stderr ?? '');
			if (error) {
				reject(new ProcessFailure(errorOutput.trim() || error.message, output, errorOutput));
				return;
			}
			resolve({ stdout: output, stderr: errorOutput });
		});
	});
}

function runGit(cwd: string, args: readonly string[], env?: NodeJS.ProcessEnv): Promise<IProcessResult> {
	return runProcess('git', ['-C', cwd, ...args], { cwd, env: env ?? process.env });
}

function commitIdentityArguments(args: readonly string[]): readonly string[] {
	return ['-c', 'user.name=Modernity', '-c', 'user.email=modernity@users.noreply.github.com', ...args];
}

function gitCredentialEnvironment(credential: { username: string; password: string }): NodeJS.ProcessEnv {
	const authorization = Buffer.from(`${credential.username}:${credential.password}`, 'utf8').toString('base64');
	return {
		...process.env,
		GIT_TERMINAL_PROMPT: '0',
		GIT_CONFIG_COUNT: '1',
		GIT_CONFIG_KEY_0: 'http.extraHeader',
		GIT_CONFIG_VALUE_0: `Authorization: Basic ${authorization}`,
	};
}

function getBackendBaseUrl(): string {
	return vscode.workspace.getConfiguration('modernity').get<string>('gatewayUrl', 'http://127.0.0.1:8000').trim().replace(/\/+$/, '');
}

function getWebBaseUrl(): string {
	const configured = vscode.workspace.getConfiguration('modernity').get<string>('webUrl', '').trim();
	return (configured || getBackendBaseUrl()).replace(/\/+$/, '');
}

function canonicalUuid(value: string): string {
	if (UUID_PATTERN.test(value)) {
		return value.toLowerCase();
	}
	const hash = createHash('sha256').update(value).digest('hex').split('');
	hash[12] = '5';
	hash[16] = ['8', '9', 'a', 'b'][Number.parseInt(hash[16], 16) % 4];
	const compact = hash.join('').slice(0, 32);
	return `${compact.slice(0, 8)}-${compact.slice(8, 12)}-${compact.slice(12, 16)}-${compact.slice(16, 20)}-${compact.slice(20)}`;
}

function slugify(value: string): string {
	const slug = value.normalize('NFKD').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
	return slug || `modernity-project-${randomUUID().slice(0, 8)}`;
}

function humanize(value: string): string {
	return value.replace(/[-_]+/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function summarizePrompt(prompt: string): string {
	const normalized = prompt.replace(/\s+/g, ' ').trim();
	return normalized.length <= 72 ? normalized : `${normalized.slice(0, 69)}...`;
}

function normalizeRemote(value: string): string {
	return value.trim().replace(/\.git$/, '').replace(/^git@github\.com:/, 'https://github.com/').replace(/\/+$/, '').toLowerCase();
}

function escapeMarkdown(value: string): string {
	return value.replace(/[\\`*_{}\[\]()<>#+.!|-]/g, '\\$&');
}

async function chooseWorkspaceFolder(folders: readonly vscode.WorkspaceFolder[]): Promise<vscode.WorkspaceFolder> {
	if (folders.length === 1) {
		return folders[0];
	}
	return pickRequired(folders.map(folder => ({
		label: folder.name,
		description: folder.uri.fsPath,
		value: folder,
	})), vscode.l10n.t('Choose the mod project folder'));
}

function chooseModId(slug: string): Promise<string> {
	return requiredInput({
		title: vscode.l10n.t('Minecraft Mod ID'),
		prompt: vscode.l10n.t('Use lowercase letters, digits, and underscores.'),
		value: slug.replace(/-/g, '_').slice(0, 64),
		validateInput: value => /^[a-z][a-z0-9_]{1,63}$/.test(value) ? undefined : vscode.l10n.t('Use 2-64 lowercase letters, digits, or underscores, starting with a letter.'),
	});
}

async function hasEntries(directory: string): Promise<boolean> {
	try {
		return (await fs.readdir(directory)).length > 0;
	} catch {
		return false;
	}
}

async function chooseCategory(): Promise<EpisodeCategory> {
	return pickRequired<EpisodeCategory>([
		{ label: vscode.l10n.t('New Mechanic'), description: vscode.l10n.t('Gameplay systems, behavior, commands, or progression'), value: 'new_mechanic' },
		{ label: vscode.l10n.t('Item Generation'), description: vscode.l10n.t('Items, recipes, blocks, equipment, or assets'), value: 'item_generation' },
		{ label: vscode.l10n.t('World Generation'), description: vscode.l10n.t('Biomes, structures, dimensions, or terrain'), value: 'world_generation' },
	], vscode.l10n.t('Classify this benchmark task'));
}

async function chooseComplexity(): Promise<EpisodeComplexity> {
	return pickRequired<EpisodeComplexity>([
		{ label: vscode.l10n.t('M — Medium'), description: vscode.l10n.t('Several coordinated files or behaviors'), value: 'M' },
		{ label: vscode.l10n.t('S — Small'), description: vscode.l10n.t('Focused change with a narrow evaluator'), value: 'S' },
		{ label: vscode.l10n.t('L — Large'), description: vscode.l10n.t('Cross-cutting system requiring substantial integration'), value: 'L' },
	], vscode.l10n.t('Estimate task complexity'));
}

async function pickRequired<T>(items: readonly IChoice<T>[], title: string): Promise<T> {
	const selected = await vscode.window.showQuickPick(items, { title, ignoreFocusOut: true });
	if (!selected) {
		throw new UserCancelledError();
	}
	return selected.value;
}

async function requiredInput(options: vscode.InputBoxOptions): Promise<string> {
	const value = await vscode.window.showInputBox({
		...options,
		ignoreFocusOut: true,
		validateInput: options.validateInput ?? (input => input.trim() ? undefined : vscode.l10n.t('A value is required.')),
	});
	if (!value) {
		throw new UserCancelledError();
	}
	return value.trim();
}

async function readManifestProjectId(workspaceRoot: string): Promise<string | undefined> {
	try {
		const raw = JSON.parse(await fs.readFile(path.join(workspaceRoot, '.modernity', 'project.json'), 'utf8')) as { project_id?: string };
		return typeof raw.project_id === 'string' && UUID_PATTERN.test(raw.project_id) ? raw.project_id : undefined;
	} catch {
		return undefined;
	}
}

async function environmentManifest(context: vscode.ExtensionContext, repository: GitEpisodeRepository): Promise<object> {
	let gitVersion = 'unknown';
	try {
		gitVersion = (await runGit(repository.root, ['--version'])).stdout.trim();
	} catch {
		// Validation records unavailable tools independently.
	}
	return {
		modernity_extension_version: String(context.extension.packageJSON.version ?? '0.0.1'),
		vscode_version: vscode.version,
		node_version: process.version,
		platform: process.platform,
		architecture: process.arch,
		git_version: gitVersion,
		minecraft_version: '26.2',
		neoforge_version: '26.2.0.7-beta',
		java_version: '25',
		gradle_version: '9.2.1',
	};
}
