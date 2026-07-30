/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { bufferToStream, VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { IRequestContext, IRequestOptions } from '../../../../base/parts/request/common/request.js';
import { IEncryptionMainService, KnownStorageProvider } from '../../../encryption/common/encryptionService.js';
import { NullLogService } from '../../../log/common/log.js';
import { IProductService } from '../../../product/common/productService.js';
import { AbstractRequestService, AuthInfo, Credentials } from '../../../request/common/request.js';
import { InMemoryStorageService, StorageScope, StorageTarget } from '../../../storage/common/storage.js';
import { ModernityAuthMainService } from '../../electron-main/modernityAuthMainService.js';

const REFRESH_TOKEN_STORAGE_KEY = 'modernity.auth.refreshToken';

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

class TestEncryptionService implements IEncryptionMainService {
	declare readonly _serviceBrand: undefined;

	async encrypt(value: string): Promise<string> { return `encrypted:${value}`; }
	async decrypt(value: string): Promise<string> { return value.replace(/^encrypted:/, ''); }
	async isEncryptionAvailable(): Promise<boolean> { return true; }
	async getKeyStorageProvider(): Promise<KnownStorageProvider> { return KnownStorageProvider.keychainAccess; }
	async setUsePlainTextEncryption(): Promise<void> { }
}

class TestStorageService extends InMemoryStorageService {
	readonly whenReady: Promise<void>;

	constructor() {
		super();
		this.whenReady = this.initialize();
	}
}

function response(statusCode: number, body?: object): IRequestContext {
	return {
		res: { statusCode, headers: {} },
		stream: bufferToStream(VSBuffer.fromString(body ? JSON.stringify(body) : '')),
	};
}

function requestPath(options: IRequestOptions): string {
	return new URL(options.url ?? '').pathname;
}

function createService(requestService: TestRequestService, storageService: TestStorageService): ModernityAuthMainService {
	const productService = {
		_serviceBrand: undefined,
		modernityApiBaseUrl: 'https://api.modernity.test',
	} as IProductService;
	return new ModernityAuthMainService(
		requestService,
		new TestEncryptionService(),
		storageService as never,
		productService,
		new NullLogService(),
	);
}

suite('ModernityAuthMainService', () => {
	const disposables = ensureNoDisposablesAreLeakedInTestSuite();

	test('starts signed out without a stored credential', async () => {
		const storage = disposables.add(new TestStorageService());
		const requests = disposables.add(new TestRequestService(() => response(500)));
		const service = disposables.add(createService(requests, storage));

		const state = await service.initialize();

		assert.deepStrictEqual({ state, requestCount: requests.requests.length }, {
			state: { status: 'signedOut' },
			requestCount: 0,
		});
	});

	test('restores a session and persists the rotated refresh token', async () => {
		const storage = disposables.add(new TestStorageService());
		await storage.whenReady;
		storage.store(REFRESH_TOKEN_STORAGE_KEY, 'encrypted:old-refresh', StorageScope.APPLICATION, StorageTarget.MACHINE);

		const requests = disposables.add(new TestRequestService(options => {
			switch (requestPath(options)) {
				case '/api/v1/auth/refresh':
					return response(200, {
						access_token: 'access',
						access_expires_at: '2099-01-01T00:00:00Z',
						refresh_token: 'new-refresh',
						refresh_expires_at: '2099-02-01T00:00:00Z',
						session_id: 'session-id',
					});
				case '/api/v1/auth/me':
					return response(200, {
						user: {
							id: 'user-id',
							github_user_id: '42',
							login: 'builder',
							display_name: 'Builder',
						},
						session: {
							id: 'session-id',
							client: 'ide',
							created_at: '2026-01-01T00:00:00Z',
							expires_at: '2099-02-01T00:00:00Z',
						},
					});
				case '/api/v1/github/installations':
					return response(200, {
						items: [{
							id: 'installation-id',
							github_installation_id: '9001',
							account: { login: 'builder' },
							permissions: { contents: 'write' },
							repository_selection: 'selected',
							is_default: true,
							status: 'active',
							last_refreshed_at: '2026-01-02T00:00:00Z',
							version: 2,
						}],
						next_cursor: null,
					});
				case '/api/v1/github/installations/installation-id/refresh':
					return response(200, {
						installation: {
							id: 'installation-id',
							github_installation_id: '9001',
							account: { login: 'builder' },
							permissions: { contents: 'write' },
							repository_selection: 'selected',
							is_default: true,
							status: 'active',
							last_refreshed_at: '2026-01-03T00:00:00Z',
							version: 3,
						},
					});
				default:
					return response(404);
			}
		}));
		const service = disposables.add(createService(requests, storage));

		const state = await service.initialize();
		const installations = await service.getGithubInstallations();
		const refreshed = await service.refreshGithubInstallation('installation-id', 2);

		assert.deepStrictEqual({
			state,
			installations,
			refreshed,
			storedRefresh: storage.get(REFRESH_TOKEN_STORAGE_KEY, StorageScope.APPLICATION),
			paths: requests.requests.map(requestPath),
			refreshHeaders: requests.requests[3].headers,
		}, {
			state: {
				status: 'signedIn',
				accessExpiresAt: '2099-01-01T00:00:00Z',
				user: {
					id: 'user-id',
					githubUserId: '42',
					login: 'builder',
					email: undefined,
					displayName: 'Builder',
					avatarUrl: undefined,
				},
				session: {
					id: 'session-id',
					client: 'ide',
					machineId: undefined,
					createdAt: '2026-01-01T00:00:00Z',
					expiresAt: '2099-02-01T00:00:00Z',
				},
			},
			installations: {
				items: [{
					id: 'installation-id',
					githubInstallationId: '9001',
					accountLogin: 'builder',
					permissions: { contents: 'write' },
					repositorySelection: 'selected',
					isDefault: true,
					status: 'active',
					lastRefreshedAt: '2026-01-02T00:00:00Z',
					version: 2,
				}],
				nextCursor: undefined,
			},
			refreshed: {
				id: 'installation-id',
				githubInstallationId: '9001',
				accountLogin: 'builder',
				permissions: { contents: 'write' },
				repositorySelection: 'selected',
				isDefault: true,
				status: 'active',
				lastRefreshedAt: '2026-01-03T00:00:00Z',
				version: 3,
			},
			storedRefresh: 'encrypted:new-refresh',
			paths: [
				'/api/v1/auth/refresh',
				'/api/v1/auth/me',
				'/api/v1/github/installations',
				'/api/v1/github/installations/installation-id/refresh',
			],
			refreshHeaders: {
				'Content-Type': 'application/json',
				Authorization: 'Bearer access',
				'If-Match': '2',
			},
		});
	});

	test('clears an invalid stored refresh token', async () => {
		const storage = disposables.add(new TestStorageService());
		await storage.whenReady;
		storage.store(REFRESH_TOKEN_STORAGE_KEY, 'encrypted:invalid', StorageScope.APPLICATION, StorageTarget.MACHINE);
		const requests = disposables.add(new TestRequestService(() => response(401, {
			code: 'AUTH_REFRESH_INVALID',
			message: 'Refresh token invalid.',
			request_id: 'request-id',
			retryable: false,
		})));
		const service = disposables.add(createService(requests, storage));

		const state = await service.initialize();

		assert.deepStrictEqual({
			state,
			storedRefresh: storage.get(REFRESH_TOKEN_STORAGE_KEY, StorageScope.APPLICATION),
		}, {
			state: { status: 'signedOut' },
			storedRefresh: undefined,
		});
	});

	test('starts and cancels the GitHub device flow', async () => {
		const storage = disposables.add(new TestStorageService());
		const requests = disposables.add(new TestRequestService(options => {
			if (requestPath(options) === '/api/v1/auth/device/start') {
				return response(201, {
					poll_token: 'poll-token',
					verification_uri: 'https://github.com/login/device',
					verification_uri_complete: 'https://github.com/login/device?user_code=ABCD',
					user_code: 'ABCD',
					interval_seconds: 60,
					expires_at: '2099-01-01T00:00:00Z',
				});
			}
			return response(204);
		}));
		const service = disposables.add(createService(requests, storage));

		const authorizing = await service.startAuthentication();
		await service.cancelAuthentication();
		const signedOut = await service.getState();

		assert.deepStrictEqual({ authorizing, signedOut, paths: requests.requests.map(requestPath) }, {
			authorizing: {
				status: 'authorizing',
				authorization: {
					verificationUri: 'https://github.com/login/device',
					verificationUriComplete: 'https://github.com/login/device?user_code=ABCD',
					userCode: 'ABCD',
					expiresAt: '2099-01-01T00:00:00Z',
				},
			},
			signedOut: { status: 'signedOut' },
			paths: ['/api/v1/auth/device/start', '/api/v1/auth/device/cancel'],
		});
	});
});
