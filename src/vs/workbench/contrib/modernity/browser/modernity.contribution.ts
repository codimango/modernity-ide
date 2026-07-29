/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity Contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { ModernityDaemonStatusBarEntry } from './modernityDaemonStatus.js';
import { ModernityInferenceStatusBarEntry } from './modernityInferenceStatus.js';
import { registerAction2 } from '../../../../platform/actions/common/actions.js';
import { Action2 } from '../../../../platform/actions/common/actions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { URI } from '../../../../base/common/uri.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IWorkbenchLayoutService, Parts } from '../../../services/layout/browser/layoutService.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IViewDescriptorService, ViewContainerLocation } from '../../../common/views.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';

registerWorkbenchContribution2(ModernityDaemonStatusBarEntry.ID, ModernityDaemonStatusBarEntry, WorkbenchPhase.AfterRestored);
registerWorkbenchContribution2(ModernityInferenceStatusBarEntry.ID, ModernityInferenceStatusBarEntry, WorkbenchPhase.AfterRestored);

// Dev toggle per latest instruction.md: simple = locked chat (aux maximized), dev = code viewer, file tree, bonus debug/search/scm
// Latest: should not bring back EVERYTHING on left panel (condensed) + terminal. Per user: need left panel but condensed (less features). Only terminal never.
// How other CTAs update panels: layout.ts applyAuxiliaryBarMaximizedOverride hides EDITOR/SIDEBAR/PANEL, maximizes AUXILIARYBAR (simple locked chat)
// Dev mode: restore via setPartHidden false for EDITOR (code viewer) + SIDEBAR (file tree) + ACTIVITYBAR (left panel condensed). Only PANEL (terminal) never.
// Condensed left nav: only file_tree, search, scm, debug — hide extensions, testing, accounts-extra, etc. Enforced via pinnedViewlets storage.

import { Disposable } from '../../../../base/common/lifecycle.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';

// Condensed left panel per instruction: file_tree, debug, search, source_control only (not everything)
// Maps to VS Code view container IDs - these get icon buttons in left nav when dev toggle flipped
const CONDENSED_ICON_IDS = [
	'workbench.view.explorer', // file_tree
	'workbench.view.search',   // search
	'workbench.view.scm',      // source_control
	'workbench.view.debug',    // debug
] as const;

class ModernityDevModeListener extends Disposable implements IWorkbenchContribution {

