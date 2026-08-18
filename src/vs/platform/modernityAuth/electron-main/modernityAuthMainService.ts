/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken } from '../../../base/common/cancellation.js';
import { Emitter } from '../../../base/common/event.js';
import { Disposable } from '../../../base/common/lifecycle.js';
import { IRequestContext } from '../../../base/parts/request/common/request.js';
import { IEncryptionMainService } from '../../encryption/common/encryptionService.js';
import { ILogService } from '../../log/common/log.js';
import {
	IModernityAuthService,
	IModernityAuthSession,
	IModernityAuthUser,
	IModernityGithubInstallation,
	IModernityGithubInstallationPage,
	IModernityGithubInstallStart,
	ModernityGithubInstallationStatus,
	ModernityAuthState,
} from '../common/modernityAuth.js';
import { resolveModernityApiBaseUrl } from '../../product/common/modernityApi.js';
import { IProductService } from '../../product/common/productService.js';
import { asText, IRequestService } from '../../request/common/request.js';
import { StorageScope, StorageTarget } from '../../storage/common/storage.js';
import { IApplicationStorageMainService } from '../../storage/electron-main/storageMainService.js';

const REFRESH_TOKEN_STORAGE_KEY = 'modernity.auth.refreshToken';
const REFRESH_MARGIN_MS = 60_000;
const REFRESH_RETRY_MS = 15_000;
const MAX_TIMER_DELAY_MS = 2_147_483_647;

interface ApiErrorBody {
	readonly code?: string;
	readonly retryable?: boolean;
	readonly details?: { readonly retry_after_seconds?: number };
}

interface DeviceStartResponse {
	readonly poll_token: string;
	readonly verification_uri: string;
	readonly verification_uri_complete?: string;
	readonly user_code: string;
	readonly interval_seconds: number;
	readonly expires_at: string;
}

interface DevicePendingResponse {
	readonly status: 'pending';
	readonly next_poll_seconds: number;
	readonly expires_at: string;
}

interface ApiUser {
	readonly id: string;
	readonly github_user_id: string;
	readonly login: string;
	readonly email?: string;
	readonly display_name?: string;
	readonly avatar_url?: string;
}

interface ApiSession {
	readonly id: string;
	readonly client: string;
	readonly machine_id?: string;
	readonly created_at: string;
	readonly expires_at: string;
}

interface TokenResponse {
	readonly access_token: string;
	readonly access_expires_at: string;
	readonly refresh_token: string;
	readonly refresh_expires_at: string;
	readonly session_id: string;
}

interface DeviceCredentialsResponse extends TokenResponse {
	readonly user: ApiUser;
}

interface MeResponse {
	readonly user: ApiUser;
	readonly session: ApiSession;
}

interface ApiGithubInstallation {
	readonly id: string;
	readonly github_installation_id: string;
	readonly account: { readonly login: string };
	readonly permissions: Readonly<Record<string, string>>;
	readonly repository_selection: 'all' | 'selected';
	readonly is_default: boolean;
	readonly status: ModernityGithubInstallationStatus;
	readonly last_refreshed_at: string;
	readonly version: number;
}

interface GithubInstallationPageResponse {
	readonly items: readonly ApiGithubInstallation[];
	readonly next_cursor?: string | null;
}

interface GithubInstallationResponse {
	readonly installation: ApiGithubInstallation;
}

interface GithubInstallStartResponse {
	readonly authorization_url: string;
	readonly expires_at: string;
	readonly installation?: ApiGithubInstallation | null;
}

class ModernityAuthRequestError extends Error {
	constructor(
		readonly statusCode: number,
		readonly code: string,
		readonly retryable: boolean,
		readonly retryAfterSeconds: number | undefined,
	) {
		super(code);
	}
}

export class ModernityAuthMainService extends Disposable implements IModernityAuthService {

	declare readonly _serviceBrand: undefined;

	private readonly _onDidChangeState = this._register(new Emitter<ModernityAuthState>());
	readonly onDidChangeState = this._onDidChangeState.event;

