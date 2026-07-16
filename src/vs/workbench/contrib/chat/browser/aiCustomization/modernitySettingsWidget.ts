/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as DOM from '../../../../../base/browser/dom.js';
import { Button } from '../../../../../base/browser/ui/button/button.js';
import { InputBox } from '../../../../../base/browser/ui/inputbox/inputBox.js';
import { Checkbox } from '../../../../../base/browser/ui/toggle/toggle.js';
import { Emitter } from '../../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../../base/common/lifecycle.js';
import { localize } from '../../../../../nls.js';
import { IContextViewService } from '../../../../../platform/contextview/browser/contextView.js';
import { IConfigurationService, ConfigurationTarget } from '../../../../../platform/configuration/common/configuration.js';
import { IFileService } from '../../../../../platform/files/common/files.js';
import { IOpenerService } from '../../../../../platform/opener/common/opener.js';
import { URI } from '../../../../../base/common/uri.js';
import { defaultButtonStyles, defaultCheckboxStyles, defaultInputBoxStyles } from '../../../../../platform/theme/browser/defaultStyles.js';
import { Codicon } from '../../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../../base/common/themables.js';
import { VSBuffer } from '../../../../../base/common/buffer.js';
import { INotificationService, Severity } from '../../../../../platform/notification/common/notification.js';
import { ILogService } from '../../../../../platform/log/common/log.js';
import { IWorkspaceContextService } from '../../../../../platform/workspace/common/workspace.js';

const $ = DOM.$;

/**
 * Shape of the Modernity dev settings persisted via configuration service
 * and optionally exported as JSON. Keep this extensible - new fields can be added
 * without breaking existing stored values.
 */
export interface IModernityDevSettings {
	/** Absolute path to Java executable or JDK home. Empty means auto-detect. */
	readonly javaPath: string;
	/** Root folder where uncompiled Modernity projects are created. */
	readonly projectsRoot: string;
	/** Folder where built .jar files go (or pattern). */
	readonly jarOutputPath: string;
	/** Whether generated / AI textures are enabled. */
	readonly generatedTexturesEnabled: boolean;
	/** Whether to generate textures on build. */
	readonly autoGenerateTextures: boolean;
	/** Optional texture style preset. */
	readonly textureStyle: string;
	/** Map of secret name -> value reference (not the raw secret when possible). */
	readonly secrets: Record<string, string>;
	/** Free-form extra config for forward compatibility. */
	readonly extra?: Record<string, unknown>;
}

export const DEFAULT_MODERNITY_SETTINGS: IModernityDevSettings = {
	javaPath: '',
	projectsRoot: '',
	jarOutputPath: '',
	generatedTexturesEnabled: true,
	autoGenerateTextures: false,
	textureStyle: 'pixel-art',
	secrets: {},
	extra: {},
};

export const MODERNITY_SETTINGS_CONFIG_KEY = 'modernity.dev';
export const MODERNITY_SETTINGS_JSON_FILENAME = 'modernity-dev-settings.json';

/**
 * Dev panel for Modernity-specific settings. Shows up as a tab in
 * Agent Settings below Hooks, MCP Servers, Plugins.
 *
 * Fields:
 * - javaPath
 * - projectsRoot / jarOutputPath
 * - generatedTextures toggle
 * - keys/secrets
 * Persists via IConfigurationService and optionally as a JSON file in
 * the workspace or user-data directory.
 */
export class ModernitySettingsWidget extends Disposable {

	readonly element: HTMLElement;

	private readonly _onDidChangeItemCount = this._register(new Emitter<number>());
	readonly onDidChangeItemCount = this._onDidChangeItemCount.event;

	private readonly _disposableStore = this._register(new DisposableStore());
	private readonly _inputStores = this._register(new DisposableStore());

	private _header!: HTMLElement;
	private _formContainer!: HTMLElement;
	private _footer!: HTMLElement;

	// Inputs
	private _javaPathInput!: InputBox;
	private _projectsRootInput!: InputBox;
	private _jarOutputInput!: InputBox;
	private _textureStyleInput!: InputBox;

	private _generatedTexturesCheckbox!: Checkbox;
	private _autoGenerateCheckbox!: Checkbox;

	// Secrets list
	private _secretsContainer!: HTMLElement;
	private _secretsListElement!: HTMLElement;
	private _secrets: Map<string, string> = new Map();

