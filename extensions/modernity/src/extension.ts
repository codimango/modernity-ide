/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { ModernityLanguageModelProvider } from './modernityProvider';

// Node-only sandbox tooling is loaded lazily so the browser bundle never runs it.
let stopSandbox: (() => void) | undefined;

// Dev toggle panel IDE - constants per spec
// Simple mode = locked chat panel only
// Developer mode = code viewer, file tree, settings, plus bonus debug/search/scm
// Never allowed: left_panel (activity bar) and terminal
export const SIMPLE_MODE = 'simple';
export const DEVELOPER_MODE = 'developer';
export const SIMPLE_PANELS = ['chat'] as const;
export const DEV_PANELS = ['chat', 'code_viewer', 'file_tree', 'settings', 'debug', 'search', 'source_control'] as const;
export const NEVER_ALLOWED = ['terminal'] as const; // per latest: only terminal never, left panel condensed (less features) per user update
export const BONUS_DEV_FEATURES = ['debug', 'search', 'source_control'] as const;
export const CONDENSED_LEFT_PANEL = ['file_tree', 'debug', 'search', 'source_control'] as const; // per latest: need left panel but condensed, not everything

export class PanelManager {
	private _mode: typeof SIMPLE_MODE | typeof DEVELOPER_MODE;

	public constructor(mode: typeof SIMPLE_MODE | typeof DEVELOPER_MODE = SIMPLE_MODE) {
		this._mode = mode;
	}

	public isSimpleMode(): boolean {
		return this._mode === SIMPLE_MODE;
	}

	public isDeveloperMode(): boolean {
		return this._mode === DEVELOPER_MODE;
	}

	public getMode(): string {
		return this._mode;
	}

	public setMode(mode: typeof SIMPLE_MODE | typeof DEVELOPER_MODE): void {
		if (mode !== SIMPLE_MODE && mode !== DEVELOPER_MODE) {
			throw new Error(`Invalid mode ${mode}`);
		}
		this._mode = mode;
	}

	public toggle(): typeof SIMPLE_MODE | typeof DEVELOPER_MODE {
		this._mode = this._mode === SIMPLE_MODE ? DEVELOPER_MODE : SIMPLE_MODE;
		return this._mode;
	}

	public isPanelAllowed(panel: string): boolean {
		return !(NEVER_ALLOWED as readonly string[]).includes(panel);
	}

	public getVisiblePanels(): string[] {
		const base = this._mode === SIMPLE_MODE ? SIMPLE_PANELS : DEV_PANELS;
		return (base as readonly string[]).filter(p => this.isPanelAllowed(p)) as string[];
	}

	public isPanelVisible(panel: string): boolean {
		return this.getVisiblePanels().includes(panel);
	}

	public enforceLockedChat(): string[] {
		if (this._mode === SIMPLE_MODE) {
			return (SIMPLE_PANELS as readonly string[]).filter(p => p === 'chat' && this.isPanelAllowed(p)) as string[];
		}
		return this.getVisiblePanels();
	}

	public getToggleLabel(): string {
		return this.isSimpleMode() ? 'Switch to Developer Mode' : 'Switch to Simple Mode';
	}
}

export function createPanelManager(mode: typeof SIMPLE_MODE | typeof DEVELOPER_MODE = SIMPLE_MODE): PanelManager {
	return new PanelManager(mode);
}

export function getSimpleModePanels(): string[] {
	return (SIMPLE_PANELS as readonly string[]).filter(p => !(NEVER_ALLOWED as readonly string[]).includes(p)) as string[];
}

export function getDeveloperModePanels(): string[] {
	return (DEV_PANELS as readonly string[]).filter(p => !(NEVER_ALLOWED as readonly string[]).includes(p)) as string[];
}