	private state: ModernityAuthState = { status: 'loading' };
	private initialization: Promise<ModernityAuthState> | undefined;
	private refreshOperation: Promise<boolean> | undefined;
	private refreshToken: string | undefined;
	private accessToken: string | undefined;
	private accessExpiresAt: string | undefined;
	private currentUser: IModernityAuthUser | undefined;
	private currentSession: IModernityAuthSession | undefined;
	private pollToken: string | undefined;
	private pollTimer: ReturnType<typeof setTimeout> | undefined;
	private refreshTimer: ReturnType<typeof setTimeout> | undefined;
	private lastOperation: 'restore' | 'login' = 'restore';

	private readonly apiBaseUrl: string;

	constructor(
		@IRequestService private readonly requestService: IRequestService,
		@IEncryptionMainService private readonly encryptionService: IEncryptionMainService,
		@IApplicationStorageMainService private readonly storageService: IApplicationStorageMainService,
		@IProductService productService: IProductService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
		this.apiBaseUrl = resolveModernityApiBaseUrl(productService.modernityApiBaseUrl);
	}

	initialize(): Promise<ModernityAuthState> {
		if (!this.initialization) {
			this.initialization = this.restoreSession();
		}
		return this.initialization;
	}

	async getState(): Promise<ModernityAuthState> {
		await this.initialize();
		return this.state;
	}

	async startAuthentication(): Promise<ModernityAuthState> {
		await this.initialize();
		if (this.state.status === 'authorizing') {
			return this.state;
		}

		this.lastOperation = 'login';
		this.clearPollTimer();
		try {
			const response = await this.requestJson<DeviceStartResponse>('POST', '/api/v1/auth/device/start', { client: 'ide' }, [201]);
			this.pollToken = response.poll_token;
			this.setState({
				status: 'authorizing',
				authorization: {
					verificationUri: response.verification_uri,
					verificationUriComplete: response.verification_uri_complete,
					userCode: response.user_code,
					expiresAt: response.expires_at,
				},
			});
			this.schedulePoll(Math.max(1, response.interval_seconds));
		} catch (error) {
			this.handleOperationError(error);
		}
		return this.state;
	}

	async cancelAuthentication(): Promise<void> {
		const pollToken = this.pollToken;
		this.pollToken = undefined;
		this.clearPollTimer();
		if (pollToken) {
			try {
				await this.requestJson('POST', '/api/v1/auth/device/cancel', { poll_token: pollToken }, [204]);
			} catch (error) {
				this.logService.debug('[Modernity Auth] Device cancellation request failed.', error);
			}
		}
		this.setState({ status: 'signedOut' });
	}

	async retry(): Promise<ModernityAuthState> {
		if (this.lastOperation === 'login' && !this.refreshToken) {
			return this.startAuthentication();
		}
		this.initialization = undefined;
		this.setState({ status: 'loading' });
		return this.initialize();
	}

	async logout(): Promise<void> {
		await this.initialize();
		this.clearPollTimer();
		this.clearRefreshTimer();
		if (this.accessToken) {
			try {
				await this.requestJson('POST', '/api/v1/auth/logout', {}, [204], this.accessToken);
			} catch (error) {
				this.logService.debug('[Modernity Auth] Remote logout failed; local credentials will still be cleared.', error);
			}
		}
		await this.clearCredentials();
		this.setState({ status: 'signedOut' });
	}

	async getAccessToken(): Promise<string | undefined> {
		await this.initialize();
		if (!this.accessToken || !this.accessExpiresAt) {
			return undefined;
		}
		if (Date.parse(this.accessExpiresAt) - Date.now() <= REFRESH_MARGIN_MS) {
			await this.refreshSession();
		}
		return this.accessToken;
	}

