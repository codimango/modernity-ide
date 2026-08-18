/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { randomUUID } from 'crypto';
import { arch, hostname, platform } from 'os';
import { CancellationToken } from '../../../base/common/cancellation.js';
import { Emitter } from '../../../base/common/event.js';
import { Disposable } from '../../../base/common/lifecycle.js';
import { basename, join } from '../../../base/common/path.js';
import { URI } from '../../../base/common/uri.js';
import { IRequestContext } from '../../../base/parts/request/common/request.js';
import { IFileService } from '../../files/common/files.js';
import { IModernityAuthService } from '../../modernityAuth/common/modernityAuth.js';
import { IModernityDaemonService } from '../../modernityDaemon/common/modernityDaemon.js';
import { resolveModernityApiBaseUrl } from '../../product/common/modernityApi.js';
import { IProductService } from '../../product/common/productService.js';
import { asText, IRequestService } from '../../request/common/request.js';
import { StorageScope, StorageTarget } from '../../storage/common/storage.js';
import { IApplicationStorageMainService } from '../../storage/electron-main/storageMainService.js';
import {
	IModernityCreateProjectRequest,
	IModernityCreateProjectResult,
	IModernityCheckoutProjectRequest,
	IModernityProjectProvisionProgress,
	IModernityProjectService,
	IModernityProjectSummary,
	ModernityProjectProvisionPhase,
} from '../common/modernityProject.js';

const INSTALLATION_ID_STORAGE_KEY = 'modernity.machine.installationId';

interface ApiMachineResponse {
	readonly machine: { readonly id: string };
}

interface ApiRepository {
	readonly github_repository_id: string;
	readonly owner: string;
	readonly name: string;
	readonly full_name: string;
	readonly clone_url: string;
	readonly html_url: string;
	readonly default_branch: string;
	readonly head_sha: string | null;
}

interface ApiProject {
	readonly id: string;
	readonly name: string;
	readonly mod_id: string;
	readonly mod_name: string;
	readonly group_id: string;
	readonly mod_version: string;
	readonly license: string | null;
	readonly template_id: string | null;
	readonly template_version: string | null;
	readonly lifecycle_status: string;
	readonly last_opened_at: string | null;
	readonly repository: ApiRepository | null;
}

interface ApiProjectResponse {
	readonly project: ApiProject;
}

interface ApiProjectPage {
	readonly items: readonly ApiProject[];
	readonly next_cursor: string | null;
}

interface ApiRepositoryResponse {
	readonly repository: ApiRepository;
}

interface ApiGitCredentialResponse {
	readonly username: string;
	readonly password: string;
	readonly expires_at: string;
}

interface ApiCheckout {
	readonly machine: { readonly id: string };
	readonly absolute_path?: string;
	readonly state: string;
}

interface ApiCheckoutPage {
	readonly items: readonly ApiCheckout[];
	readonly next_cursor: string | null;
}

interface DaemonProvisionResponse {
	readonly project_path: string;
	readonly commit_sha: string;
	readonly manifest_version: number;
}

interface RequestErrorBody {
	readonly code?: string;
	readonly message?: string;
	readonly error?: { readonly message?: string; readonly where?: string };
}

export class ModernityProjectMainService extends Disposable implements IModernityProjectService {
	declare readonly _serviceBrand: undefined;

	private readonly _onDidChangeProvisionProgress = this._register(new Emitter<IModernityProjectProvisionProgress>());
	readonly onDidChangeProvisionProgress = this._onDidChangeProvisionProgress.event;

	private readonly apiBaseUrl: string;

	constructor(
		@IRequestService private readonly requestService: IRequestService,
		@IFileService private readonly fileService: IFileService,
		@IApplicationStorageMainService private readonly storageService: IApplicationStorageMainService,
		@IModernityAuthService private readonly authService: IModernityAuthService,
		@IModernityDaemonService private readonly daemonService: IModernityDaemonService,
		@IProductService private readonly productService: IProductService,
	) {
		super();
		this.apiBaseUrl = resolveModernityApiBaseUrl(productService.modernityApiBaseUrl);
	}

