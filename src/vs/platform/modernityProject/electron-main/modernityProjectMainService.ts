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
import { IProductService } from '../../product/common/productService.js';
import { asText, IRequestService } from '../../request/common/request.js';
import { StorageScope, StorageTarget } from '../../storage/common/storage.js';
import { IApplicationStorageMainService } from '../../storage/electron-main/storageMainService.js';
import {
	IModernityCreateProjectRequest,
	IModernityCreateProjectResult,
	IModernityProjectProvisionProgress,
	IModernityProjectService,
	ModernityProjectProvisionPhase,
} from '../common/modernityProject.js';

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';
const DAEMON_RUNTIME_PATH = '/tmp/modernity-workspace/daemon.json';
const INSTALLATION_ID_STORAGE_KEY = 'modernity.machine.installationId';

interface ApiMachineResponse {
	readonly machine: { readonly id: string };
}

interface ApiRepository {
	readonly github_repository_id: string;
	readonly clone_url: string;
	readonly html_url: string;
	readonly default_branch: string;
}

interface ApiProject {
	readonly id: string;
	readonly mod_id: string;
	readonly repository: ApiRepository | null;
}

interface ApiProjectResponse {
	readonly project: ApiProject;
}

interface ApiProjectPage {
	readonly items: readonly ApiProject[];
}

interface ApiRepositoryResponse {
	readonly repository: ApiRepository;
}

interface ApiGitCredentialResponse {
	readonly username: string;
	readonly password: string;
	readonly expires_at: string;
}

interface DaemonRuntime {
	readonly host: string;
	readonly port: number;
	readonly token: string;
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
		@IProductService private readonly productService: IProductService,
	) {
		super();
		this.apiBaseUrl = (productService.modernityApiBaseUrl ?? DEFAULT_API_BASE_URL).replace(/\/+$/, '');
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
		const projects = await this.backendRequest<ApiProjectPage>(
			'GET', '/api/v1/projects?limit=100', undefined, accessToken
		);
		const existingProject = projects.items.find(item => item.mod_id === modId);
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
		let runtime: DaemonRuntime;
		try {
			const content = await this.fileService.readFile(URI.file(DAEMON_RUNTIME_PATH));
			runtime = JSON.parse(content.value.toString()) as DaemonRuntime;
		} catch {
			throw new Error('The Modernity sandbox daemon is not running.');
		}
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