	private async restoreSession(): Promise<ModernityAuthState> {
		this.lastOperation = 'restore';
		try {
			this.refreshToken = await this.readRefreshToken();
			if (!this.refreshToken) {
				this.setState({ status: 'signedOut' });
				return this.state;
			}
			await this.refreshSession();
		} catch (error) {
			this.handleOperationError(error);
		}
		return this.state;
	}

	private refreshSession(): Promise<boolean> {
		if (!this.refreshOperation) {
			this.refreshOperation = this.doRefreshSession().finally(() => this.refreshOperation = undefined);
		}
		return this.refreshOperation;
	}

	private async doRefreshSession(): Promise<boolean> {
		if (!this.refreshToken) {
			this.setState({ status: 'signedOut' });
			return false;
		}

		try {
			const tokens = await this.requestJson<TokenResponse>('POST', '/api/v1/auth/refresh', {
				refresh_token: this.refreshToken,
				client: 'ide',
			}, [200]);
			await this.applyTokens(tokens);
			const me = await this.requestJson<MeResponse>('GET', '/api/v1/auth/me', undefined, [200], tokens.access_token);
			this.currentUser = this.toUser(me.user);
			this.currentSession = this.toSession(me.session);
			this.setState({ status: 'signedIn', user: this.currentUser, session: this.currentSession, accessExpiresAt: tokens.access_expires_at });
			this.scheduleRefresh();
			return true;
		} catch (error) {
			if (error instanceof ModernityAuthRequestError && this.isCredentialError(error.code)) {
				await this.clearCredentials();
				this.setState({ status: 'signedOut' });
				return false;
			}
			if (this.accessToken && this.accessExpiresAt && Date.parse(this.accessExpiresAt) > Date.now() && this.currentUser && this.currentSession) {
				this.scheduleRefresh(REFRESH_RETRY_MS);
				return true;
			}
			this.handleOperationError(error);
			return false;
		}
	}

	private schedulePoll(delaySeconds: number): void {
		this.clearPollTimer();
		this.pollTimer = setTimeout(() => void this.pollDeviceAuthorization(), delaySeconds * 1000);
	}

	private async pollDeviceAuthorization(): Promise<void> {
		const pollToken = this.pollToken;
		if (!pollToken || this.state.status !== 'authorizing') {
			return;
		}

		try {
			const response = await this.request('POST', '/api/v1/auth/device/poll', { poll_token: pollToken });
			if (response.statusCode === 202) {
				const pending = this.parseJson<DevicePendingResponse>(response.body);
				this.schedulePoll(Math.max(1, pending.next_poll_seconds));
				return;
			}
			if (response.statusCode !== 200) {
				throw this.requestError(response);
			}

			const credentials = this.parseJson<DeviceCredentialsResponse>(response.body);
			this.pollToken = undefined;
			await this.applyTokens(credentials);
			this.currentUser = this.toUser(credentials.user);
			const me = await this.requestJson<MeResponse>('GET', '/api/v1/auth/me', undefined, [200], credentials.access_token);
			this.currentSession = this.toSession(me.session);
			this.setState({ status: 'signedIn', user: this.currentUser, session: this.currentSession, accessExpiresAt: credentials.access_expires_at });
			this.scheduleRefresh();
		} catch (error) {
			if (error instanceof ModernityAuthRequestError && error.code === 'AUTH_DEVICE_SLOW_DOWN') {
				this.schedulePoll(Math.max(1, error.retryAfterSeconds ?? 5));
				return;
			}
			this.pollToken = undefined;
			if (error instanceof ModernityAuthRequestError && this.isCredentialError(error.code)) {
				await this.clearCredentials();
				this.setState({ status: 'signedOut' });
				return;
			}
			this.handleOperationError(error);
		}
	}

	private async applyTokens(tokens: TokenResponse): Promise<void> {
		await this.storeRefreshToken(tokens.refresh_token);
		this.refreshToken = tokens.refresh_token;
		this.accessToken = tokens.access_token;
		this.accessExpiresAt = tokens.access_expires_at;
	}

