/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/aiCustomizationManagement.css';
import * as DOM from '../../../../../base/browser/dom.js';
import { Disposable, DisposableStore } from '../../../../../base/common/lifecycle.js';
import { Emitter } from '../../../../../base/common/event.js';
import { getErrorMessage } from '../../../../../base/common/errors.js';
import { localize } from '../../../../../nls.js';
import { IConfigurationService, ConfigurationTarget } from '../../../../../platform/configuration/common/configuration.js';
import { ISecretStorageService } from '../../../../../platform/secrets/common/secrets.js';
import { IFileDialogService } from '../../../../../platform/dialogs/common/dialogs.js';
import { URI } from '../../../../../base/common/uri.js';
import { InputBox } from '../../../../../base/browser/ui/inputbox/inputBox.js';
import { Button } from '../../../../../base/browser/ui/button/button.js';
import { defaultButtonStyles, defaultInputBoxStyles } from '../../../../../platform/theme/browser/defaultStyles.js';
import { IContextViewService } from '../../../../../platform/contextview/browser/contextView.js';
import { Codicon } from '../../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../../base/common/themables.js';
import { INotificationService } from '../../../../../platform/notification/common/notification.js';
import { IFileService } from '../../../../../platform/files/common/files.js';
import { VSBuffer } from '../../../../../base/common/buffer.js';
import { IModernityAuthService, IModernityGithubInstallation, ModernityAuthState } from '../../../../../platform/modernityAuth/common/modernityAuth.js';
import { IOpenerService } from '../../../../../platform/opener/common/opener.js';

const $ = DOM.$;

/**
 * Extensible setting definition for Modernity.
 * New settings can be added by extending SETTING_DEFINITIONS.
 */
export interface IModernitySettingDefinition {
	readonly id: string;
	readonly label: string;
	readonly description: string;
	readonly category: ModernitySettingCategory;
	readonly type: 'string' | 'secret' | 'path' | 'path-file' | 'path-directory';
	readonly scope: 'application' | 'window' | 'resource';
	readonly defaultValue?: string;
	/** Whether to store via SecretStorage (for sensitive values). */
	readonly isSecret?: boolean;
}

export type ModernitySettingCategory = 'account' | 'secrets' | 'projects' | 'textures' | 'java' | 'general';

export const ModernitySettingCategoryLabels: Record<ModernitySettingCategory, string> = {
	account: localize('modernity.category.account', "Account"),
	secrets: localize('modernity.category.secrets', "Keys & Secrets"),
	projects: localize('modernity.category.projects', "Projects"),
	textures: localize('modernity.category.textures', "Generated Textures"),
	java: localize('modernity.category.java', "Java"),
	general: localize('modernity.category.general', "General"),
};

export const ModernitySettingCategoryDescriptions: Record<ModernitySettingCategory, string> = {
	account: localize('modernity.category.account.desc', "Manage your Modernity identity and GitHub connection."),
	secrets: localize('modernity.category.secrets.desc', "Manage API keys and secrets. Generic list starting with Meta API Key. Stored securely via OS keychain."),
	projects: localize('modernity.category.projects.desc', "Configure where compiled and uncompiled mod artifacts are stored. Workspace-level. 3 paths: uncompiled, jar, template."),
	textures: localize('modernity.category.textures.desc', "Single path for generated textures. Workspace-level."),
	java: localize('modernity.category.java.desc', "Java runtime configuration for mod building. Both executable and JAVA_HOME."),
	general: localize('modernity.category.general.desc', "General Modernity settings."),
};

/**
 * Default extensible setting definitions.
 * Add new entries here to extend the panel without changing UI code.
 * Per user feedback (T279032899):
 * - Secrets: generic list starting with Meta API Key (guaranteed necessary)
 * - Textures: single path
 * - Projects: 3 paths (uncompiled, jar, template)
 * - Java: both executable path and JAVA_HOME
 */
export const MODERNITY_SETTING_DEFINITIONS: IModernitySettingDefinition[] = [
	// Secrets & Keys - generic list starting with Meta API Key
	{
		id: 'modernity.secrets.metaApiKey',
		label: localize('modernity.secret.metaApiKey', "Meta API Key"),
		description: localize('modernity.secret.metaApiKey.desc', "Meta API key for authentication. Stored securely in system keychain. Add more keys via '+ Add Secret' below."),
		category: 'secrets',
		type: 'secret',
		scope: 'application',
		isSecret: true,
	},

	// Projects - workspace scope - 3 paths per confirmation
	{
		id: 'modernity.projects.uncompiledCodePath',
		label: localize('modernity.projects.uncompiledCodePath', "Uncompiled Code Output"),
		description: localize('modernity.projects.uncompiledCodePath.desc', "Directory where uncompiled / intermediate mod code is placed. Workspace setting."),
		category: 'projects',
		type: 'path-directory',
		scope: 'resource',
		defaultValue: '${workspaceFolder}/build/mod',
	},
	{
		id: 'modernity.projects.jarOutputPath',
		label: localize('modernity.projects.jarOutputPath', "JAR Output Path"),
		description: localize('modernity.projects.jarOutputPath.desc', "Directory where final .jar artifacts are written. Workspace setting."),
		category: 'projects',
		type: 'path-directory',
		scope: 'resource',
		defaultValue: '${workspaceFolder}/build/libs',
	},
	{
		id: 'modernity.projects.modTemplatePath',
		label: localize('modernity.projects.modTemplatePath', "Mod Template Path"),
		description: localize('modernity.projects.modTemplatePath.desc', "Path to the NeoForge mod template. Workspace setting."),
		category: 'projects',
		type: 'path-directory',
		scope: 'resource',
		defaultValue: '${workspaceFolder}/minecraft/mod-template/neoforge',
	},

	// Generated Textures - single path per confirmation
	{
		id: 'modernity.textures.generatedPath',
		label: localize('modernity.textures.generatedPath', "Generated Textures Path"),
		description: localize('modernity.textures.generatedPath.desc', "Directory where generated textures are stored. Workspace setting. Single path."),
		category: 'textures',
		type: 'path-directory',
		scope: 'resource',
		defaultValue: '${workspaceFolder}/src/generated/resources/assets',
	},

	// Java - both executable and JAVA_HOME per confirmation
	{
		id: 'modernity.java.path',
		label: localize('modernity.java.path', "Java Executable Path"),
		description: localize('modernity.java.path.desc', "Absolute path to Java executable (e.g. /usr/libexec/java_home/bin/java or C:\\Java\\bin\\java.exe). Empty uses system default. Workspace setting."),
		category: 'java',
		type: 'path-file',
		scope: 'resource',
		defaultValue: '',
	},
	{
		id: 'modernity.java.home',
		label: localize('modernity.java.home', "JAVA_HOME"),
		description: localize('modernity.java.home.desc', "JAVA_HOME directory. If set, overrides automatic detection. Workspace setting."),
		category: 'java',
		type: 'path-directory',
		scope: 'resource',
		defaultValue: '',
	},
];