	async createProject(request: IModernityCreateProjectRequest): Promise<IModernityCreateProjectResult> {
		const projectName = request.name.trim();
		if (!projectName) {
			throw new Error('Enter a project name.');
		}
		const accessToken = await this.authService.getAccessToken();
		if (!accessToken) {
			throw new Error('Sign in to Modernity before creating a project.');
		}
		const installationPage = await this.authService.getGithubInstallations();
		const installation = installationPage.items.find(item => item.isDefault && item.status === 'active')
			?? installationPage.items.find(item => item.status === 'active');
		if (!installation) {
			throw new Error('Connect an active GitHub App installation before creating a project.');
		}

		const repositoryName = this.validateRepositoryName(request.repositoryName);
		const modId = this.modId(repositoryName);
		const slug = this.slug(repositoryName);
		const groupId = `com.modernity.${modId}`;
		const projectDestination = join(request.destinationPath, repositoryName);

		this.report('machine', 'Syncing this machine');
		const machine = await this.registerCurrentMachine(accessToken);

		this.report('project', 'Creating or resuming project metadata');
		const projects = await this.listAllProjects(accessToken);
		const existingProject = projects.find(item => item.mod_id === modId);
		const project: ApiProjectResponse = existingProject
			? { project: existingProject }
			: await this.backendRequest<ApiProjectResponse>(
				'POST',
				'/api/v1/projects',
				{
					name: projectName,
					slug,
					description: `A NeoForge mod created with Modernity`,
					mod_id: modId,
					mod_name: projectName,
					group_id: groupId,
					mod_version: '1.0.0',
					license: 'All Rights Reserved',
					template_id: 'neoforge',
					template_version: '26.2',
					minecraft_version: '26.2',
					neoforge_version: '26.2.0.7-beta',
					java_version: '25',
					gradle_version: '9.2.1',
					visibility: 'private',
					default_branch: 'main',
					settings: {},
				},
				accessToken,
				{ 'Idempotency-Key': `project-${randomUUID()}` },
			);

		this.report('repository', 'Creating or resuming the GitHub repository');
		const repository: ApiRepositoryResponse = project.project.repository
			? { repository: project.project.repository }
			: await this.backendRequest<ApiRepositoryResponse>(
				'POST',
				`/api/v1/projects/${encodeURIComponent(project.project.id)}/repository`,
				{
					mode: 'create',
					installation_id: installation.id,
					owner: installation.accountLogin,
					name: repositoryName,
					visibility: 'private',
					github_repository_id: null,
				},
				accessToken,
				{ 'Idempotency-Key': `repository-${randomUUID()}` },
			);

		this.report('credential', 'Preparing secure Git access');
		const credential = await this.backendRequest<ApiGitCredentialResponse>(
			'POST',
			`/api/v1/projects/${encodeURIComponent(project.project.id)}/repository/git-credential`,
			undefined,
			accessToken,
		);

		this.report('local', 'Generating, validating, and publishing the project');
		const provisioned = await this.daemonRequest<DaemonProvisionResponse>('/v1/projects/provision', {
			destination: projectDestination,
			project_id: project.project.id,
			mod_id: modId,
			mod_name: projectName,
			group_id: groupId,
			mod_version: '1.0.0',
			license: 'All Rights Reserved',
			template_id: 'neoforge',
			template_version: '26.2',
			repository_id: repository.repository.github_repository_id,
			repository_url: repository.repository.clone_url,
			default_branch: repository.repository.default_branch,
			git_username: credential.username,
			git_password: credential.password,
			git_author_name: installation.accountLogin,
			cloud_access_token: accessToken,
		});

		this.report('checkout', 'Registering the local checkout');
		await this.backendRequest(
			'POST',
			`/api/v1/projects/${encodeURIComponent(project.project.id)}/checkouts`,
			{
				machine_id: machine.machine.id,
				absolute_path: provisioned.project_path,
				folder_basename: basename(provisioned.project_path),
				manifest_version: provisioned.manifest_version,
				repository: {
					github_repository_id: repository.repository.github_repository_id,
					remote_url: repository.repository.clone_url,
				},
				state: 'present',
				is_primary: true,
			},
			accessToken,
			{ 'Idempotency-Key': `checkout-${randomUUID()}` },
		);

		this.report('refresh', 'Confirming the GitHub push');
		await this.backendRequest(
			'POST',
			`/api/v1/projects/${encodeURIComponent(project.project.id)}/repository/refresh`,
			undefined,
			accessToken,
		);
		this.report('complete', 'Project created');
		return {
			projectId: project.project.id,
			projectPath: provisioned.project_path,
			repositoryUrl: repository.repository.html_url,
			commitSha: provisioned.commit_sha,
		};
	}

	async listProjects(): Promise<readonly IModernityProjectSummary[]> {
		const accessToken = await this.requireAccessToken();
		const machine = await this.registerCurrentMachine(accessToken);
		const projects = await this.listAllProjects(accessToken);
		const summaries = await Promise.all(projects.map(async project => {
			const checkouts = await this.listAllCheckouts(project.id, accessToken);
			const currentCheckout = checkouts.find(checkout =>
				checkout.machine.id === machine.machine.id
				&& checkout.state === 'present'
				&& typeof checkout.absolute_path === 'string'
			);
			const checkoutPath = currentCheckout?.absolute_path
				&& await this.fileService.exists(URI.file(currentCheckout.absolute_path))
				? currentCheckout.absolute_path
				: undefined;
			return {
				projectId: project.id,
				name: project.name,
				modId: project.mod_id,
				lifecycleStatus: project.lifecycle_status,
				repositoryFullName: project.repository?.full_name,
				checkoutPath,
			} satisfies IModernityProjectSummary;
		}));
		return summaries.sort((first, second) => first.name.localeCompare(second.name));
	}

