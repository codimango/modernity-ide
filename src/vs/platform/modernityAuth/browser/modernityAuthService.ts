/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../base/common/event.js';
import { InstantiationType, registerSingleton } from '../../instantiation/common/extensions.js';
import { IModernityAuthService, IModernityGithubInstallation, IModernityGithubInstallationPage, IModernityGithubInstallStart, ModernityAuthState } from '../common/modernityAuth.js';

class BrowserModernityAuthService implements IModernityAuthService {
	declare readonly _serviceBrand: undefined;

	readonly onDidChangeState = Event.None;

	async initialize(): Promise<ModernityAuthState> { return { status: 'signedOut' }; }
	async getState(): Promise<ModernityAuthState> { return { status: 'signedOut' }; }
	async startAuthentication(): Promise<ModernityAuthState> { return { status: 'signedOut' }; }
	async cancelAuthentication(): Promise<void> { }
	async retry(): Promise<ModernityAuthState> { return { status: 'signedOut' }; }
	async logout(): Promise<void> { }
	async getAccessToken(): Promise<string | undefined> { return undefined; }
	async getGithubInstallations(): Promise<IModernityGithubInstallationPage> { return { items: [], nextCursor: undefined }; }
	async startGithubInstallation(): Promise<IModernityGithubInstallStart> { throw new Error('Modernity desktop authentication is unavailable.'); }
	async refreshGithubInstallation(): Promise<IModernityGithubInstallation> { throw new Error('Modernity desktop authentication is unavailable.'); }
}

registerSingleton(IModernityAuthService, BrowserModernityAuthService, InstantiationType.Delayed);