export const CUSTOM_SECRETS_CONFIG_KEY = 'modernity.secrets.customKeys';
const MASKED_SECRET_VALUE = '••••••••••••••••';

interface IModernityDevConfiguration {
	readonly secrets?: Readonly<Record<string, string>>;
}

function isStringKeyedObject(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

type SettingInput = {
	definition: IModernitySettingDefinition;
	inputBox: InputBox;
	container: HTMLElement;
	browseButton?: Button;
	toggleVisibilityButton?: Button;
	statusBadge?: HTMLElement;
	disposables: DisposableStore;
	secretRevealed: boolean;
	realValue?: string;
};

type CustomSecretEntry = {
	keyName: string;
	inputBox: InputBox;
	keyInputBox: InputBox;
	container: HTMLElement;
	disposables: DisposableStore;
	secretRevealed: boolean;
};

export class ModernitySettingsWidget extends Disposable {

	readonly element: HTMLElement;
	private readonly _onDidChangeItemCount = this._register(new Emitter<number>());
	readonly onDidChangeItemCount = this._onDidChangeItemCount.event;

	private readonly scrollContainer: HTMLElement;
	private readonly headerContainer: HTMLElement;
	private readonly contentContainer: HTMLElement;
	private readonly settingsById = new Map<string, SettingInput>();
	private readonly customSecrets = new Map<string, CustomSecretEntry>();
	private readonly categorySections: HTMLElement[] = [];
	private customSecretsListContainer: HTMLElement | undefined;
	private readonly searchInputContainer: HTMLElement | undefined;
	private searchInputBox: InputBox | undefined;
	private accountContainer: HTMLElement | undefined;
	private accountPrimaryAction: HTMLElement | undefined;
	private accountRenderVersion = 0;

	private readonly settingDisposables = this._register(new DisposableStore());
	private readonly accountDisposables = this._register(new DisposableStore());

	constructor(
		private readonly mode: 'settings' | 'account',
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ISecretStorageService private readonly secretStorageService: ISecretStorageService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@INotificationService private readonly notificationService: INotificationService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
		@IModernityAuthService private readonly authService: IModernityAuthService,
	) {
		super();

		this.element = $('.modernity-settings-widget');
		this.element.style.display = 'flex';
		this.element.style.flexDirection = 'column';
		this.element.style.height = '100%';
		this.element.style.overflow = 'hidden';

		// Header with search and actions
		this.headerContainer = DOM.append(this.element, $('.modernity-settings-header'));
		this.headerContainer.style.padding = '8px 12px';
		this.headerContainer.style.display = 'flex';
		this.headerContainer.style.flexDirection = 'column';
		this.headerContainer.style.gap = '8px';
		this.headerContainer.style.flexShrink = '0';

		const titleRow = DOM.append(this.headerContainer, $('.modernity-settings-title-row'));
		titleRow.style.display = 'flex';
		titleRow.style.alignItems = 'center';
		titleRow.style.justifyContent = 'space-between';

		const title = DOM.append(titleRow, $('h2.modernity-settings-title'));
		title.style.margin = '0';
		title.style.fontSize = '13px';
		title.style.fontWeight = '600';
		title.style.display = 'flex';
		title.style.alignItems = 'center';
		title.style.gap = '6px';

		const titleIcon = DOM.append(title, $('span')) as HTMLElement;
		titleIcon.className = ThemeIcon.asClassName(this.mode === 'account' ? Codicon.account : Codicon.package);
		titleIcon.style.fontSize = '14px';
		DOM.append(title, document.createTextNode(this.mode === 'account'
			? localize('modernity.account.title', "Account")
			: localize('modernity.title', "Modernity Dev Settings")));

		const actionsRow = DOM.append(titleRow, $('.modernity-settings-actions'));
		actionsRow.style.display = 'flex';
		actionsRow.style.gap = '6px';

		// Export / Import JSON buttons
		if (this.mode === 'settings') {
			const exportButton = this._register(new Button(actionsRow, {
				...defaultButtonStyles,
				title: localize('modernity.export', "Export settings as JSON"),
			}));
			exportButton.label = localize('modernity.export.label', "Export JSON");
			this._register(exportButton.onDidClick(() => this.exportAsJson()));

			const importButton = this._register(new Button(actionsRow, {
				...defaultButtonStyles,
				secondary: true,
				title: localize('modernity.import', "Import settings from JSON"),
			}));
			importButton.label = localize('modernity.import.label', "Import");
			this._register(importButton.onDidClick(() => this.importFromJson()));
		}

		// Search
		const searchRow = DOM.append(this.headerContainer, $('.modernity-settings-search-row'));
		searchRow.style.display = 'flex';
		searchRow.style.alignItems = 'center';
		searchRow.style.gap = '8px';

		this.searchInputContainer = DOM.append(searchRow, $('.modernity-search-container'));
		this.searchInputContainer.style.flex = '1';
		searchRow.style.display = this.mode === 'settings' ? 'flex' : 'none';

		// Scrollable content
		this.scrollContainer = DOM.append(this.element, $('.modernity-settings-scroll'));
		this.scrollContainer.style.flex = '1';
		this.scrollContainer.style.overflowY = 'auto';
		this.scrollContainer.style.overflowX = 'hidden';
		this.scrollContainer.style.padding = '0 12px 12px 12px';

		this.contentContainer = DOM.append(this.scrollContainer, $('.modernity-settings-content'));
		this.contentContainer.style.display = 'flex';
		this.contentContainer.style.flexDirection = 'column';
		this.contentContainer.style.gap = '16px';

		this.createSearchBox();
		this.renderSettings();
		if (this.mode === 'account') {
			this._register(this.authService.onDidChangeState(state => this.renderAccountState(state)));
			void this.authService.getState().then(state => this.renderAccountState(state));
		}

		// Listen to configuration changes
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration('modernity')) {
				this.refreshFromConfiguration();
			}
		}));

		this._onDidChangeItemCount.fire(this.mode === 'settings' ? MODERNITY_SETTING_DEFINITIONS.length : 0);
	}

	private createSearchBox(): void {
		if (!this.searchInputContainer) {
			return;
		}
		this.searchInputBox = this._register(new InputBox(this.searchInputContainer, this.contextViewService, {
			placeholder: localize('modernity.search.placeholder', "Search settings..."),
			inputBoxStyles: defaultInputBoxStyles,
		}));
		this.searchInputBox.element.style.width = '100%';

		this._register(this.searchInputBox.onDidChange(value => {
			this.filterSettings(value);
		}));
	}

	focusSearch(): void {
		this.searchInputBox?.focus();
	}

	focusAccount(): void {
		this.accountPrimaryAction?.focus();
	}

	private filterSettings(query: string): void {
		const lower = query.toLowerCase().trim();
		if (!lower) {
			// Show all
			for (const [, entry] of this.settingsById) {
				entry.container.style.display = '';
			}
			for (const [, entry] of this.customSecrets) {
				entry.container.style.display = '';
			}
			// Show all category sections
			for (const section of this.categorySections) {
				section.style.display = '';
			}
			return;
		}

		// Group visibility tracking
		const categoryVisibility = new Map<string, boolean>();
		if ('account github sync profile name email logout'.includes(lower)) {
			categoryVisibility.set('account', true);
		}

		for (const [, entry] of this.settingsById) {
			const def = entry.definition;
			const haystack = `${def.label} ${def.description} ${def.id}`.toLowerCase();
			const matches = haystack.includes(lower);
			entry.container.style.display = matches ? '' : 'none';
			if (matches) {
				categoryVisibility.set(def.category, true);
			}
		}

		for (const [keyName, entry] of this.customSecrets) {
			const haystack = `${keyName} custom secret`.toLowerCase();
			const matches = haystack.includes(lower);
			entry.container.style.display = matches ? '' : 'none';
			if (matches) {
				categoryVisibility.set('secrets', true);
			}
		}

		for (const section of this.categorySections) {
			const cat = section.dataset['category'];
			if (!cat) { continue; }
			const hasVisible = categoryVisibility.get(cat as ModernitySettingCategory);
			section.style.display = hasVisible ? '' : 'none';
		}
	}

	private renderSettings(): void {
		// Group by category
		const byCategory = new Map<ModernitySettingCategory, IModernitySettingDefinition[]>();
		for (const def of MODERNITY_SETTING_DEFINITIONS) {
			if (!byCategory.has(def.category)) {
				byCategory.set(def.category, []);
			}
			byCategory.get(def.category)!.push(def);
		}

		const orderedCategories: ModernitySettingCategory[] = this.mode === 'account'
			? ['account']
			: ['secrets', 'projects', 'textures', 'java', 'general'];

		for (const category of orderedCategories) {
			const defs = byCategory.get(category) ?? [];
			if (category !== 'account' && defs.length === 0) { continue; }

			const categorySection = DOM.append(this.contentContainer, $('.modernity-settings-category'));
			this.categorySections.push(categorySection);
			categorySection.dataset['category'] = category;
			categorySection.classList.toggle('modernity-account-root', category === 'account');
			categorySection.style.display = 'flex';
			categorySection.style.flexDirection = 'column';
			categorySection.style.gap = '8px';
			categorySection.style.padding = '12px';
			categorySection.style.border = '1px solid var(--vscode-widget-border, transparent)';
			categorySection.style.borderRadius = '4px';
			categorySection.style.background = 'var(--vscode-sideBar-background, transparent)';

			const categoryHeader = DOM.append(categorySection, $('.modernity-category-header'));
			categoryHeader.style.display = 'flex';
			categoryHeader.style.flexDirection = 'column';
			categoryHeader.style.gap = '2px';
			categoryHeader.style.marginBottom = '4px';
			categoryHeader.style.display = category === 'account' ? 'none' : 'flex';

			const categoryTitle = DOM.append(categoryHeader, $('h3.modernity-category-title'));
			categoryTitle.style.margin = '0';
			categoryTitle.style.fontSize = '12px';
			categoryTitle.style.fontWeight = '600';
			categoryTitle.style.textTransform = 'uppercase';
			categoryTitle.style.letterSpacing = '0.5px';
			categoryTitle.textContent = ModernitySettingCategoryLabels[category];

			const categoryDesc = DOM.append(categoryHeader, $('span.modernity-category-desc'));
			categoryDesc.style.fontSize = '11px';
			categoryDesc.style.opacity = '0.8';
			categoryDesc.textContent = ModernitySettingCategoryDescriptions[category];

			const settingsList = DOM.append(categorySection, $('.modernity-settings-list'));
			settingsList.style.display = 'flex';
			settingsList.style.flexDirection = 'column';
			settingsList.style.gap = '12px';

			if (category === 'account') {
				this.accountContainer = DOM.append(settingsList, $('.modernity-account'));
				continue;
			}

			for (const def of defs) {
				const entry = this.createSettingRow(settingsList, def);
				this.settingsById.set(def.id, entry);
			}

			// Special handling for secrets: add custom secrets UI (generic list)
			if (category === 'secrets') {
				const customSection = DOM.append(categorySection, $('.modernity-custom-secrets-section'));
				customSection.style.marginTop = '12px';
				customSection.style.paddingTop = '12px';
				customSection.style.borderTop = '1px dashed var(--vscode-widget-border)';

				const customHeader = DOM.append(customSection, $('.modernity-custom-secrets-header'));
				customHeader.style.display = 'flex';
				customHeader.style.alignItems = 'center';
				customHeader.style.justifyContent = 'space-between';
				customHeader.style.marginBottom = '8px';

				const customTitle = DOM.append(customHeader, $('h4.modernity-custom-secrets-title'));
				customTitle.style.margin = '0';
				customTitle.style.fontSize = '12px';
				customTitle.style.fontWeight = '500';
				customTitle.textContent = localize('modernity.customSecrets.title', "Custom Secrets");

				const addButton = this._register(new Button(customHeader, {
					...defaultButtonStyles,
					secondary: true,
					title: localize('modernity.customSecrets.add', "Add a custom secret key"),
				}));
				addButton.label = localize('modernity.customSecrets.add.label', "+ Add Secret");
				this._register(addButton.onDidClick(() => this.promptAddCustomSecret()));

				this.customSecretsListContainer = DOM.append(customSection, $('.modernity-custom-secrets-list'));
				this.customSecretsListContainer.style.display = 'flex';
				this.customSecretsListContainer.style.flexDirection = 'column';
				this.customSecretsListContainer.style.gap = '8px';

				// Load existing custom secrets async
				void this.loadCustomSecrets();
			}
		}

		if (this.mode === 'settings') {
			const footer = DOM.append(this.contentContainer, $('.modernity-settings-footer'));
			footer.style.marginTop = '8px';
			footer.style.padding = '8px';
			footer.style.fontSize = '11px';
			footer.style.opacity = '0.7';
			footer.style.borderTop = '1px solid var(--vscode-widget-border)';

			const footerText = DOM.append(footer, $('span'));
			footerText.textContent = localize('modernity.footer', "Settings stored in settings.json (workspace for paths) + OS keychain for secrets. Generic secrets start with Meta API Key. Use + Add Secret for any custom key. Export saves all as JSON. Extend via MODERNITY_SETTING_DEFINITIONS.");
			void this.refreshFromConfiguration();
		}
	}

	private renderAccountState(state: ModernityAuthState): void {
		if (!this.accountContainer) {
			return;
		}
		this.accountDisposables.clear();
		DOM.clearNode(this.accountContainer);
		const renderVersion = ++this.accountRenderVersion;

		if (state.status !== 'signedIn') {
			const status = DOM.append(this.accountContainer, $('.modernity-account-empty'));
			status.textContent = state.status === 'loading'
				? localize('modernity.account.loading', "Loading account...")
				: localize('modernity.account.signedOut', "Not signed in to Modernity.");
			return;
		}

		const profile = DOM.append(this.accountContainer, $('.modernity-account-profile'));
		if (state.user.avatarUrl) {
			const avatar = DOM.append(profile, $('img.modernity-account-avatar')) as HTMLImageElement;
			avatar.src = state.user.avatarUrl;
			avatar.alt = '';
		} else {
			const avatar = DOM.append(profile, $('span.modernity-account-avatar.modernity-account-avatar-fallback'));
			avatar.classList.add(...ThemeIcon.asClassNameArray(Codicon.github));
			avatar.setAttribute('aria-hidden', 'true');
		}

		const identity = DOM.append(profile, $('.modernity-account-identity'));
		const kicker = DOM.append(identity, $('.modernity-account-kicker'));
		kicker.textContent = localize('modernity.account.yourProfile', "Your Profile");
		const name = DOM.append(identity, $('.modernity-account-name'));
		name.textContent = state.user.displayName ?? state.user.login;
		const login = DOM.append(identity, $('.modernity-account-login'));
		login.textContent = `@${state.user.login}`;

		const logoutButton = this.accountDisposables.add(new Button(profile, {
			...defaultButtonStyles,
			secondary: true,
			supportIcons: true,
			title: localize('modernity.account.logoutTitle', "Sign out of Modernity on this device"),
		}));
		logoutButton.label = `$(sign-out) ${localize('modernity.account.logout', "Sign Out")}`;
		logoutButton.element.classList.add('modernity-account-logout');
		this.accountPrimaryAction = logoutButton.element;
		this.accountDisposables.add(logoutButton.onDidClick(async () => {
			logoutButton.enabled = false;
			try {
				await this.authService.logout();
			} catch {
				logoutButton.enabled = true;
				this.notificationService.error(localize('modernity.account.logoutFailed', "Modernity could not complete logout."));
			}
		}));

		const identityDetails = this.createAccountSection(
			Codicon.github,
			localize('modernity.account.githubIdentity', "GitHub Identity"),
			localize('modernity.account.githubIdentityDescription', "Account used to sign in to Modernity."),
		);
		this.createAccountDetail(identityDetails, localize('modernity.account.username', "Username"), state.user.login);
		this.createAccountDetail(identityDetails, localize('modernity.account.email', "Email"), state.user.email ?? localize('modernity.account.privateEmail', "Private on GitHub"));
		this.createAccountDetail(identityDetails, localize('modernity.account.githubId', "GitHub ID"), state.user.githubUserId);
		this.createAccountDetail(identityDetails, localize('modernity.account.status', "Status"), localize('modernity.account.verified', "Verified"), Codicon.verified);

		const repositoryAccess = this.createAccountSection(
			Codicon.repo,
			localize('modernity.account.repositoryAccess', "Repository Access"),
			localize('modernity.account.repositoryAccessDescription', "Access granted through the Modernity GitHub App."),
		);
		void this.renderRepositoryAccess(repositoryAccess, state, renderVersion);

		const sessionDetails = this.createAccountSection(
			Codicon.deviceDesktop,
			localize('modernity.account.currentSession', "Current Session"),
			localize('modernity.account.currentSessionDescription', "This IDE session is backed by a rotating refresh credential."),
		);
		this.createAccountDetail(sessionDetails, localize('modernity.account.client', "Client"), state.session.client);
		this.createAccountDetail(sessionDetails, localize('modernity.account.created', "Created"), this.formatAccountDate(state.session.createdAt));
		this.createAccountDetail(sessionDetails, localize('modernity.account.accessRenews', "Access renews by"), this.formatAccountDate(state.accessExpiresAt));
		this.createAccountDetail(sessionDetails, localize('modernity.account.sessionExpires', "Session expires"), this.formatAccountDate(state.session.expiresAt), Codicon.clock);
	}

	private createAccountSection(icon: ThemeIcon, title: string, description: string): HTMLElement {
		if (!this.accountContainer) {
			throw new Error('Account container not initialized');
		}
		const section = DOM.append(this.accountContainer, $('.modernity-account-section'));
		const heading = DOM.append(section, $('.modernity-account-section-heading'));
		const iconElement = DOM.append(heading, $('span'));
		iconElement.classList.add(...ThemeIcon.asClassNameArray(icon));
		iconElement.setAttribute('aria-hidden', 'true');
		const headingText = DOM.append(heading, $('.modernity-account-section-heading-text'));
		DOM.append(headingText, $('h4')).textContent = title;
		DOM.append(headingText, $('p')).textContent = description;
		return DOM.append(section, $('.modernity-account-details'));
	}

	private createAccountDetail(container: HTMLElement, label: string, value: string, icon?: ThemeIcon): void {
		const row = DOM.append(container, $('.modernity-account-detail'));
		DOM.append(row, $('span.modernity-account-detail-label')).textContent = label;
		const valueElement = DOM.append(row, $('span.modernity-account-detail-value'));
		if (icon) {
			const iconElement = DOM.append(valueElement, $('span'));
			iconElement.classList.add(...ThemeIcon.asClassNameArray(icon));
			iconElement.setAttribute('aria-hidden', 'true');
		}
		DOM.append(valueElement, $('span')).textContent = value;
	}

	private async renderRepositoryAccess(container: HTMLElement, state: Extract<ModernityAuthState, { status: 'signedIn' }>, renderVersion: number): Promise<void> {
		DOM.append(container, $('.modernity-account-loading')).textContent = localize('modernity.account.loadingRepositories', "Loading...");
		try {
			const page = await this.authService.getGithubInstallations();
			if (renderVersion !== this.accountRenderVersion || !container.isConnected) {
				return;
			}
			DOM.clearNode(container);
			const installation = page.items.find(item => item.isDefault)
				?? page.items.find(item => item.status === 'active')
				?? page.items[0];
			if (!installation) {
				this.renderDisconnectedRepositoryAccess(container, state);
				return;
			}
			this.renderConnectedRepositoryAccess(container, state, installation);
		} catch {
			if (renderVersion !== this.accountRenderVersion || !container.isConnected) {
				return;
			}
			DOM.clearNode(container);
			const error = DOM.append(container, $('.modernity-account-repository-error'));
			error.setAttribute('role', 'alert');
			error.textContent = localize('modernity.account.repositoryLoadFailed', "Repository access could not be loaded.");
			const retry = this.accountDisposables.add(new Button(container, { ...defaultButtonStyles, secondary: true }));
			retry.label = localize('modernity.account.tryAgain', "Try Again");
			this.accountDisposables.add(retry.onDidClick(() => this.renderAccountState(state)));
		}
	}

	private renderDisconnectedRepositoryAccess(container: HTMLElement, state: Extract<ModernityAuthState, { status: 'signedIn' }>): void {
		const empty = DOM.append(container, $('.modernity-account-repository-empty'));
		DOM.append(empty, $('strong')).textContent = localize('modernity.account.notConnected', "Not Connected");
		DOM.append(empty, $('span')).textContent = localize('modernity.account.noInstallation', "No GitHub App installation is linked to this account.");
		const connect = this.accountDisposables.add(new Button(container, { ...defaultButtonStyles, supportIcons: true }));
		connect.label = `$(link-external) ${localize('modernity.account.connectRepositories', "Connect Repositories")}`;
		this.accountDisposables.add(connect.onDidClick(async () => {
			connect.enabled = false;
			try {
				const started = await this.authService.startGithubInstallation();
				if (started.installation?.status === 'active') {
					this.renderAccountState(state);
					return;
				}
				await this.openerService.open(URI.parse(started.authorizationUrl), { openExternal: true });
			} catch {
				connect.enabled = true;
				this.notificationService.error(localize('modernity.account.connectFailed', "Modernity could not open GitHub repository access."));
				this.renderAccountState(state);
			}
		}));
	}

	private renderConnectedRepositoryAccess(container: HTMLElement, state: Extract<ModernityAuthState, { status: 'signedIn' }>, installation: IModernityGithubInstallation): void {
		this.createAccountDetail(container, localize('modernity.account.repositoryAccount', "Account"), installation.accountLogin);
		this.createAccountDetail(
			container,
			localize('modernity.account.repositoryScope', "Repository Scope"),
			installation.repositorySelection === 'all'
				? localize('modernity.account.allRepositories', "All Repositories")
				: localize('modernity.account.selectedRepositories', "Selected Repositories"),
		);
		this.createAccountDetail(
			container,
			localize('modernity.account.permissions', "Permissions"),
			Object.entries(installation.permissions).map(([name, level]) => `${name}: ${level}`).join(', '),
		);
		this.createAccountDetail(container, localize('modernity.account.status', "Status"), this.installationStatusLabel(installation.status), this.installationStatusIcon(installation.status));

		const actions = DOM.append(container, $('.modernity-account-repository-actions'));
		const manage = this.accountDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		manage.label = `$(link-external) ${localize('modernity.account.manageGithub', "Manage on GitHub")}`;
		this.accountDisposables.add(manage.onDidClick(() => this.openerService.open(
			URI.parse(`https://github.com/settings/installations/${installation.githubInstallationId}`),
			{ openExternal: true },
		)));

		const refresh = this.accountDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		refresh.label = `$(refresh) ${localize('modernity.account.refreshStatus', "Refresh Status")}`;
		this.accountDisposables.add(refresh.onDidClick(async () => {
			refresh.enabled = false;
			try {
				await this.authService.refreshGithubInstallation(installation.id, installation.version);
				this.renderAccountState(state);
			} catch {
				refresh.enabled = true;
				this.notificationService.error(localize('modernity.account.refreshFailed', "Repository status could not be refreshed."));
			}
		}));
	}

	private installationStatusLabel(status: IModernityGithubInstallation['status']): string {
		switch (status) {
			case 'active': return localize('modernity.account.statusActive', "Active");
			case 'permission_missing': return localize('modernity.account.statusMissingPermissions', "Missing Permissions");
			case 'suspended': return localize('modernity.account.statusSuspended', "Suspended");
			case 'revoked': return localize('modernity.account.statusDisconnected', "Disconnected");
		}
	}

	private installationStatusIcon(status: IModernityGithubInstallation['status']): ThemeIcon {
		return status === 'active' ? Codicon.check : status === 'permission_missing' ? Codicon.warning : Codicon.error;
	}

	private formatAccountDate(value: string): string {
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? localize('modernity.account.unavailable', "Unavailable") : date.toLocaleString();
	}

	private async loadCustomSecrets(): Promise<void> {
		try {
			const customKeys = this.configurationService.getValue<string[]>(CUSTOM_SECRETS_CONFIG_KEY) || [];
			for (const keyName of customKeys) {
				if (this.customSecrets.has(keyName)) { continue; }
				const secretId = `modernity.secrets.custom.${keyName}`;
				const stored = await this.secretStorageService.get(secretId);
				this.createCustomSecretRow(keyName, stored ?? '');
			}
		} catch (err) {
			console.warn('[Modernity] Failed to load custom secrets', err);
		}
	}

	private async promptAddCustomSecret(): Promise<void> {
		// Simple prompt via input: we create a temporary row with key input focused
		const keyName = `custom_${Date.now()}`;
		const entry = this.createCustomSecretRow('', '');
		// Focus key input
		entry.keyInputBox.focus();
		// Auto-save will be handled when user fills and blurs
		// Store the placeholder key so we can track, but actual key will be updated on save
		this.customSecrets.set(keyName, entry);
		// Remove placeholder immediately and re-add with real key after user types
		// Instead, we create with empty key and let user type key name
		entry.container.dataset['secretKey'] = '';
	}

	private createCustomSecretRow(keyName: string, value: string): CustomSecretEntry {
		if (!this.customSecretsListContainer) {
			throw new Error('Custom secrets container not initialized');
		}

		const container = DOM.append(this.customSecretsListContainer, $('.modernity-custom-secret-row'));
		container.dataset['secretKey'] = keyName;
		container.style.display = 'flex';
		container.style.flexDirection = 'column';
		container.style.gap = '4px';
		container.style.padding = '6px';
		container.style.border = '1px solid var(--vscode-widget-border)';
		container.style.borderRadius = '3px';

		const keyRow = DOM.append(container, $('.modernity-custom-secret-key-row'));
		keyRow.style.display = 'flex';
		keyRow.style.alignItems = 'center';
		keyRow.style.gap = '6px';

		const keyInputContainer = DOM.append(keyRow, $('.modernity-custom-key-input-container'));
		keyInputContainer.style.flex = '1';

		const disposables = new DisposableStore();

		const keyInputBox = disposables.add(new InputBox(keyInputContainer, this.contextViewService, {
			placeholder: localize('modernity.customSecret.keyPlaceholder', "Secret name (e.g. MY_SERVICE_TOKEN)"),
			inputBoxStyles: defaultInputBoxStyles,
		}));
		keyInputBox.element.style.width = '100%';
		if (keyName) {
			keyInputBox.value = keyName;
		}

		const valueRow = DOM.append(container, $('.modernity-custom-secret-value-row'));
		valueRow.style.display = 'flex';
		valueRow.style.alignItems = 'center';
		valueRow.style.gap = '6px';

		const valueInputContainer = DOM.append(valueRow, $('.modernity-custom-value-input-container'));
		valueInputContainer.style.flex = '1';

		const inputBox = disposables.add(new InputBox(valueInputContainer, this.contextViewService, {
			placeholder: localize('modernity.customSecret.valuePlaceholder', "Secret value (stored securely)"),
			inputBoxStyles: defaultInputBoxStyles,
		}));
		inputBox.element.style.width = '100%';
		(inputBox.inputElement as HTMLInputElement).type = 'password';
		inputBox.value = value;

		// Toggle visibility
		const toggleBtn = disposables.add(new Button(valueRow, {
			...defaultButtonStyles,
			secondary: true,
			title: localize('modernity.toggleVisibility', "Toggle visibility"),
		}));
		toggleBtn.element.classList.add('modernity-icon-button');
		DOM.append(toggleBtn.element, $(`.codicon.codicon-eye`));

		let secretRevealed = false;
		disposables.add(toggleBtn.onDidClick(() => {
			secretRevealed = !secretRevealed;
			const inputEl = inputBox.inputElement as HTMLInputElement;
			inputEl.type = secretRevealed ? 'text' : 'password';
			toggleBtn.element.innerHTML = '';
			DOM.append(toggleBtn.element, $(`.codicon.codicon-${secretRevealed ? 'eye-closed' : 'eye'}`));
		}));

		// Delete button
		const deleteBtn = disposables.add(new Button(valueRow, {
			...defaultButtonStyles,
			secondary: true,
			title: localize('modernity.customSecret.delete', "Delete this secret"),
		}));
		DOM.append(deleteBtn.element, $(`.codicon.codicon-trash`));

		const entry: CustomSecretEntry = {
			keyName: keyName,
			inputBox,
			keyInputBox,
			container,
			disposables,
			secretRevealed: false,
		};

		// Save logic for custom secret
		const saveCustom = async () => {
			const newKey = keyInputBox.value.trim();
			const newValue = inputBox.value.trim();

			if (!newKey) {
				return;
			}

			// If key changed, delete old if exists
			const oldKey = entry.keyName;
			if (oldKey && oldKey !== newKey) {
				if (this.customSecrets.has(oldKey)) {
					this.customSecrets.delete(oldKey);
				}
				// Delete old secret storage
				try {
					await this.secretStorageService.delete(`modernity.secrets.custom.${oldKey}`);
				} catch { }
				// Update config list
				await this.updateCustomKeysList();
			}

			entry.keyName = newKey;
			container.dataset['secretKey'] = newKey;

			if (!this.customSecrets.has(newKey)) {
				this.customSecrets.set(newKey, entry);
			}

			const secretId = `modernity.secrets.custom.${newKey}`;
			if (newValue) {
				await this.secretStorageService.set(secretId, newValue);
			} else {
				await this.secretStorageService.delete(secretId);
			}

			await this.updateCustomKeysList();
		};

		disposables.add(DOM.addDisposableListener(keyInputBox.inputElement as HTMLInputElement, DOM.EventType.BLUR, () => void saveCustom()));
		disposables.add(DOM.addDisposableListener(inputBox.inputElement as HTMLInputElement, DOM.EventType.BLUR, () => void saveCustom()));
		disposables.add(DOM.addDisposableListener(keyInputBox.inputElement as HTMLInputElement, DOM.EventType.KEY_DOWN, (e: KeyboardEvent) => {
			if (e.key === 'Enter') {
				void saveCustom();
				(keyInputBox.inputElement as HTMLInputElement).blur();
			}
		}));
		disposables.add(DOM.addDisposableListener(inputBox.inputElement as HTMLInputElement, DOM.EventType.KEY_DOWN, (e: KeyboardEvent) => {
			if (e.key === 'Enter') {
				void saveCustom();
				(inputBox.inputElement as HTMLInputElement).blur();
			}
		}));

		disposables.add(deleteBtn.onDidClick(async () => {
			const k = entry.keyName || keyInputBox.value.trim();
			if (k) {
				try {
					await this.secretStorageService.delete(`modernity.secrets.custom.${k}`);
				} catch { }
				this.customSecrets.delete(k);
				await this.updateCustomKeysList();
			}
			disposables.dispose();
			container.remove();
		}));

		this.settingDisposables.add(disposables);

		if (keyName) {
			this.customSecrets.set(keyName, entry);
		}

		return entry;
	}

	private async updateCustomKeysList(): Promise<void> {
		const keys = Array.from(this.customSecrets.keys()).filter(k => k && k.trim().length > 0);
		// Also include keys from UI inputs that may not yet be in map but have value
		// Dedupe
		const unique = Array.from(new Set(keys));
		try {
			await this.configurationService.updateValue(CUSTOM_SECRETS_CONFIG_KEY, unique, ConfigurationTarget.USER);
		} catch (err) {
			console.warn('[Modernity] Failed to update custom keys list', err);
		}
	}

	private createSettingRow(parent: HTMLElement, def: IModernitySettingDefinition): SettingInput {
		const container = DOM.append(parent, $('.modernity-setting-row'));
		container.dataset['settingId'] = def.id;
		container.style.display = 'flex';
		container.style.flexDirection = 'column';
		container.style.gap = '4px';

		const labelRow = DOM.append(container, $('.modernity-setting-label-row'));
		labelRow.style.display = 'flex';
		labelRow.style.flexDirection = 'column';
		labelRow.style.gap = '2px';

		const label = DOM.append(labelRow, $('label.modernity-setting-label'));
		label.textContent = def.label;
		label.style.fontSize = '12px';
		label.style.fontWeight = '500';

		const description = DOM.append(labelRow, $('span.modernity-setting-description'));
		description.textContent = def.description;
		description.style.fontSize = '11px';
		description.style.opacity = '0.7';
		description.style.lineHeight = '1.3';

		const inputRow = DOM.append(container, $('.modernity-setting-input-row'));
		inputRow.style.display = 'flex';
		inputRow.style.alignItems = 'center';
		inputRow.style.gap = '6px';
		inputRow.style.marginTop = '4px';

		const inputContainer = DOM.append(inputRow, $('.modernity-input-container'));
		inputContainer.style.flex = '1';
		inputContainer.style.minWidth = '0';

		const disposables = new DisposableStore();

		const inputBox = disposables.add(new InputBox(inputContainer, this.contextViewService, {
			placeholder: def.defaultValue || '',
			inputBoxStyles: defaultInputBoxStyles,
		}));
		inputBox.element.style.width = '100%';

		if (def.isSecret) {
			(inputBox.inputElement as HTMLInputElement).type = 'password';
		}

		const entry: SettingInput = {
			definition: def,
			inputBox,
			container,
			disposables,
			secretRevealed: false,
		};

		// Show/hide toggle for secrets - eye reveals real key
		if (def.isSecret) {
			const toggleBtn = disposables.add(new Button(inputRow, {
				...defaultButtonStyles,
				secondary: true,
				title: localize('modernity.toggleVisibility', "Toggle visibility"),
			}));
			toggleBtn.element.classList.add('modernity-icon-button');
			DOM.append(toggleBtn.element, $(`.codicon.codicon-eye`));
			disposables.add(toggleBtn.onDidClick(() => {
				entry.secretRevealed = !entry.secretRevealed;
				const inputEl = inputBox.inputElement as HTMLInputElement;
				if (entry.secretRevealed) {
					// Show real value if we have it stored
					if (entry.realValue) {
						entry.inputBox.value = entry.realValue;
					}
					inputEl.type = 'text';
				} else {
					// Mask again if secret was saved
					if (entry.realValue) {
						entry.inputBox.value = MASKED_SECRET_VALUE;
					}
					inputEl.type = 'password';
				}
				toggleBtn.element.innerHTML = '';
				DOM.append(toggleBtn.element, $(`.codicon.codicon-${entry.secretRevealed ? 'eye-closed' : 'eye'}`));
			}));
			entry.toggleVisibilityButton = toggleBtn;
		}

		// Browse button for path types
		if (def.type === 'path' || def.type === 'path-directory' || def.type === 'path-file') {
			const browseBtn = disposables.add(new Button(inputRow, {
				...defaultButtonStyles,
				secondary: true,
				title: localize('modernity.browse', "Browse..."),
			}));
			browseBtn.label = localize('modernity.browse.label', "Browse");
			disposables.add(browseBtn.onDidClick(() => this.browseForPath(def, entry)));
			entry.browseButton = browseBtn;
		}

		// Save on Enter and on blur
		const inputEl = inputBox.inputElement as HTMLInputElement;
		disposables.add(DOM.addDisposableListener(inputEl, DOM.EventType.BLUR, () => {
			void this.saveSetting(def, entry);
		}));
		disposables.add(DOM.addDisposableListener(inputEl, DOM.EventType.KEY_DOWN, (e: KeyboardEvent) => {
			if (e.key === 'Enter') {
				void this.saveSetting(def, entry);
				inputEl.blur();
			}
		}));

		// Status badge for secrets - shows if saved via keychain, .env, or settings secrets map
		const statusBadge = DOM.append(inputRow, $('span.modernity-secret-status'));
		statusBadge.style.fontSize = '11px';
		statusBadge.style.minWidth = '120px';
		statusBadge.style.textAlign = 'right';
		statusBadge.style.opacity = '0.8';
		statusBadge.style.display = 'none';
		entry.statusBadge = statusBadge;

		// Add to main disposables
		this.settingDisposables.add(disposables);

		return entry;
	}

	private async browseForPath(def: IModernitySettingDefinition, entry: SettingInput): Promise<void> {
		try {
			const defaultUri = entry.inputBox.value ? URI.file(entry.inputBox.value) : undefined;
			const result = def.type === 'path-file'
				? await this.fileDialogService.showOpenDialog({
					canSelectFiles: true,
					canSelectFolders: false,
					canSelectMany: false,
					defaultUri,
					openLabel: localize('modernity.browse.openLabel', "Select"),
				})
				: await this.fileDialogService.showOpenDialog({
					canSelectFiles: false,
					canSelectFolders: true,
					canSelectMany: false,
					defaultUri,
					openLabel: localize('modernity.browse.openFolder', "Select Folder"),
				});

			if (result && result.length > 0) {
				entry.inputBox.value = result[0].fsPath;
				await this.saveSetting(def, entry);
			}
		} catch (err) {
			this.notificationService.error(localize('modernity.browse.error', "Failed to browse: {0}", String(err)));
		}
	}

	private async refreshFromConfiguration(): Promise<void> {
		for (const [id, entry] of this.settingsById) {
			const def = entry.definition;
			try {
				if (def.isSecret) {
					const stored = await this.secretStorageService.get(id);
					let realVal = stored ?? '';
					if (!realVal) {
						try {
							const devConfig = this.configurationService.getValue<IModernityDevConfiguration>('modernity.dev');
							const devSecrets = devConfig?.secrets ?? {};
							const fallbackFromDevSecrets = devSecrets['MODEL_API_KEY'] ?? devSecrets['model_api_key'] ?? devSecrets['LLM_API_KEY'] ?? devSecrets['META_API_KEY'] ?? '';
							const customKeys = this.configurationService.getValue<string[]>('modernity.secrets.customKeys') || [];
							let fallbackFromCustom = '';
							if (customKeys.includes('MODEL_API_KEY')) {
								fallbackFromCustom = await this.secretStorageService.get('modernity.secrets.custom.MODEL_API_KEY') ?? '';
							}
							if (fallbackFromDevSecrets) {
								realVal = fallbackFromDevSecrets;
							} else if (fallbackFromCustom) {
								realVal = fallbackFromCustom;
							}
						} catch { }
					}
					// Store real value for eye toggle, but display masked asterisks per user preference
					entry.realValue = realVal || undefined;
					if (realVal) {
						entry.inputBox.value = MASKED_SECRET_VALUE;
						entry.secretRevealed = false;
						const inputEl = entry.inputBox.inputElement as HTMLInputElement;
						inputEl.type = 'password';
					} else {
						entry.inputBox.value = '';
					}
					if (entry.statusBadge) {
						entry.statusBadge.style.display = 'none';
					}
				} else {
					const configValue = this.configurationService.getValue<string>(id);
					if (configValue !== undefined) {
						entry.inputBox.value = configValue;
					} else if (def.defaultValue) {
						entry.inputBox.value = '';
						entry.inputBox.setPlaceHolder(def.defaultValue);
					}
				}
			} catch (err) {
				console.warn(`[ModernitySettingsWidget] Failed to load ${id}:`, err);
			}
		}
	}

	private async saveSetting(def: IModernitySettingDefinition, entry: SettingInput): Promise<void> {
		const rawValue = entry.inputBox.value;
		// If showing masked asterisks, don't overwrite - user didn't change it
		if (rawValue === MASKED_SECRET_VALUE || /^[•*]+$/.test(rawValue)) {
			return;
		}
		const value = rawValue.trim();
		try {
			if (def.isSecret) {
				// Update cached real value for eye toggle
				if (value) {
					entry.realValue = value;
				} else {
					entry.realValue = undefined;
				}
				if (value) {
					await this.secretStorageService.set(def.id, value);
				} else {
					await this.secretStorageService.delete(def.id);
				}
				this.notificationService.info(localize('modernity.secret.saved', "Secret saved securely: {0}", def.label));
			} else {
				// Workspace scope for paths as per user preference
				const target = def.scope === 'resource' ? ConfigurationTarget.WORKSPACE : ConfigurationTarget.USER;
				if (value) {
					await this.configurationService.updateValue(def.id, value, target);
				} else {
					// Remove if empty - let default take over
					await this.configurationService.updateValue(def.id, undefined, target);
				}
			}
		} catch (err) {
			this.notificationService.error(localize('modernity.save.error', "Failed to save {0}: {1}", def.label, getErrorMessage(err)));
		}
	}

	private async exportAsJson(): Promise<void> {
		try {
			const exportData: Record<string, string | string[]> = {};
			for (const [id, entry] of this.settingsById) {
				const def = entry.definition;
				if (def.isSecret) {
					const val = await this.secretStorageService.get(id);
					if (val) {
						exportData[id] = val;
					}
				} else {
					const v = this.configurationService.getValue<string>(id);
					if (v) {
						exportData[id] = v;
					}
				}
			}
			// Include custom secrets
			for (const [keyName] of this.customSecrets) {
				const secretId = `modernity.secrets.custom.${keyName}`;
				const val = await this.secretStorageService.get(secretId);
				if (val) {
					exportData[secretId] = val;
				}
			}
			// Include custom keys list
			const customKeys = this.configurationService.getValue<string[]>(CUSTOM_SECRETS_CONFIG_KEY) || [];
			if (customKeys.length > 0) {
				exportData[CUSTOM_SECRETS_CONFIG_KEY] = customKeys;
			}

			const jsonStr = JSON.stringify(exportData, null, 2);
			const defaultUri = URI.file('modernity-settings.json');

			const result = await this.fileDialogService.showSaveDialog({
				defaultUri,
				filters: [{ name: 'JSON', extensions: ['json'] }],
				saveLabel: localize('modernity.export.saveLabel', "Export"),
			});

			if (result) {
				await this.fileService.writeFile(result, VSBuffer.fromString(jsonStr));
				this.notificationService.info(localize('modernity.export.success', "Modernity settings exported to {0}", result.fsPath));
			}
		} catch (err) {
			this.notificationService.error(localize('modernity.export.error', "Failed to export settings: {0}", getErrorMessage(err)));
		}
	}

	private async importFromJson(): Promise<void> {
		try {
			const result = await this.fileDialogService.showOpenDialog({
				canSelectFiles: true,
				canSelectFolders: false,
				canSelectMany: false,
				filters: [{ name: 'JSON', extensions: ['json'] }],
				openLabel: localize('modernity.import.openLabel', "Import"),
			});

			if (!result || result.length === 0) {
				return;
			}

			const fileUri = result[0];
			const content = await this.fileService.readFile(fileUri);
			const jsonStr = content.value.toString();
			const parsed: unknown = JSON.parse(jsonStr);

			if (!isStringKeyedObject(parsed)) {
				throw new Error('Invalid JSON format - expected object');
			}
			const data = parsed;

			let imported = 0;
			for (const [key, value] of Object.entries(data)) {
				if (key === CUSTOM_SECRETS_CONFIG_KEY && Array.isArray(value) && value.every(item => typeof item === 'string')) {
					await this.configurationService.updateValue(key, value, ConfigurationTarget.USER);
					continue;
				}
				if (typeof value !== 'string') { continue; }
				const def = MODERNITY_SETTING_DEFINITIONS.find(d => d.id === key);

				if (def?.isSecret || key.includes('secrets') || key.includes('secret') || key.includes('ApiKey') || key.includes('apiKey')) {
					await this.secretStorageService.set(key, value);
					// If custom secret, ensure UI
					if (key.startsWith('modernity.secrets.custom.')) {
						const customKeyName = key.replace('modernity.secrets.custom.', '');
						if (!this.customSecrets.has(customKeyName)) {
							this.createCustomSecretRow(customKeyName, value);
						} else {
							const existing = this.customSecrets.get(customKeyName);
							if (existing) {
								existing.inputBox.value = value;
								existing.keyInputBox.value = customKeyName;
							}
						}
					}
				} else {
					const target = def?.scope === 'resource' ? ConfigurationTarget.WORKSPACE : ConfigurationTarget.USER;
					await this.configurationService.updateValue(key, value, target);
				}

				const entry = this.settingsById.get(key);
				if (entry) {
					entry.inputBox.value = value;
				}
				imported++;
			}

			this.notificationService.info(localize('modernity.import.success', "Imported {0} setting(s) from {1}", imported, fileUri.fsPath));
			await this.refreshFromConfiguration();
			// Reload custom secrets list
			await this.loadCustomSecrets();

		} catch (err) {
			this.notificationService.error(localize('modernity.import.error', "Failed to import settings: {0}", getErrorMessage(err)));
		}
	}

	public layout(height: number, width: number): void {
		this.element.style.height = `${height}px`;
		this.element.style.width = `${width}px`;
	}

	public render(): void {
		void this.refreshFromConfiguration();
	}

	public fireItemCount(): void {
		this._onDidChangeItemCount.fire(this.mode === 'settings' ? MODERNITY_SETTING_DEFINITIONS.length + this.customSecrets.size : 0);
	}

	public revealLastItem(): void {
		this.scrollContainer.scrollTop = this.scrollContainer.scrollHeight;
	}
}