	async getGithubInstallations(): Promise<IModernityGithubInstallationPage> {
		const accessToken = await this.requireAccessToken();
		const response = await this.requestJson<GithubInstallationPageResponse>('GET', '/api/v1/github/installations', undefined, [200], accessToken);
		return {
			items: response.items.map(installation => this.toGithubInstallation(installation)),
			nextCursor: response.next_cursor ?? undefined,
		};
	}

	async startGithubInstallation(): Promise<IModernityGithubInstallStart> {
		const accessToken = await this.requireAccessToken();
		const response = await this.requestJson<GithubInstallStartResponse>(
			'POST',
			'/api/v1/github/installations/start',
			{ return_to: 'settings' },
			[200],
			accessToken,
		);
		return {
			authorizationUrl: response.authorization_url,
			expiresAt: response.expires_at,
			installation: response.installation ? this.toGithubInstallation(response.installation) : undefined,
		};
	}

	async refreshGithubInstallation(installationId: string, version: number): Promise<IModernityGithubInstallation> {
		const accessToken = await this.requireAccessToken();
		const response = await this.requestJson<GithubInstallationResponse>(
			'POST',
			`/api/v1/github/installations/${encodeURIComponent(installationId)}/refresh`,
			undefined,
			[200],
			accessToken,
			{ 'If-Match': String(version) },
		);
		return this.toGithubInstallation(response.installation);
	}

	private scheduleRefresh(delay = Math.max(1000, Date.parse(this.accessExpiresAt ?? '') - Date.now() - REFRESH_MARGIN_MS)): void {
		this.clearRefreshTimer();
		this.refreshTimer = setTimeout(() => void this.refreshSession(), Math.min(delay, MAX_TIMER_DELAY_MS));
	}

	private clearPollTimer(): void {
		if (this.pollTimer) {
			clearTimeout(this.pollTimer);
			this.pollTimer = undefined;
		}
	}

	private clearRefreshTimer(): void {
		if (this.refreshTimer) {
			clearTimeout(this.refreshTimer);
			this.refreshTimer = undefined;
		}
	}

	private async readRefreshToken(): Promise<string | undefined> {
		await this.storageService.whenReady;
		const encrypted = this.storageService.get(REFRESH_TOKEN_STORAGE_KEY, StorageScope.APPLICATION);
		if (!encrypted) {
			return undefined;
		}
		try {
			return await this.encryptionService.decrypt(encrypted);
		} catch (error) {
			this.storageService.remove(REFRESH_TOKEN_STORAGE_KEY, StorageScope.APPLICATION);
			this.logService.error('[Modernity Auth] Stored credentials could not be decrypted.', error);
			return undefined;
		}
	}

	private async storeRefreshToken(refreshToken: string): Promise<void> {
		await this.storageService.whenReady;
		try {
			const encrypted = await this.encryptionService.encrypt(refreshToken);
			this.storageService.store(REFRESH_TOKEN_STORAGE_KEY, encrypted, StorageScope.APPLICATION, StorageTarget.MACHINE);
		} catch (error) {
			this.storageService.remove(REFRESH_TOKEN_STORAGE_KEY, StorageScope.APPLICATION);
			throw new ModernityAuthRequestError(0, 'AUTH_SECURE_STORAGE_UNAVAILABLE', false, undefined);
		}
	}

	private async clearCredentials(): Promise<void> {
		await this.storageService.whenReady;
		this.storageService.remove(REFRESH_TOKEN_STORAGE_KEY, StorageScope.APPLICATION);
		this.refreshToken = undefined;
		this.accessToken = undefined;
		this.accessExpiresAt = undefined;
		this.currentUser = undefined;
		this.currentSession = undefined;
	}

	private setState(state: ModernityAuthState): void {
		this.state = state;
		this._onDidChangeState.fire(state);
	}

	private handleOperationError(error: Error): void {
		if (error instanceof ModernityAuthRequestError) {
			this.setState({ status: 'error', code: error.code, canRetry: error.retryable || error.statusCode === 0 || error.statusCode >= 500 });
			return;
		}
		this.logService.error('[Modernity Auth] Unexpected authentication failure.', error);
		this.setState({ status: 'error', code: 'AUTH_SERVICE_UNAVAILABLE', canRetry: true });
	}