	async checkoutProject(request: IModernityCheckoutProjectRequest): Promise<IModernityCreateProjectResult> {
		const accessToken = await this.requireAccessToken();
		this.report('machine', 'Syncing this machine');
		const machine = await this.registerCurrentMachine(accessToken);
		const response = await this.backendRequest<ApiProjectResponse>(
			'GET',
			`/api/v1/projects/${encodeURIComponent(request.projectId)}`,
			undefined,
			accessToken,
		);
		const project = response.project;
		const repository = project.repository;
		if (!repository) {
			throw new Error('This project does not have a GitHub repository yet.');
		}
		if (project.template_id !== 'neoforge' || project.template_version !== '26.2') {
			throw new Error('Only NeoForge 26.2 projects can be checked out.');
		}
		const repositoryName = this.validateRepositoryName(repository.name);
		const destination = join(request.destinationPath, repositoryName);

		const checkouts = await this.listAllCheckouts(project.id, accessToken);
		const existing = checkouts.find(checkout =>
			checkout.machine.id === machine.machine.id
			&& checkout.state === 'present'
			&& typeof checkout.absolute_path === 'string'
		);
		if (existing?.absolute_path && await this.fileService.exists(URI.file(existing.absolute_path))) {
			return {
				projectId: project.id,
				projectPath: existing.absolute_path,
				repositoryUrl: repository.html_url,
				commitSha: repository.head_sha ?? '',
			};
		}

		this.report('credential', 'Preparing secure Git access');
		const credential = await this.backendRequest<ApiGitCredentialResponse>(
			'POST',
			`/api/v1/projects/${encodeURIComponent(project.id)}/repository/git-credential`,
			undefined,
			accessToken,
		);
		const repositoryHasHead = typeof repository.head_sha === 'string' && repository.head_sha.length > 0;
		this.report(
			'local',
			repositoryHasHead ? 'Cloning and verifying the project' : 'Generating and publishing the project',
		);
		const checkedOut = repositoryHasHead
			? await this.daemonRequest<DaemonProvisionResponse>('/v1/projects/checkout', {
				destination,
				project_id: project.id,
				mod_id: project.mod_id,
				template_id: project.template_id,
				template_version: project.template_version,
				repository_id: repository.github_repository_id,
				repository_url: repository.clone_url,
				default_branch: repository.default_branch,
				git_username: credential.username,
				git_password: credential.password,
			})
			: await this.daemonRequest<DaemonProvisionResponse>('/v1/projects/provision', {
				destination,
				project_id: project.id,
				mod_id: project.mod_id,
				mod_name: project.mod_name,
				group_id: project.group_id,
				mod_version: project.mod_version,
				license: project.license ?? 'All Rights Reserved',
				template_id: project.template_id,
				template_version: project.template_version,
				repository_id: repository.github_repository_id,
				repository_url: repository.clone_url,
				default_branch: repository.default_branch,
				git_username: credential.username,
				git_password: credential.password,
				git_author_name: repository.owner,
				cloud_access_token: accessToken,
			});

		this.report('checkout', 'Registering the local checkout');
		await this.backendRequest(
			'POST',
			`/api/v1/projects/${encodeURIComponent(project.id)}/checkouts`,
			{
				machine_id: machine.machine.id,
				absolute_path: checkedOut.project_path,
				folder_basename: basename(checkedOut.project_path),
				manifest_version: checkedOut.manifest_version,
				repository: {
					github_repository_id: repository.github_repository_id,
					remote_url: repository.clone_url,
				},
				state: 'present',
				is_primary: true,
			},
			accessToken,
			{ 'Idempotency-Key': `checkout-${randomUUID()}` },
		);
		this.report('refresh', 'Confirming the GitHub repository');
		await this.backendRequest(
			'POST',
			`/api/v1/projects/${encodeURIComponent(project.id)}/repository/refresh`,
			undefined,
			accessToken,
		);
		this.report('complete', 'Project checked out');
		return {
			projectId: project.id,
			projectPath: checkedOut.project_path,
			repositoryUrl: repository.html_url,
			commitSha: checkedOut.commit_sha,
		};
	}

