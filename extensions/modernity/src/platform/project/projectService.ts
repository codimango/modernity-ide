/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: modernityProject platform service — owns state, refresh, cancellation, disposables,
 *       injected coordinators. View-free.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { Checkout, Project, RepositorySummary, Page, CursorParams } from './models';
import { CloudApiError } from './errors';
import { DaemonError } from './errors';
import { ModernityCloudClient } from './cloudClient';
import { ModernityDaemonClient } from './daemonClient';
import type { IGitAdapter } from './gitContract';

export interface ProjectServiceDeps {
	readonly cloudClient: ModernityCloudClient;
	readonly daemonClient: ModernityDaemonClient;
	readonly gitAdapter: IGitAdapter;
	/** Optional filesystem probe for checkout path validation. */
	readonly fileExists?: (uri: vscode.Uri) => Promise<boolean>;
}

export type FlowCoordinator = {
	/** Called when a project needs checkout flow coordination. */
	coordinateCheckout?: (project: Project, token: vscode.CancellationToken) => Promise<void>;
};

export interface ProjectServiceState {
	readonly projects: ReadonlyMap<string, Project>;
	readonly lastUpdatedAt: number | null;
	readonly cloudOffline: boolean;
	readonly daemonAvailable: boolean;
	readonly lastError?: string;
}

class SimpleDisposableStore {
	private readonly items = new Set<vscode.Disposable>();
	add(d: vscode.Disposable): void { this.items.add(d); }
	dispose(): void {
		for (const d of this.items) {
			try { d.dispose(); } catch {}
		}
		this.items.clear();
	}
}

export class ModernityProjectService implements vscode.Disposable {
	private readonly deps: ProjectServiceDeps;
	private readonly disposables = new SimpleDisposableStore();
	private readonly onDidChangeProjectsEmitter = new vscode.EventEmitter<ProjectServiceState>();
	private readonly onDidChangeDaemonEmitter = new vscode.EventEmitter<boolean>();

	readonly onDidChangeProjects: vscode.Event<ProjectServiceState> = this.onDidChangeProjectsEmitter.event;
	readonly onDidChangeDaemonAvailability: vscode.Event<boolean> = this.onDidChangeDaemonEmitter.event;

	private projects = new Map<string, Project>();
	private lastUpdatedAt: number | null = null;
	private cloudOffline = false;
	private daemonAvailable = true;
	private lastError?: string;

	// refresh coalescing
	private refreshInFlight: Promise<void> | null = null;
	private refreshQueued = false;
	private refreshCts: vscode.CancellationTokenSource | null = null;

	// flow coordinators
	private checkoutCoordinator?: FlowCoordinator;

	private readonly repositories = new Map<string, RepositorySummary | null>();
	private readonly checkouts = new Map<string, Checkout[]>();

	constructor(deps: ProjectServiceDeps, coordinator?: FlowCoordinator) {
		this.deps = deps;
		this.checkoutCoordinator = coordinator;
		this.disposables.add(this.onDidChangeProjectsEmitter);
		this.disposables.add(this.onDidChangeDaemonEmitter);

		// dispose on window shutdown — task says dispose immediately on window shutdown
		// In VS Code extension host, we rely on extension deactivation; we also listen to cancellation of a global token if provided
		// Here we register a disposable that cancels any in-flight refresh
		this.disposables.add({ dispose: () => { this.cancelRefresh(); } } as vscode.Disposable);
	}

	/** For tests — inject/replace coordinators after construction. */
	setFlowCoordinator(coordinator: FlowCoordinator): void {
		this.checkoutCoordinator = coordinator;
	}

	getState(): ProjectServiceState {
		return {
			projects: new Map(this.projects),
			lastUpdatedAt: this.lastUpdatedAt,
			cloudOffline: this.cloudOffline,
			daemonAvailable: this.daemonAvailable,
			lastError: this.lastError,
		};
	}

	getProjects(): Project[] {
		return [...this.projects.values()];
	}

	getProject(id: string): Project | undefined {
		return this.projects.get(id);
	}

	getRepository(projectId: string): RepositorySummary | null | undefined {
		return this.repositories.get(projectId);
	}

	getCheckouts(projectId: string): Checkout[] | undefined {
		return this.checkouts.get(projectId);
	}

	private emit(): void {
		this.onDidChangeProjectsEmitter.fire(this.getState());
		this.onDidChangeDaemonEmitter.fire(this.daemonAvailable);
	}

	/** Cancel any in-flight refresh — used on window shutdown and explicit cancel. */
	cancelRefresh(): void {
		this.refreshCts?.cancel();
		this.refreshCts?.dispose();
		this.refreshCts = null;
	}