	private isCredentialError(code: string): boolean {
		return code === 'AUTH_REFRESH_INVALID'
			|| code === 'AUTH_REFRESH_EXPIRED'
			|| code === 'AUTH_REFRESH_REPLAYED'
			|| code === 'AUTH_ACCESS_INVALID'
			|| code === 'AUTH_ACCESS_EXPIRED';
	}

	private toUser(user: ApiUser): IModernityAuthUser {
		return {
			id: user.id,
			githubUserId: user.github_user_id,
			login: user.login,
			email: user.email,
			displayName: user.display_name,
			avatarUrl: user.avatar_url,
		};
	}

	private toSession(session: ApiSession): IModernityAuthSession {
		return {
			id: session.id,
			client: session.client,
			machineId: session.machine_id,
			createdAt: session.created_at,
			expiresAt: session.expires_at,
		};
	}

	private toGithubInstallation(installation: ApiGithubInstallation): IModernityGithubInstallation {
		return {
			id: installation.id,
			githubInstallationId: installation.github_installation_id,
			accountLogin: installation.account.login,
			permissions: installation.permissions,
			repositorySelection: installation.repository_selection,
			isDefault: installation.is_default,
			status: installation.status,
			lastRefreshedAt: installation.last_refreshed_at,
			version: installation.version,
		};
	}

	private async requireAccessToken(): Promise<string> {
		const accessToken = await this.getAccessToken();
		if (!accessToken) {
			throw new ModernityAuthRequestError(401, 'AUTH_ACCESS_INVALID', false, undefined);
		}
		return accessToken;
	}

	private async requestJson<T>(method: string, path: string, body: object | undefined, expectedStatuses: readonly number[], accessToken?: string, headers?: Readonly<Record<string, string>>): Promise<T> {
		const response = await this.request(method, path, body, accessToken, headers);
		if (!expectedStatuses.includes(response.statusCode)) {
			throw this.requestError(response);
		}
		if (response.statusCode === 204) {
			return undefined as T;
		}
		return this.parseJson<T>(response.body);
	}

	private async request(method: string, path: string, body?: object, accessToken?: string, headers?: Readonly<Record<string, string>>): Promise<{ statusCode: number; body: string }> {
		let context: IRequestContext;
		try {
			context = await this.requestService.request({
				type: method,
				url: `${this.apiBaseUrl}${path}`,
				headers: {
					'Content-Type': 'application/json',
					...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
					...headers,
				},
				data: body ? JSON.stringify(body) : undefined,
				disableCache: true,
				timeout: 20_000,
				callSite: 'modernityAuth',
			}, CancellationToken.None);
		} catch (error) {
			throw new ModernityAuthRequestError(0, 'AUTH_SERVICE_UNAVAILABLE', true, undefined);
		}
		return {
			statusCode: context.res.statusCode ?? 0,
			body: await asText(context) ?? '',
		};
	}

	private requestError(response: { statusCode: number; body: string }): ModernityAuthRequestError {
		let error: ApiErrorBody = {};
		if (response.body) {
			try {
				error = this.parseJson<ApiErrorBody>(response.body);
			} catch {
				// The status still provides a safe generic error when the body is not the v1 envelope.
			}
		}
		return new ModernityAuthRequestError(
			response.statusCode,
			error.code ?? (response.statusCode >= 500 ? 'AUTH_SERVICE_UNAVAILABLE' : 'AUTH_REQUEST_FAILED'),
			error.retryable ?? response.statusCode >= 500,
			error.details?.retry_after_seconds,
		);
	}

	private parseJson<T>(value: string): T {
		return JSON.parse(value) as T;
	}

	override dispose(): void {
		this.clearPollTimer();
		this.clearRefreshTimer();
		super.dispose();
	}
}