	public constructor(
		@IWorkbenchLayoutService private readonly layoutService: IWorkbenchLayoutService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IViewDescriptorService private readonly viewDescriptorService: IViewDescriptorService,
		@ICommandService private readonly commandService: ICommandService,
		@INotificationService private readonly notificationService: INotificationService
	) {
		super();
		// Apply initial mode
		this.applyMode();

		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration('modernity.developerMode')) {
				this.applyMode();
			}
		}));
	}

	private applyMode(): void {
		const isDev = this.configurationService.getValue<boolean>('modernity.developerMode') ?? false;
		try {
			if (!isDev) {
				(this.layoutService as any).setAuxiliaryBarMaximized?.(true);
				this.layoutService.setPartHidden(true, Parts.ACTIVITYBAR_PART);
				// Restore simple: hide activity bar via location + visible config (PR6 default)
				try {
					this.configurationService.updateValue('workbench.activityBar.location', 'hidden');
					this.configurationService.updateValue('workbench.activityBar.visible', false);
				} catch { /* ignore */ }
			} else {
				(this.layoutService as any).setAuxiliaryBarMaximized?.(false);
				// Critical: activity bar hidden via workbench.activityBar.location=hidden + visible=false from PR6
				// ActivityBarPosition enum = default, top, bottom, hidden — must be 'default' to show, not 'side'
				try {
					this.configurationService.updateValue('workbench.activityBar.location', 'default');
					this.configurationService.updateValue('workbench.activityBar.visible', true);
				} catch { /* ignore */ }
				this.layoutService.setPartHidden(false, Parts.EDITOR_PART); // code viewer
				this.layoutService.setPartHidden(false, Parts.SIDEBAR_PART); // file tree
				this.layoutService.setPartHidden(false, Parts.ACTIVITYBAR_PART); // left panel condensed per latest - icon buttons for file_tree, search, scm, debug
				this.layoutService.setPartHidden(false, Parts.STATUSBAR_PART); // restore status bar for dev
				this.applyCondensedActivityBar();
				// Re-apply after a tick to fight layout override that hides again - ensures icon buttons visible
				setTimeout(() => {
					try {
						this.layoutService.setPartHidden(false, Parts.ACTIVITYBAR_PART);
						this.layoutService.setPartHidden(false, Parts.SIDEBAR_PART);
						this.layoutService.setPartHidden(false, Parts.EDITOR_PART);
						this.layoutService.setPartHidden(false, Parts.STATUSBAR_PART);
						this.configurationService.updateValue('workbench.activityBar.location', 'default');
						this.configurationService.updateValue('workbench.activityBar.visible', true);
						if (!this.layoutService.isVisible(Parts.ACTIVITYBAR_PART)) {
							this.commandService.executeCommand('workbench.action.toggleActivityBarVisibility');
						}
						const count = CONDENSED_ICON_IDS.length;
						const visible = this.layoutService.isVisible(Parts.ACTIVITYBAR_PART);
						const sidebarAfter = this.viewDescriptorService.getViewContainersByLocation(ViewContainerLocation.Sidebar).map(c => c.id).join(',');
						this.notificationService.info('Modernity dev mode: condensed left nav count=' + count + ' visible=' + visible + ' sidebar=' + sidebarAfter);
					} catch { /* ignore */ }
				}, 150);
					this.notificationService.info('Modernity dev mode enabled - showing condensed left nav: file_tree, search, source_control, debug + code_viewer');
				}
				this.layoutService.setPartHidden(true, Parts.PANEL_PART); // only terminal never
			} catch {
				// ignore
			}
		}

	private applyCondensedActivityBar(): void {
		// Fix for empty bar: previous storage overwrite caused race where PaneCompositeBar
		// re-pins all containers on registration (if not in cached), then save overwrites condensed.
		// New approach: don't touch storage at all for pinned, just MOVE view containers.
		// - Keep condensed in Sidebar => they naturally get icon buttons (explorer, search, scm, debug)
		// - Move everything else from Sidebar to Panel (panel hidden as terminal never) => they disappear from left nav
		// This restores icon buttons for panels you wanted without empty bar.
		try {
			const sidebarContainers = this.viewDescriptorService.getViewContainersByLocation(ViewContainerLocation.Sidebar);
			const panelContainers = this.viewDescriptorService.getViewContainersByLocation(ViewContainerLocation.Panel);
			const auxContainers = this.viewDescriptorService.getViewContainersByLocation(ViewContainerLocation.AuxiliaryBar);

			// 1) Ensure file_tree, search, source_control, debug are in Sidebar for icon buttons
			for (const id of CONDENSED_ICON_IDS) {
				const container =
					sidebarContainers.find(c => c.id === id) ||
					panelContainers.find(c => c.id === id) ||
					auxContainers.find(c => c.id === id) ||
					this.viewDescriptorService.getViewContainerById(id);
				if (container) {
					const loc = this.viewDescriptorService.getViewContainerLocation(container);
					if (loc !== ViewContainerLocation.Sidebar) {
						try {
							this.viewDescriptorService.moveViewContainerToLocation(container, ViewContainerLocation.Sidebar, undefined, 'modernity-dev-toggle');
						} catch { /* ignore */ }
					}
				}
			}

			// 2) Hide everything else from left nav by moving non-condensed away from Sidebar to Panel (hidden)
			// This is what gives condensed left nav, not everything. Prevents 15 icons screenshot.
			for (const container of sidebarContainers.slice()) {
				if (!(CONDENSED_ICON_IDS as readonly string[]).includes(container.id)) {
					try {
						this.viewDescriptorService.moveViewContainerToLocation(container, ViewContainerLocation.Panel, undefined, 'modernity-dev-toggle-condense');
					} catch { /* ignore */ }
				}
			}
		} catch {
			// ignore
		}
	}
}

registerWorkbenchContribution2('modernity.devModeListener', ModernityDevModeListener, WorkbenchPhase.AfterRestored);

class OpenModernityDaemonStatusAction extends Action2 {
	constructor() {
		super({
			id: 'workbench.action.openModernityDaemonStatus',
			title: { value: 'Modernity: Open Daemon Status', original: 'Modernity: Open Daemon Status' },
		});
	}

	async run(accessor: ServicesAccessor): Promise<void> {
		const fileService = accessor.get(IFileService);
		const openerService = accessor.get(IOpenerService);
		try {
			const uri = URI.file('/tmp/modernity-workspace/daemon.json');
			const content = await fileService.readFile(uri);
			const data = JSON.parse(content.value.toString());
			const port = data.port;
			const url = `http://127.0.0.1:${port}/`;
			await openerService.open(URI.parse(url), { openExternal: true });
		} catch {
			// ignore
		}
	}
}

class OpenModernityInferenceStatusAction extends Action2 {
	constructor() {
		super({
			id: 'workbench.action.openModernityInferenceStatus',
			title: { value: 'Modernity: Open Inference Gateway Status', original: 'Modernity: Open Inference Gateway Status' },
		});
	}

	async run(accessor: ServicesAccessor): Promise<void> {
		const openerService = accessor.get(IOpenerService);
		try {
			const url = 'http://127.0.0.1:8000/health';
			await openerService.open(URI.parse(url), { openExternal: true });
		} catch {
			// ignore
		}
	}
}

registerAction2(OpenModernityDaemonStatusAction);
registerAction2(OpenModernityInferenceStatusAction);