export function activate(context: vscode.ExtensionContext): void {
	const provider = new ModernityLanguageModelProvider(context);

	// Register vendor modernity through languageModelChatProviders
	const registration = vscode.lm.registerLanguageModelChatProvider('modernity', provider);
	context.subscriptions.push(registration);

	// Optional: log activation so users know provider is ready
	const output = vscode.window.createOutputChannel('Modernity', { log: true });
	output.info(`Modernity model provider activated (session ${ (provider as any)._sessionId ?? 'unknown' })`);

	context.subscriptions.push(output);

	// Dev toggle: Modernity Settings UI Button
	const config = vscode.workspace.getConfiguration('modernity');
	const initialMode = config.get<boolean>('developerMode') ? DEVELOPER_MODE : SIMPLE_MODE;
	const panelManager = new PanelManager(initialMode as typeof SIMPLE_MODE | typeof DEVELOPER_MODE);

	// Set context key for when clauses
	void vscode.commands.executeCommand('setContext', 'modernity.developerMode', panelManager.isDeveloperMode());

	const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
	statusBar.text = panelManager.getToggleLabel();
	statusBar.tooltip = 'Toggle between simple (locked chat) and developer mode';
	statusBar.command = 'modernity.toggleDeveloperMode';
	// Show status bar item as UI button in Modernity Settings area (status bar)
	statusBar.show();
	context.subscriptions.push(statusBar);

		const applyMode = async (): Promise<void> => {
		// Per latest instruction.md: should not bring back EVERYTHING on left panel (condensed) and terminal
		// Per user: need left panel but condensed (less features). Only terminal never.
		// How other CTAs update panels: layout.ts applyAuxiliaryBarMaximizedOverride hides EDITOR/SIDEBAR/PANEL, maximizes AUXILIARYBAR (simple locked chat)
		// Dev mode: restoreAuxiliaryBar + setPartHidden false for EDITOR (code viewer) + SIDEBAR (file tree) + show activityBar condensed
		try {
			if (panelManager.isSimpleMode()) {
				// Simple: locked chat only
				await vscode.commands.executeCommand('workbench.action.maximizeAuxiliaryBar');
				await vscode.commands.executeCommand('workbench.action.activityBar.hide'); // left panel hidden in simple
			} else {
				// Developer: restore - brings back editor (code viewer) and sidebar
				await vscode.commands.executeCommand('workbench.action.restoreAuxiliaryBar');
				await vscode.commands.executeCommand('workbench.view.explorer').then(() => {}, () => {}); // file tree panel
				// Bonus per latest instruction 18-23: debugging, search, source control
				await vscode.commands.executeCommand('workbench.view.search').then(() => {}, () => {});
				await vscode.commands.executeCommand('workbench.view.scm').then(() => {}, () => {});
				await vscode.commands.executeCommand('workbench.view.debug').then(() => {}, () => {});
				// Left panel condensed: show activityBar but only with file_tree, debug, search, scm (not everything like extensions)
				// Per latest: need left panel but condensed (less features)
				await vscode.commands.executeCommand('workbench.action.activityBar.show');
				await vscode.commands.executeCommand('workbench.view.explorer').then(() => {}, () => {}); // back to file tree as primary
				await vscode.commands.executeCommand('workbench.action.focusFirstEditorGroup').then(() => {}, () => {});
			}
			// Always enforce terminal never allowed per should-not
			await vscode.commands.executeCommand('workbench.action.terminal.hide');
			await vscode.commands.executeCommand('workbench.action.closePanel').then(() => {}, () => {});
		} catch (err) {
			output.warn(`Dev toggle applyMode failed: ${err}`);
		}
	};

	const updateUI = async (): Promise<void> => {
		void vscode.commands.executeCommand('setContext', 'modernity.developerMode', panelManager.isDeveloperMode());
		statusBar.text = panelManager.getToggleLabel();
		output.info(`Dev toggle: mode=${panelManager.getMode()} visible=${panelManager.getVisiblePanels().join(',')}`);
		await applyMode();
	};

	const toggleCommand = vscode.commands.registerCommand('modernity.toggleDeveloperMode', async () => {
		const newMode = panelManager.toggle();
		await config.update('developerMode', newMode === DEVELOPER_MODE, vscode.ConfigurationTarget.Global);
		await updateUI();
		void vscode.window.showInformationMessage(`Modernity: ${newMode === DEVELOPER_MODE ? 'Developer mode enabled - code viewer, file tree, debug, search, scm' : 'Simple mode - locked chat panel only'}. Terminal and left panel never allowed. Visible: ${panelManager.getVisiblePanels().join(', ')}`);
	});

	const enableCommand = vscode.commands.registerCommand('modernity.enableDeveloperMode', async () => {
		panelManager.setMode(DEVELOPER_MODE);
		await config.update('developerMode', true, vscode.ConfigurationTarget.Global);
		await updateUI();
	});

	const disableCommand = vscode.commands.registerCommand('modernity.disableDeveloperMode', async () => {
		panelManager.setMode(SIMPLE_MODE);
		await config.update('developerMode', false, vscode.ConfigurationTarget.Global);
		await updateUI();
	});

	context.subscriptions.push(toggleCommand, enableCommand, disableCommand);

	context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(e => {
		if (e.affectsConfiguration('modernity.developerMode')) {
			const isDev = vscode.workspace.getConfiguration('modernity').get<boolean>('developerMode') ?? false;
			panelManager.setMode(isDev ? DEVELOPER_MODE : SIMPLE_MODE);
			void updateUI();
		}
	}));

	void applyMode();

	// Expose the sandbox/tooling MCP server (compile / boot / create_sandbox / gametest /
	// rcon / ...) to the agent, and ensure the sandbox daemon it depends on is running.
	// Desktop (Node) only — the browser extension host has no child processes or sockets.
	const isNode = typeof process !== 'undefined' && !!process.versions?.node;
	if (isNode) {
		void import('./sandboxTools').then(sandbox => {
			context.subscriptions.push(sandbox.registerSandboxMcpProvider(context));
			stopSandbox = sandbox.stopSandboxDaemon;
			return sandbox.ensureSandboxDaemon(context);
		}).catch(err => output.warn(`Sandbox tooling unavailable: ${err?.message ?? err}`));
	}
}

export function deactivate(): void {
	stopSandbox?.();
}