	private _lastSettings: IModernityDevSettings = DEFAULT_MODERNITY_SETTINGS;

	constructor(
		@IConfigurationService private readonly _configurationService: IConfigurationService,
		@IContextViewService private readonly _contextViewService: IContextViewService,
		@IOpenerService private readonly _openerService: IOpenerService,
		@IFileService private readonly _fileService: IFileService,
		@INotificationService private readonly _notificationService: INotificationService,
		@ILogService private readonly _logService: ILogService,
		@IWorkspaceContextService private readonly _workspaceContextService: IWorkspaceContextService,
	) {
		super();

		this.element = $('.modernity-settings-widget');
		this.element.classList.add('modernity-settings-widget');

		this._createHeader();
		this._createForm();
		this._createFooter();

		this._loadFromConfiguration();
		this._register(this._configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(MODERNITY_SETTINGS_CONFIG_KEY)) {
				this._loadFromConfiguration();
			}
		}));

		// Always report 1 so badge shows as configured; could be 0 if untouched.
		this._onDidChangeItemCount.fire(1);
	}

	private _createHeader(): void {
		this._header = DOM.append(this.element, $('.section-title-header'));
		const row = DOM.append(this._header, $('.section-title-row'));
		DOM.append(row, $('span.section-title-icon.codicon.codicon-game'));
		const title = DOM.append(row, $('h2.section-title'));
		title.textContent = localize('modernitySettingsTitle', "Modernity");

		const description = DOM.append(this._header, $('p.section-title-description'));
		DOM.append(description, $('span.section-title-description-text')).textContent = localize('modernitySettingsDesc', "Configure your Modernity modding environment - Java toolchain, project layout, generated textures, and secrets. Settings are stored in VS Code settings and can be exported as JSON.");
		description.appendChild(document.createTextNode(' '));
		const learnMore = DOM.append(description, $('a.section-title-link')) as HTMLAnchorElement;
		learnMore.textContent = localize('learnMoreModernity', "Learn more about Modernity");
		learnMore.href = 'https://github.com/codimango/modernity';
		this._disposableStore.add(DOM.addDisposableListener(learnMore, 'click', e => {
			e.preventDefault();
			void this._openerService.open(URI.parse(learnMore.href));
		}));

		// Actions row
		const actionsRow = DOM.append(this._header, $('.modernity-settings-actions-row'));

		const exportBtn = this._disposableStore.add(new Button(actionsRow, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('exportJson', "Export as JSON") }));
		exportBtn.label = `$(${Codicon.export.id}) ${localize('exportJson', "Export as JSON")}`;
		this._disposableStore.add(exportBtn.onDidClick(() => this._exportAsJson()));

		const importBtn = this._disposableStore.add(new Button(actionsRow, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('importJson', "Import from JSON") }));
		importBtn.label = `$(${Codicon.cloudDownload.id}) ${localize('importJson', "Import from JSON")}`;
		this._disposableStore.add(importBtn.onDidClick(() => this._importFromJson()));

		const resetBtn = this._disposableStore.add(new Button(actionsRow, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('resetDefaults', "Reset to defaults") }));
		resetBtn.label = `$(${Codicon.discard.id}) ${localize('resetDefaults', "Reset to defaults")}`;
		this._disposableStore.add(resetBtn.onDidClick(() => this._resetToDefaults()));
	}

	private _createForm(): void {
		this._formContainer = DOM.append(this.element, $('.modernity-settings-form'));

		// Java section
		this._createSectionHeader(localize('javaSection', "Java Toolchain"), localize('javaSectionDesc', "Path to Java executable or JDK home. Leave empty to auto-detect."));
		this._javaPathInput = this._createLabeledInput(localize('javaPathLabel', "Java Path"), localize('javaPathPlaceholder', "/path/to/java or /Library/Java/... or leave empty"), (value) => this._updateSetting('javaPath', value));
		this._createBrowseButton(this._javaPathInput, this._javaPathInput.element.parentElement as HTMLElement);

		DOM.append(this._formContainer, $('.modernity-settings-separator'));

		// Projects section
		this._createSectionHeader(localize('projectsSection', "Projects"), localize('projectsSectionDesc', "Where your mod sources and built artifacts live."));
		this._projectsRootInput = this._createLabeledInput(
			localize('projectsRootLabel', "Projects Root (uncompiled code)"),
			localize('projectsRootPlaceholder', "~/ModernityProjects or /Users/.../projects"),
			(value) => this._updateSetting('projectsRoot', value)
		);
		this._createBrowseButton(this._projectsRootInput, this._projectsRootInput.element.parentElement as HTMLElement);

		this._jarOutputInput = this._createLabeledInput(
			localize('jarOutputLabel', "JAR Output Path"),
			localize('jarOutputPlaceholder', "{projectsRoot}/{modId}/build/libs or leave empty for default"),
			(value) => this._updateSetting('jarOutputPath', value)
		);

		DOM.append(this._formContainer, $('.modernity-settings-separator'));

		// Textures section
		this._createSectionHeader(localize('texturesSection', "Generated Textures"), localize('texturesSectionDesc', "Controls AI-generated textures and related assets."));

		const texturesRow = DOM.append(this._formContainer, $('.modernity-settings-row'));
		const texturesLabelContainer = DOM.append(texturesRow, $('.modernity-settings-checkbox-container'));

		this._generatedTexturesCheckbox = this._disposableStore.add(new Checkbox(localize('generatedTexturesEnabled', "Enable generated textures"), false, defaultCheckboxStyles));
		texturesLabelContainer.appendChild(this._generatedTexturesCheckbox.domNode);
		DOM.append(texturesLabelContainer, $('span.modernity-settings-checkbox-label')).textContent = localize('generatedTexturesEnabled', "Enable generated textures");
		this._disposableStore.add(this._generatedTexturesCheckbox.onChange(() => {
			this._updateSetting('generatedTexturesEnabled', this._generatedTexturesCheckbox.checked);
		}));

		const autoRow = DOM.append(this._formContainer, $('.modernity-settings-row'));
		const autoContainer = DOM.append(autoRow, $('.modernity-settings-checkbox-container'));
		this._autoGenerateCheckbox = this._disposableStore.add(new Checkbox(localize('autoGenerateTextures', "Auto-generate on build"), false, defaultCheckboxStyles));
		autoContainer.appendChild(this._autoGenerateCheckbox.domNode);
		DOM.append(autoContainer, $('span.modernity-settings-checkbox-label')).textContent = localize('autoGenerateTextures', "Auto-generate on build");
		this._disposableStore.add(this._autoGenerateCheckbox.onChange(() => {
			this._updateSetting('autoGenerateTextures', this._autoGenerateCheckbox.checked);
		}));

		this._textureStyleInput = this._createLabeledInput(
			localize('textureStyleLabel', "Texture Style Preset"),
			localize('textureStylePlaceholder', "pixel-art, realistic, etc."),
			(value) => this._updateSetting('textureStyle', value)
		);

		DOM.append(this._formContainer, $('.modernity-settings-separator'));

		// Secrets section
		this._createSectionHeader(localize('secretsSection', "Keys / Secrets"), localize('secretsSectionDesc', "Environment keys and tokens used by Modernity services. Values are stored in settings - avoid committing secrets to git."));

		this._secretsContainer = DOM.append(this._formContainer, $('.modernity-settings-secrets-section'));
		this._secretsListElement = DOM.append(this._secretsContainer, $('.modernity-settings-secrets-list'));

		const secretsActions = DOM.append(this._secretsContainer, $('.modernity-settings-secrets-actions'));
		const addSecretBtn = this._disposableStore.add(new Button(secretsActions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		addSecretBtn.label = `$(${Codicon.add.id}) ${localize('addSecret', "Add Secret")}`;
		this._disposableStore.add(addSecretBtn.onDidClick(() => this._addSecretRow()));

		// Initialize with common keys from .env.sample
		this._ensureDefaultSecretKeys();
	}

	private _createFooter(): void {
		this._footer = DOM.append(this.element, $('.section-footer'));
		const footerDesc = DOM.append(this._footer, $('p.section-footer-description'));
		footerDesc.textContent = localize('modernityFooterDesc', "Settings are saved to {0} in your VS Code settings (User or Workspace). They are also kept extensible via an extra JSON bag so future keys don't require code changes.", '`modernity.dev`');

		const row = DOM.append(this._footer, $('.modernity-settings-footer-row'));
		const jsonName = DOM.append(row, $('code.modernity-settings-json-name'));
		jsonName.textContent = MODERNITY_SETTINGS_JSON_FILENAME;

		const openSettingsLink = DOM.append(row, $('a.section-footer-link')) as HTMLAnchorElement;
		openSettingsLink.textContent = localize('openSettingsJson', "Open Settings (JSON)");
		openSettingsLink.href = '#';
		this._disposableStore.add(DOM.addDisposableListener(openSettingsLink, 'click', (e) => {
			e.preventDefault();
			void this._openerService.open(URI.parse('command:workbench.action.openSettings?%5B%22modernity.dev%22%5D'));
		}));
	}

	private _createSectionHeader(title: string, description: string): void {
		const section = DOM.append(this._formContainer, $('.modernity-settings-section-header'));
		const titleEl = DOM.append(section, $('h3.modernity-settings-section-title'));
		titleEl.textContent = title;
		const descEl = DOM.append(section, $('p.modernity-settings-section-desc'));
		descEl.textContent = description;
	}

	private _createLabeledInput(label: string, placeholder: string, onChange: (value: string) => void): InputBox {
		const row = DOM.append(this._formContainer, $('.modernity-settings-row'));
		const labelEl = DOM.append(row, $('label.modernity-settings-label'));
		labelEl.textContent = label;

		const inputContainer = DOM.append(row, $('.modernity-settings-input-container'));
		const input = this._inputStores.add(new InputBox(inputContainer, this._contextViewService, {
			placeholder,
			inputBoxStyles: defaultInputBoxStyles,
			ariaLabel: label,
		}));
		this._disposableStore.add(input.onDidChange(() => onChange(input.value)));

		return input;
	}

	private _createBrowseButton(inputBox: InputBox, row: HTMLElement): void {
		// Add a subtle browse hint - actual folder picking would need dialog service.
		// For now we just show icon indicating path.
		const hint = DOM.append(row, $('span.modernity-settings-path-hint'));
		hint.classList.add(...ThemeIcon.asClassNameArray(Codicon.folderOpened));
		hint.title = localize('pathHint', "Absolute path or ~ expansion");
	}

	private _ensureDefaultSecretKeys(): void {
		if (this._secrets.size === 0) {
			// Suggest common env keys from .env.sample
			const commonKeys = [
				'GITHUB_CLIENT_ID',
				'GITHUB_CLIENT_SECRET',
				'MODERNITY_JWT_SECRET',
				'MODERNITY_PROJECTS_ROOT',
				'MODERNITY_TOKEN_ENCRYPTION_KEY',
			];
			for (const k of commonKeys) {
				if (!this._secrets.has(k)) {
					this._secrets.set(k, '');
				}
			}
		}
	}

	private _renderSecrets(): void {
		DOM.clearNode(this._secretsListElement);
		for (const [key, value] of this._secrets) {
			this._renderSecretRow(key, value);
		}
	}

	private _renderSecretRow(key: string, value: string): void {
		const row = DOM.append(this._secretsListElement, $('.modernity-settings-secret-row'));

		const keyContainer = DOM.append(row, $('.modernity-settings-secret-key-container'));
		const keyInput = this._inputStores.add(new InputBox(keyContainer, this._contextViewService, {
			placeholder: localize('secretKeyPlaceholder', "KEY_NAME"),
			inputBoxStyles: defaultInputBoxStyles,
			ariaLabel: localize('secretKeyAria', "Secret key name"),
		}));
		keyInput.value = key;

		const valueContainer = DOM.append(row, $('.modernity-settings-secret-value-container'));
		const valueInput = this._inputStores.add(new InputBox(valueContainer, this._contextViewService, {
			placeholder: localize('secretValuePlaceholder', "value"),
			inputBoxStyles: defaultInputBoxStyles,
			ariaLabel: localize('secretValueAria', "Secret value"),
		}));
		valueInput.value = value;
		// Mask secrets visually - switch type to password style via CSS class, but InputBox doesn't support password type by default.
		// We keep value but add class for masking if needed.

		let originalKey = key;

		this._inputStores.add(keyInput.onDidChange(() => {
			const newKey = keyInput.value.trim();
			if (newKey && newKey !== originalKey) {
				const oldVal = this._secrets.get(originalKey) ?? '';
				this._secrets.delete(originalKey);
				if (this._secrets.has(newKey)) {
					this._notificationService.notify({
						severity: Severity.Warning,
						message: localize('secretKeyExists', "A secret with key '{0}' already exists.", newKey),
					});
					keyInput.value = originalKey;
					return;
				}
				this._secrets.set(newKey, oldVal);
				originalKey = newKey;
				this._persist();
			} else if (!newKey) {
				// keep empty key temporarily, will clean on persist
				this._secrets.delete(originalKey);
				originalKey = '';
			}
		}));

		this._inputStores.add(valueInput.onDidChange(() => {
			if (originalKey) {
				this._secrets.set(originalKey, valueInput.value);
				this._persist();
			}
		}));

		const deleteBtn = DOM.append(row, $('a.modernity-settings-secret-delete.codicon.codicon-close')) as HTMLAnchorElement;
		deleteBtn.title = localize('deleteSecret', "Delete secret");
		deleteBtn.href = '#';
		this._disposableStore.add(DOM.addDisposableListener(deleteBtn, 'click', (e) => {
			e.preventDefault();
			if (originalKey) {
				this._secrets.delete(originalKey);
			}
			row.remove();
			this._persist();
		}));
	}

	private _addSecretRow(): void {
		const newKey = `NEW_SECRET_${this._secrets.size + 1}`;
		this._secrets.set(newKey, '');
		this._renderSecretRow(newKey, '');
		this._persist();
	}

	private _loadFromConfiguration(): void {
		try {
			const stored = this._configurationService.getValue<IModernityDevSettings>(MODERNITY_SETTINGS_CONFIG_KEY) as Partial<IModernityDevSettings> | undefined;
			const merged: IModernityDevSettings = {
				...DEFAULT_MODERNITY_SETTINGS,
				...(stored as object ?? {}),
				secrets: { ...(DEFAULT_MODERNITY_SETTINGS.secrets), ...(stored?.secrets ?? {}) },
				extra: { ...(DEFAULT_MODERNITY_SETTINGS.extra), ...(stored?.extra ?? {}) },
			};
			this._lastSettings = merged;
			this._applyToUI(merged);
		} catch (err) {
			this._logService.warn('ModernitySettingsWidget: failed to load config', err);
			this._applyToUI(DEFAULT_MODERNITY_SETTINGS);
		}
	}

	private _applyToUI(settings: IModernityDevSettings): void {
		if (this._javaPathInput) {
			this._javaPathInput.value = settings.javaPath ?? '';
		}
		if (this._projectsRootInput) {
			this._projectsRootInput.value = settings.projectsRoot ?? '';
		}
		if (this._jarOutputInput) {
			this._jarOutputInput.value = settings.jarOutputPath ?? '';
		}
		if (this._textureStyleInput) {
			this._textureStyleInput.value = settings.textureStyle ?? '';
		}
		if (this._generatedTexturesCheckbox) {
			this._generatedTexturesCheckbox.checked = !!settings.generatedTexturesEnabled;
		}
		if (this._autoGenerateCheckbox) {
			this._autoGenerateCheckbox.checked = !!settings.autoGenerateTextures;
		}

		this._secrets = new Map(Object.entries(settings.secrets ?? {}));
		this._ensureDefaultSecretKeys();
		this._renderSecrets();
	}

	private _collectFromUI(): IModernityDevSettings {
		const secrets: Record<string, string> = {};
		for (const [k, v] of this._secrets) {
			if (k.trim()) {
				secrets[k.trim()] = v;
			}
		}

		return {
			javaPath: this._javaPathInput?.value ?? this._lastSettings.javaPath,
			projectsRoot: this._projectsRootInput?.value ?? this._lastSettings.projectsRoot,
			jarOutputPath: this._jarOutputInput?.value ?? this._lastSettings.jarOutputPath,
			generatedTexturesEnabled: this._generatedTexturesCheckbox?.checked ?? this._lastSettings.generatedTexturesEnabled,
			autoGenerateTextures: this._autoGenerateCheckbox?.checked ?? this._lastSettings.autoGenerateTextures,
			textureStyle: this._textureStyleInput?.value ?? this._lastSettings.textureStyle,
			secrets,
			extra: this._lastSettings.extra ?? {},
		};
	}

	private _updateSetting<K extends keyof IModernityDevSettings>(key: K, value: IModernityDevSettings[K]): void {
		this._lastSettings = { ...this._lastSettings, [key]: value };
		this._persist();
	}

	private _persist(): void {
		const current = this._collectFromUI();
		this._lastSettings = current;
		this._configurationService.updateValue(MODERNITY_SETTINGS_CONFIG_KEY, current, ConfigurationTarget.USER)
			.catch(err => {
				this._logService.error('ModernitySettingsWidget: failed to save config', err);
				this._notificationService.error(localize('saveFailed', "Failed to save Modernity settings: {0}", String(err)));
			});

		// Also persist as JSON file under .modernity/ so settings survive outside VS Code settings sync
		// and are visible in the repo / workspace. Best-effort, don't block UI.
		void this._persistToFile(current);
	}

	private async _persistToFile(settings: IModernityDevSettings): Promise<void> {
		try {
			const folders = this._workspaceContextService.getWorkspace().folders;
			if (folders.length === 0) {
				return;
			}
			// Write to first workspace folder /.modernity/modernity-dev-settings.json
			const targetDir = URI.joinPath(folders[0].uri, '.modernity');
			try {
				await this._fileService.createFolder(targetDir);
			} catch {
				// folder may already exist
			}
			const targetFile = URI.joinPath(targetDir, MODERNITY_SETTINGS_JSON_FILENAME);
			const content = JSON.stringify(settings, null, 2);
			await this._fileService.writeFile(targetFile, VSBuffer.fromString(content));
		} catch (err) {
			this._logService.trace('ModernitySettingsWidget: file persist skipped', err);
		}
	}

	private async _exportAsJson(): Promise<void> {
		const current = this._collectFromUI();
		const json = JSON.stringify(current, null, 2);
		try {
			// Try to write to workspace folder if available, else show in notification with copy
			const blob = new Blob([json], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = MODERNITY_SETTINGS_JSON_FILENAME;
			a.click();
			URL.revokeObjectURL(url);

			this._notificationService.info(localize('exportedJson', "Exported Modernity settings as {0}", MODERNITY_SETTINGS_JSON_FILENAME));
		} catch (err) {
			this._logService.error('ModernitySettingsWidget: export failed', err);
			this._notificationService.error(localize('exportFailed', "Failed to export settings: {0}", String(err)));
		}

		// Also ensure file under .modernity/ is up to date
		void this._persistToFile(current);
	}

	private async _importFromJson(): Promise<void> {
		const input = DOM.getActiveWindow().prompt(localize('importPrompt', "Paste Modernity settings JSON to import:"));
		if (!input) {
			return;
		}
		try {
			const parsed = JSON.parse(input) as Partial<IModernityDevSettings>;
			const merged: IModernityDevSettings = {
				...DEFAULT_MODERNITY_SETTINGS,
				...parsed,
				secrets: { ...(DEFAULT_MODERNITY_SETTINGS.secrets), ...(parsed.secrets ?? {}) },
				extra: { ...(DEFAULT_MODERNITY_SETTINGS.extra), ...(parsed.extra ?? {}) },
			};
			this._lastSettings = merged;
			this._applyToUI(merged);
			await this._configurationService.updateValue(MODERNITY_SETTINGS_CONFIG_KEY, merged, ConfigurationTarget.USER);
			this._notificationService.info(localize('importSuccess', "Imported Modernity settings."));
		} catch (err) {
			this._notificationService.error(localize('importFailed', "Failed to parse JSON: {0}", String(err)));
		}
	}

	private async _resetToDefaults(): Promise<void> {
		this._lastSettings = { ...DEFAULT_MODERNITY_SETTINGS };
		this._applyToUI(DEFAULT_MODERNITY_SETTINGS);
		await this._configurationService.updateValue(MODERNITY_SETTINGS_CONFIG_KEY, DEFAULT_MODERNITY_SETTINGS, ConfigurationTarget.USER);
		this._notificationService.info(localize('resetSuccess', "Reset Modernity settings to defaults."));
	}

	layout(_height: number, _width: number): void {
		// Ensure input boxes re-layout on resize
		try {
			this._javaPathInput?.layout();
			this._projectsRootInput?.layout();
			this._jarOutputInput?.layout();
			this._textureStyleInput?.layout();
		} catch {
			// ignore
		}
	}

	focusSearch(): void {
		// Focus first input for quick editing
		try {
			this._javaPathInput?.focus();
			this._javaPathInput?.select();
		} catch {
			// ignore
		}
	}

	fireItemCount(): void {
		this._onDidChangeItemCount.fire(1);
	}
}