	/** Coalesce refreshes — if one is in flight, queue one more and reuse same promise. */
	async refresh(token?: vscode.CancellationToken): Promise<void> {
		if (this.refreshInFlight) {
			this.refreshQueued = true;
			return this.refreshInFlight;
		}

		const cts = new vscode.CancellationTokenSource();
		this.refreshCts = cts;
		if (token) {
			token.onCancellationRequested(() => { cts.cancel(); });
		}

		const run = async (): Promise<void> => {
			do {
				this.refreshQueued = false;
				try {
					await this.refreshInternal(cts.token);
				} catch (e: any) {
					if (e instanceof vscode.CancellationError) {
						// preserve last-known state
						this.lastError = 'cancelled';
						this.emit();
						break;
					}
					throw e;
				}
			} while (this.refreshQueued);
		};

		this.refreshInFlight = run()
			.finally(() => {
				this.refreshInFlight = null;
				cts.dispose();
				if (this.refreshCts === cts) { this.refreshCts = null; }
			});

		return this.refreshInFlight;
	}

	private async refreshInternal(token: vscode.CancellationToken): Promise<void> {
		if (token.isCancellationRequested) { throw new vscode.CancellationError(); }

		// Step 1: check daemon health separately — map unavailability distinct from cloud offline
		try {
			await this.deps.daemonClient.health(token);
			if (!this.daemonAvailable) {
				this.daemonAvailable = true;
			}
		} catch (e: any) {
			if (e instanceof DaemonError) {
				// missing/stale/401/connection => typed daemon error, preserve cloud cache
				this.daemonAvailable = false;
				this.lastError = `daemon ${e.kind}: ${e.message}`;
			} else if (e instanceof vscode.CancellationError) {
				throw e;
			} else {
				this.daemonAvailable = false;
				this.lastError = `daemon unavailable: ${e?.message ?? e}`;
			}
			// Do NOT discard cloud cached state — emit daemon change but keep projects
			this.emit();
			// Continue to cloud refresh even if daemon down — offline vs daemon separation
		}

		// Step 2: cloud projects — preserve last-known on offline/503/network
		try {
			const params: CursorParams = { limit: 50 };
			const all: Project[] = [];
			let cursor: string | undefined = undefined;
			do {
				if (token.isCancellationRequested) { throw new vscode.CancellationError(); }
				const page: Page<Project> = await this.deps.cloudClient.listProjects({ ...params, cursor }, token);
				all.push(...page.items);
				cursor = page.next_cursor ?? undefined;
			} while (cursor);

			// Successfully fetched cloud — update
			this.projects = new Map(all.map(p=>[p.id, p]));
			this.lastUpdatedAt = Date.now();
			this.cloudOffline = false;
			this.lastError = undefined;

			// Optionally refresh repositories and checkouts for each project (lightweight)
			// Do not block main refresh if one repo fails
			for (const p of all) {
				if (token.isCancellationRequested) { break; }
				try {
					const repoRes = await this.deps.cloudClient.getRepository(p.id, token);
					this.repositories.set(p.id, repoRes.repository);
				} catch { /* preserve last known */ }
				try {
					const ckRes = await this.deps.cloudClient.listCheckouts(p.id, { limit: 50 }, token);
					this.checkouts.set(p.id, [...ckRes.items]);
				} catch { /* preserve */ }
				// coordinator hook — injected flow (e.g., auto checkout creation)
				if (this.checkoutCoordinator?.coordinateCheckout) {
					try { await this.checkoutCoordinator.coordinateCheckout(p, token); } catch { /* swallow */ }
				}
			}

			this.emit();
		} catch (e: any) {
			if (e instanceof vscode.CancellationError) { throw e; }
			if (e instanceof CloudApiError && e.kind === 'offline') {
				this.cloudOffline = true;
				this.lastError = `cloud offline: ${e.envelope.message}`;
				// preserve lastKnown
				this.emit();
				return;
			}
			// Other cloud errors — keep cached, surface lastError but not offline
			this.lastError = e?.message ?? String(e);
			this.emit();
			// Do not throw to avoid breaking coalescing loop — but preserve error for UI
		}
	}

	/** Called on extension deactivate / window shutdown — immediate disposal. */
	dispose(): void {
		this.cancelRefresh();
		this.disposables.dispose();
	}

	/** For testing — simulate daemon restart clearing cached discovery. */
	handleDaemonRestart(): void {
		this.deps.daemonClient.discoveryReset();
		this.daemonAvailable = false;
		this.emit();
	}
}

// VS Code service registration helper
export const IModernityProjectService = 'modernityProject';

export function registerModernityProjectService(
	context: vscode.ExtensionContext,
	deps: ProjectServiceDeps,
	coordinator?: FlowCoordinator
): ModernityProjectService {
	const service = new ModernityProjectService(deps, coordinator);
	context.subscriptions.push(service);
	// Also expose via context if needed
	return service;
}
