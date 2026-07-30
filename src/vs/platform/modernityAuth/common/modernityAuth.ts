/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../base/common/event.js';
import { createDecorator } from '../../instantiation/common/instantiation.js';

export const MODERNITY_AUTH_CHANNEL = 'modernityAuth';

export interface IModernityAuthUser {
	readonly id: string;
	readonly githubUserId: string;
	readonly login: string;
	readonly email: string | undefined;
	readonly displayName: string | undefined;
	readonly avatarUrl: string | undefined;
}

export interface IModernityAuthSession {
	readonly id: string;
	readonly client: string;
	readonly machineId: string | undefined;
	readonly createdAt: string;
	readonly expiresAt: string;
}

export type ModernityGithubInstallationStatus = 'active' | 'permission_missing' | 'suspended' | 'revoked';

export interface IModernityGithubInstallation {
	readonly id: string;
	readonly githubInstallationId: string;
	readonly accountLogin: string;
	readonly permissions: Readonly<Record<string, string>>;
	readonly repositorySelection: 'all' | 'selected';
	readonly isDefault: boolean;
	readonly status: ModernityGithubInstallationStatus;
	readonly lastRefreshedAt: string;
	readonly version: number;
}

export interface IModernityGithubInstallationPage {
	readonly items: readonly IModernityGithubInstallation[];
	readonly nextCursor: string | undefined;
}

export interface IModernityGithubInstallStart {
	readonly authorizationUrl: string;
	readonly expiresAt: string;
}

export interface IModernityDeviceAuthorization {
	readonly verificationUri: string;
	readonly verificationUriComplete: string | undefined;
	readonly userCode: string;
	readonly expiresAt: string;
}

export type ModernityAuthState =
	| { readonly status: 'loading' }
	| { readonly status: 'signedOut' }
	| { readonly status: 'authorizing'; readonly authorization: IModernityDeviceAuthorization }
	| { readonly status: 'signedIn'; readonly user: IModernityAuthUser; readonly session: IModernityAuthSession; readonly accessExpiresAt: string }
	| { readonly status: 'error'; readonly code: string; readonly canRetry: boolean };

export const IModernityAuthService = createDecorator<IModernityAuthService>('modernityAuthService');

export interface IModernityAuthService {
	readonly _serviceBrand: undefined;

	readonly onDidChangeState: Event<ModernityAuthState>;

	initialize(): Promise<ModernityAuthState>;
	getState(): Promise<ModernityAuthState>;
	startAuthentication(): Promise<ModernityAuthState>;
	cancelAuthentication(): Promise<void>;
	retry(): Promise<ModernityAuthState>;
	logout(): Promise<void>;
	getAccessToken(): Promise<string | undefined>;
	getGithubInstallations(): Promise<IModernityGithubInstallationPage>;
	startGithubInstallation(): Promise<IModernityGithubInstallStart>;
	refreshGithubInstallation(installationId: string, version: number): Promise<IModernityGithubInstallation>;
}
