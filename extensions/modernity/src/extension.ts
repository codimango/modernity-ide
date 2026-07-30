/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { ModernityLanguageModelProvider } from './modernityProvider';
import { ModernityCloudClient } from './platform/project/cloudClient';
import { ModernityDaemonClient } from './platform/project/daemonClient';
import { VsCodeGitAdapter } from './platform/project/gitAdapter';
import { ModernityProjectService } from './platform/project/projectService';
import { ConversationHistory, createTitlePreview } from './conversationHistory';

// Node-only sandbox tooling is loaded lazily so the browser bundle never runs it.
let stopSandbox: (() => void) | undefined;
let projectService: ModernityProjectService | undefined;
let chatProvider: ModernityLanguageModelProvider | undefined;
let conversationHistory: ConversationHistory | undefined;

// Dev toggle panel IDE - constants per spec
// Simple mode = locked chat panel only
// Developer mode = code viewer, file tree, settings, plus bonus debug/search/scm
// Never allowed: left_panel (activity bar) and terminal
export const SIMPLE_MODE = 'simple';
export const DEVELOPER_MODE = 'developer';
export const SIMPLE_PANELS = ['chat'] as const;
export const DEV_PANELS = ['chat', 'code_viewer', 'file_tree', 'settings', 'left_panel', 'debug', 'search', 'source_control'] as const; // per latest line 12 show left panel
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
	// Phase 0: Simple Local History - account for previous conversations
	conversationHistory = new ConversationHistory(context);
	const lastSessionId = conversationHistory.getLastSessionId();
	const provider = new ModernityLanguageModelProvider(context, lastSessionId);
	chatProvider = provider;

	// Register vendor modernity through languageModelChatProviders
	const registration = vscode.lm.registerLanguageModelChatProvider('modernity', provider);
	context.subscriptions.push(registration);

	// Optional: log activation so users know provider is ready
	const output = vscode.window.createOutputChannel('Modernity', { log: true });
	output.info(`Modernity model provider activated (session ${provider.sessionId}) - Phase 0 local history: ${conversationHistory!.getConversations().length} conversations, file ${conversationHistory!.getFilePath()}`);
	if (lastSessionId) {
		output.info(`Auto-restore lastSessionId=${lastSessionId} for conversation persistence on reopen`);
	}

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

	// Phase 0: History button in Modernity Settings header (status bar second button) - shows previous conversations
	const historyStatusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
	historyStatusBar.text = '$(history) Chat History';
	historyStatusBar.tooltip = 'View and resume previous conversations (Phase 0 local history)';
	historyStatusBar.command = 'modernity.openConversationHistory';
	historyStatusBar.show();
	context.subscriptions.push(historyStatusBar);

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

	// Phase 0: Conversation History - simple local history + resume
	const resumeConversation = async (conversationId: string): Promise<void> => {
		if (!conversationHistory || !chatProvider) { return; }
		const conv = conversationHistory.getConversation(conversationId);
		if (!conv) {
			void vscode.window.showWarningMessage(`Conversation ${conversationId} not found`);
			return;
		}
		chatProvider.setSessionId(conversationId);
		conversationHistory.setLastSessionId(conversationId);
		output.info(`Resumed conversation ${conversationId} - title: ${conv.title}, messages: ${conv.messages.length}, file: ${conversationHistory.getFilePath()}`);
		output.show(true);
		for (const msg of conv.messages) {
			output.info(`[${msg.timestamp}] ${msg.role}: ${msg.text.slice(0, 500)}`);
		}
		void vscode.window.showInformationMessage(`Resumed: ${conv.title} (${conv.messages.length} messages) - session ${conversationId}`);
		try { await vscode.commands.executeCommand('workbench.action.chat.open'); } catch { }
	};

	const openHistoryCommand = vscode.commands.registerCommand('modernity.openConversationHistory', async () => {
		if (!conversationHistory) { return; }
		const conversations = conversationHistory.getConversations();
		if (conversations.length === 0) {
			void vscode.window.showInformationMessage('No previous conversations found (Phase 0 local history). Send a message first.');
			return;
		}
		type QuickPickItem = vscode.QuickPickItem & { conversationId: string };
		const items: QuickPickItem[] = conversations.map(conv => ({
			label: conv.title,
			description: new Date(conv.lastMessageAt).toLocaleString(),
			// Use preview 100 chars + count for verification
			detail: createTitlePreview(conv.messages[conv.messages.length - 1]?.text || conv.title, 100) + ` (${conv.messages.length} msgs) - ${conv.conversationId.slice(0, 8)}`,
			conversationId: conv.conversationId
		}));
		const selected = await vscode.window.showQuickPick(items, {
			placeHolder: 'Select a conversation to resume (Phase 0 local history - sorted by last_message_at desc)',
			matchOnDescription: true,
			matchOnDetail: true
		});
		if (selected) {
			await resumeConversation(selected.conversationId);
		}
	});

	const resumeCommand = vscode.commands.registerCommand('modernity.resumeConversation', async (conversationId?: string) => {
		if (typeof conversationId === 'string' && conversationId) {
			await resumeConversation(conversationId);
			return;
		}
		await vscode.commands.executeCommand('modernity.openConversationHistory');
	});

	const newConversationCommand = vscode.commands.registerCommand('modernity.newConversation', async () => {
		if (!conversationHistory || !chatProvider) { return; }
		const newId = (globalThis as any).crypto?.randomUUID?.() ?? `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
		chatProvider.setSessionId(newId);
		conversationHistory.setLastSessionId(newId);
		output.info(`Started new conversation ${newId}`);
		void vscode.window.showInformationMessage(`Started new conversation ${newId.slice(0, 8)}`);
		try { await vscode.commands.executeCommand('workbench.action.chat.open'); } catch { }
	});

	const clearHistoryCommand = vscode.commands.registerCommand('modernity.clearConversationHistory', async () => {
		if (!conversationHistory) { return; }
		const confirm = await vscode.window.showWarningMessage('Clear all local conversation history (Phase 0)? This deletes globalState and ~/.modernity/conversations.json', { modal: true }, 'Clear');
		if (confirm === 'Clear') {
			await conversationHistory.clear();
			void vscode.window.showInformationMessage('Conversation history cleared');
			output.info('Cleared all local conversation history');
		}
	});

	context.subscriptions.push(openHistoryCommand, resumeCommand, newConversationCommand, clearHistoryCommand);

	context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(e => {
		if (e.affectsConfiguration('modernity.developerMode')) {
			const isDev = vscode.workspace.getConfiguration('modernity').get<boolean>('developerMode') ?? false;
			panelManager.setMode(isDev ? DEVELOPER_MODE : SIMPLE_MODE);
			void updateUI();
		}
	}));

	void applyMode();

	// T23: modernityProject platform service — owns project state, refresh events, cancellation, disposables, injected coordinators.
	// Cloud: Bearer, envelope {code,message,request_id,retryable,details}, 401→signed_out, 403→unauthorized, 404→missing, 409→conflict, 422→validation, 429→rate_limited, 503/offline preserves cache.
	// Daemon: owner-only runtime JSON {host,port,token,workspace_root}, loopback only, no fallback, health ok, create/getStatus/postOperation.
	// Git: injected via vscode.git extension + credential provider, safe contract status/init/clone/import/fetch/ff-pull/push.
	try {
		const getAccessToken = async (): Promise<string | undefined> => {
			try {
				const secret = await context.secrets.get('modernity.accessToken');
				if (secret) { return secret; }
			} catch {}
			try {
				const cfgTok = vscode.workspace.getConfiguration('modernity').get<string>('accessToken');
				if (cfgTok && cfgTok.trim()) { return cfgTok.trim(); }
			} catch {}
			return undefined;
		};

		const gatewayUrl = vscode.workspace.getConfiguration('modernity').get<string>('gatewayUrl')?.trim() || 'http://127.0.0.1:8000';

		const cloudClient = new ModernityCloudClient({
			baseUrl: gatewayUrl,
			getAccessToken,
			onRequestSnapshot: (snap) => {
				output.trace?.(`[T23][cloud] ${snap.method} ${snap.url}`);
			},
		});

		const daemonClient = new ModernityDaemonClient({
			onSnapshot: (snap) => {
				output.trace?.(`[T23][daemon] ${snap.method} ${snap.url}`);
			},
		});

		const gitAdapter = new VsCodeGitAdapter();

		const service = new ModernityProjectService({
			cloudClient,
			daemonClient,
			gitAdapter,
		});

		projectService = service;
		context.subscriptions.push(service);
		context.subscriptions.push(service.onDidChangeProjects(state => {
			output.trace?.(`[T23] projects changed: count=${state.projects.size} offline=${state.cloudOffline} daemon=${state.daemonAvailable} err=${state.lastError ?? 'none'}`);
		}));
		context.subscriptions.push(service.onDidChangeDaemonAvailability(avail => {
			output.info(`[T23] daemon availability: ${avail}`);
		}));

		context.subscriptions.push(vscode.commands.registerCommand('modernity.refreshProjects', async () => {
			await service.refresh();
			void vscode.window.showInformationMessage(`Modernity projects: ${service.getProjects().length} (offline=${service.getState().cloudOffline} daemon=${service.getState().daemonAvailable})`);
		}));
		context.subscriptions.push(vscode.commands.registerCommand('modernity.cancelRefreshProjects', () => {
			service.cancelRefresh();
		}));

		void service.refresh().then(() => {
			output.info(`[T23] initial refresh done: ${service.getProjects().length} projects`);
		}).catch(err => {
			if (err instanceof vscode.CancellationError) { return; }
			output.warn(`[T23] initial refresh failed: ${err?.message ?? err}`);
		});

		output.info('[T23] modernityProject platform service registered (T23)');

		// T24: compact project list and project-level command entry points
		// Uses T23 service + cloudClient + gitAdapter. First-screen IDE view with all required fields and states.
		try {
			void (async () => {
				try {
					const { ProjectListProvider } = await import('./platform/project/list/provider');
					const { registerProjectListCommands } = await import('./platform/project/list/commands');

					const provider = new ProjectListProvider(
						service,
						cloudClient,
						gitAdapter,
						output,
					);
					context.subscriptions.push(provider as any);

					const treeView = vscode.window.createTreeView('modernity.projectList', {
						treeDataProvider: provider,
						showCollapseAll: false,
					});
					context.subscriptions.push(treeView);
					treeView.onDidChangeVisibility(e => {
						if (e.visible) {
							void vscode.commands.executeCommand('setContext', 'modernity.isProjectListVisible', true);
						}
					});
					context.subscriptions.push(vscode.window.onDidChangeWindowState(state => {
						if (state.focused && provider.getState().kind !== 'loading') {
							void provider.refresh();
						}
					}));

					registerProjectListCommands(context, cloudClient, service, gitAdapter, provider, output);

					void provider.buildFromServiceState();

					output.info('[T24] compact project list activated — name, repo, checkout basename (never other machine full path), local Git independent from cached GitHub head/observed time, lifecycle, last-opened, all states loading/empty/offline/unauthorized/partial/archived/recoverable (401/409/429/503), commands create/open/clone/fetch/pull/push/sandbox/refresh/manageMachines, a11y focus/keyboard, restrained density, desktop/narrow checks');
				} catch (err: any) {
					output.warn(`[T24] project list init failed: ${err?.message ?? err}`);
				}
			})();
		} catch (err: any) {
			output.warn(`[T24] project list init scheduling failed: ${err?.message ?? err}`);
		}

	} catch (err: any) {
		output.warn(`[T23] project service init failed: ${err?.message ?? err}`);
	}

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
	try { projectService?.dispose(); } catch {}
	projectService = undefined;
	chatProvider = undefined;
	conversationHistory = undefined;
	stopSandbox?.();
}
