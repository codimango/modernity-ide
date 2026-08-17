/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { bufferToStream, VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Event } from '../../../../base/common/event.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { IRequestContext, IRequestOptions } from '../../../../base/parts/request/common/request.js';
import { IModernityAuthService } from '../../../modernityAuth/common/modernityAuth.js';
import { IModernityDaemonService } from '../../../modernityDaemon/common/modernityDaemon.js';
import { NullLogService } from '../../../log/common/log.js';
import { IProductService } from '../../../product/common/productService.js';
import { AbstractRequestService, AuthInfo, Credentials } from '../../../request/common/request.js';
import { ModernityProjectMainService } from '../../electron-main/modernityProjectMainService.js';

class TestRequestService extends AbstractRequestService {
	readonly requests: IRequestOptions[] = [];

	constructor(private readonly handler: (options: IRequestOptions) => IRequestContext) {
		super(new NullLogService());
	}

	async request(options: IRequestOptions, _token: CancellationToken): Promise<IRequestContext> {
		this.requests.push(options);
		return this.handler(options);
	}

	async resolveProxy(): Promise<string | undefined> { return undefined; }
	async lookupAuthorization(_authInfo: AuthInfo): Promise<Credentials | undefined> { return undefined; }
	async lookupKerberosAuthorization(): Promise<string | undefined> { return undefined; }
	async loadCertificates(): Promise<string[]> { return []; }
}

function response(statusCode: number, body?: object): IRequestContext {
	return {
		res: { statusCode, headers: {} },
		stream: bufferToStream(VSBuffer.fromString(body ? JSON.stringify(body) : '')),
	};
}

suite('ModernityProjectMainService', () => {
	const disposables = ensureNoDisposablesAreLeakedInTestSuite();

	test('forwards the current cloud token only to remote daemon provisioning', async () => {
		let daemonBody: Record<string, string> = {};
		let daemonAuthorization: string | string[] | undefined;
		const requests = disposables.add(new TestRequestService(options => {
			const url = new URL(options.url ?? '');
			if (url.host === '127.0.0.1:43123') {
				daemonBody = JSON.parse(String(options.data ?? '{}')) as Record<string, string>;
				daemonAuthorization = options.headers?.Authorization;
				return response(200, {
					project_path: '/projects/example-mod',
					commit_sha: 'commit-sha',
					manifest_version: 2,
				});
			}

			switch (`${options.type} ${url.pathname}`) {
				case 'PUT /api/v1/machines/current':
					return response(200, { machine: { id: 'machine-id' } });
				case 'GET /api/v1/projects':
					return response(200, { items: [], next_cursor: null });
				case 'POST /api/v1/projects':
					return response(200, {
						project: {
							id: '550e8400-e29b-41d4-a716-446655440000',
							name: 'Example Mod',
							mod_id: 'example_mod',
							mod_name: 'Example Mod',
							group_id: 'com.modernity.example_mod',
							mod_version: '1.0.0',
							license: 'All Rights Reserved',
							template_id: 'neoforge',
							template_version: '26.2',
							lifecycle_status: 'active',
							last_opened_at: null,
							repository: null,
						},
					});
				case 'POST /api/v1/projects/550e8400-e29b-41d4-a716-446655440000/repository':
					return response(200, {
						repository: {
							github_repository_id: '9002',
							owner: 'builder',
							name: 'example-mod',
							full_name: 'builder/example-mod',
							clone_url: 'https://github.com/builder/example-mod.git',
							html_url: 'https://github.com/builder/example-mod',
							default_branch: 'main',
							head_sha: null,
						},
					});
				case 'POST /api/v1/projects/550e8400-e29b-41d4-a716-446655440000/repository/git-credential':
					return response(200, {
						username: 'x-access-token',
						password: 'git-token',
						expires_at: '2099-01-01T00:00:00Z',
					});
				case 'POST /api/v1/projects/550e8400-e29b-41d4-a716-446655440000/checkouts':
				case 'POST /api/v1/projects/550e8400-e29b-41d4-a716-446655440000/repository/refresh':
					return response(200, {});
				default:
					return response(404, { message: `Unexpected request: ${options.type} ${url.pathname}` });
			}
		}));

		const authService: IModernityAuthService = {
			_serviceBrand: undefined,
			onDidChangeState: Event.None,
			async initialize() { return { status: 'signedOut' }; },
			async getState() { return { status: 'signedOut' }; },
			async startAuthentication() { return { status: 'signedOut' }; },
			async cancelAuthentication() { },
			async retry() { return { status: 'signedOut' }; },
			async logout() { },
			async getAccessToken() { return 'cloud-access-token'; },
			async getGithubInstallations() {
				return {
					items: [{
						id: 'installation-id',
						githubInstallationId: '9001',
						accountLogin: 'builder',
						permissions: { contents: 'write' },
						repositorySelection: 'selected',
						isDefault: true,
						status: 'active',
						lastRefreshedAt: '2026-01-01T00:00:00Z',
						version: 1,
					}],
					nextCursor: undefined,
				};
			},
			async startGithubInstallation() {
				return { authorizationUrl: 'https://github.com', expiresAt: '2099-01-01T00:00:00Z' };
			},
			async refreshGithubInstallation() {
				throw new Error('Not used');
			},
		};
		const daemonService: IModernityDaemonService = {
			_serviceBrand: undefined,
			async ensureRunning() {
				return {
					host: '127.0.0.1',
					port: 43123,
					token: 'daemon-token',
					runtimeFile: '/state/daemon.json',
				};
			},
		};
		const storage = {
			whenReady: Promise.resolve(),
			get() { return undefined; },
			store() { },
		};
		const productService = {
			_serviceBrand: undefined,
			modernityApiBaseUrl: 'https://api.modernity.test',
			version: '0.1.0-test',
		} as IProductService;
		const service = disposables.add(new ModernityProjectMainService(
			requests,
			{ exists: async () => false } as never,
			storage as never,
			authService,
			daemonService,
			productService,
		));

		const result = await service.createProject({
			name: 'Example Mod',
			repositoryName: 'example-mod',
			destinationPath: '/projects',
		});

		assert.deepStrictEqual({
			result,
			daemonAuthorization,
			cloudAccessToken: daemonBody.cloud_access_token,
			template: [daemonBody.template_id, daemonBody.template_version],
		}, {
			result: {
				projectId: '550e8400-e29b-41d4-a716-446655440000',
				projectPath: '/projects/example-mod',
				repositoryUrl: 'https://github.com/builder/example-mod',
				commitSha: 'commit-sha',
			},
			daemonAuthorization: 'Bearer daemon-token',
			cloudAccessToken: 'cloud-access-token',
			template: ['neoforge', '26.2'],
		});
	});
});