	private async requireAccessToken(): Promise<string> {
		const accessToken = await this.authService.getAccessToken();
		if (!accessToken) {
			throw new Error('Sign in to Modernity first.');
		}
		return accessToken;
	}

	private async listAllProjects(accessToken: string): Promise<readonly ApiProject[]> {
		const projects: ApiProject[] = [];
		let cursor: string | null = null;
		do {
			const suffix: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
			const page: ApiProjectPage = await this.backendRequest<ApiProjectPage>(
				'GET', `/api/v1/projects?limit=100${suffix}`, undefined, accessToken
			);
			projects.push(...page.items);
			cursor = page.next_cursor;
		} while (cursor);
		return projects;
	}

	private async listAllCheckouts(
		projectId: string,
		accessToken: string,
	): Promise<readonly ApiCheckout[]> {
		const checkouts: ApiCheckout[] = [];
		let cursor: string | null = null;
		do {
			const suffix: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
			const page: ApiCheckoutPage = await this.backendRequest<ApiCheckoutPage>(
				'GET',
				`/api/v1/projects/${encodeURIComponent(projectId)}/checkouts?limit=100${suffix}`,
				undefined,
				accessToken,
			);
			checkouts.push(...page.items);
			cursor = page.next_cursor;
		} while (cursor);
		return checkouts;
	}

	private async registerCurrentMachine(accessToken: string): Promise<ApiMachineResponse> {
		await this.storageService.whenReady;
		let installationId = this.storageService.get(INSTALLATION_ID_STORAGE_KEY, StorageScope.APPLICATION);
		if (!installationId) {
			installationId = randomUUID();
			this.storageService.store(
				INSTALLATION_ID_STORAGE_KEY,
				installationId,
				StorageScope.APPLICATION,
				StorageTarget.MACHINE,
			);
		}
		return this.backendRequest<ApiMachineResponse>('PUT', '/api/v1/machines/current', {
			installation_id: installationId,
			display_name: hostname(),
			platform: platform(),
			architecture: arch(),
			app_version: this.productService.version,
		}, accessToken);
	}

	private async daemonRequest<T>(path: string, body: object): Promise<T> {
		const runtime = await this.daemonService.ensureRunning();
		return this.requestJson<T>(
			'POST',
			`http://${runtime.host}:${runtime.port}${path}`,
			body,
			{ Authorization: `Bearer ${runtime.token}` },
			15 * 60 * 1000,
		);
	}

	private backendRequest<T>(method: string, path: string, body: object | undefined, accessToken: string, headers?: Readonly<Record<string, string>>): Promise<T> {
		return this.requestJson<T>(method, `${this.apiBaseUrl}${path}`, body, {
			Authorization: `Bearer ${accessToken}`,
			...headers,
		}, 30_000);
	}

	private async requestJson<T>(method: string, url: string, body: object | undefined, headers: Readonly<Record<string, string>>, timeout: number): Promise<T> {
		let context: IRequestContext;
		try {
			context = await this.requestService.request({
				type: method,
				url,
				headers: { 'Content-Type': 'application/json', ...headers },
				data: body ? JSON.stringify(body) : undefined,
				disableCache: true,
				timeout,
				callSite: 'modernityProject',
			}, CancellationToken.None);
		} catch {
			throw new Error('Modernity could not reach a required local or cloud service.');
		}
		const responseBody = await asText(context) ?? '';
		const statusCode = context.res.statusCode ?? 0;
		if (statusCode < 200 || statusCode >= 300) {
			let error: RequestErrorBody = {};
			try {
				error = JSON.parse(responseBody) as RequestErrorBody;
			} catch {
				// Use the HTTP status fallback below.
			}
			throw new Error(error.message ?? error.error?.message ?? error.code ?? `Request failed (${statusCode}).`);
		}
		if (!responseBody) {
			return undefined as T;
		}
		return JSON.parse(responseBody) as T;
	}

	private validateRepositoryName(value: string): string {
		const normalized = value.trim();
		if (!/^[A-Za-z0-9._-]{1,100}$/.test(normalized) || normalized === '.' || normalized === '..') {
			throw new Error('Repository names may contain letters, numbers, periods, hyphens, and underscores.');
		}
		return normalized;
	}

	private modId(repositoryName: string): string {
		let value = repositoryName.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
		if (!/^[a-z]/.test(value)) {
			value = `mod_${value}`;
		}
		if (value.length < 2) {
			value = `${value}_mod`;
		}
		return value.slice(0, 64);
	}

	private slug(repositoryName: string): string {
		return repositoryName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
	}

	private report(phase: ModernityProjectProvisionPhase, message: string): void {
		this._onDidChangeProvisionProgress.fire({ phase, message });
	}
}
