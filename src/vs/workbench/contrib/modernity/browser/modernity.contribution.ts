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

registerWorkbenchContribution2(ModernityDaemonStatusBarEntry.ID, ModernityDaemonStatusBarEntry, WorkbenchPhase.AfterRestored);
registerWorkbenchContribution2(ModernityInferenceStatusBarEntry.ID, ModernityInferenceStatusBarEntry, WorkbenchPhase.AfterRestored);

// Dev toggle - how other CTAs update panels: use layoutService.setPartHidden and setAuxiliaryBarMaximized
// Per latest instruction.md: simple = locked chat (auxiliaryBar maximized), dev = code viewer, file tree, bonus debug/search/scm, NEVER left_panel/terminal
class ModernityDevToggleContribution extends Action2 {
	static readonly ID = 'modernity.devToggle.applyMode';

	public constructor() {
		super({
			id: ModernityDevToggleContribution.ID,
			title: { value: 'Modernity: Apply Dev Toggle Mode', original: 'Modernity: Apply Dev Toggle Mode' },
			f1: false
		});
	}

	public override async run(accessor: ServicesAccessor): Promise<void> {
		const layoutService = accessor.get(IWorkbenchLayoutService);
		const configService = accessor.get(IConfigurationService);
		const isDev = configService.getValue<boolean>('modernity.developerMode') ?? false;

		try {
			if (!isDev) {
				// Simple mode: locked chat only - maximize auxiliary bar (chat covers entire screen)
				// This hides editor (code viewer), sidebar (file tree), panel (terminal)
				(layoutService as any).setAuxiliaryBarMaximized?.(true);
			} else {
				// Developer mode: bring back code viewer (editor), file tree (explorer), plus bonus
				(layoutService as any).setAuxiliaryBarMaximized?.(false);
				layoutService.setPartHidden(false, Parts.EDITOR_PART); // code viewer panel
				layoutService.setPartHidden(false, Parts.SIDEBAR_PART); // file tree panel (explorer)
				// Bonus per instruction.md 18-23: debugging, search, source control - enable via focusing views
				// These are accessible via View actions even with activityBar hidden
				// We ensure sidebar is visible so file tree / search / scm / debug can be shown
				// Note: keep activityBar (left_panel) and panel (terminal) hidden per NEVER_ALLOWED
			}
			// Always enforce NEVER_ALLOWED: left_panel (activity bar) and terminal (panel)
			layoutService.setPartHidden(true, Parts.ACTIVITYBAR_PART); // left panel never
			layoutService.setPartHidden(true, Parts.PANEL_PART); // terminal never (panel contains terminal)
		} catch {
			// ignore layout errors
		}
	}
}

// Register a workbench contribution that listens to config changes and applies mode
import { Disposable } from '../../../../base/common/lifecycle.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';

class ModernityDevModeListener extends Disposable implements IWorkbenchContribution {

	public constructor(
		@IWorkbenchLayoutService private readonly layoutService: IWorkbenchLayoutService,
		@IConfigurationService private readonly configurationService: IConfigurationService
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
			} else {
				(this.layoutService as any).setAuxiliaryBarMaximized?.(false);
				this.layoutService.setPartHidden(false, Parts.EDITOR_PART);
				this.layoutService.setPartHidden(false, Parts.SIDEBAR_PART);
				// Bonus panels are enabled as views in sidebar - keep sidebar visible
			}
			this.layoutService.setPartHidden(true, Parts.ACTIVITYBAR_PART);
			this.layoutService.setPartHidden(true, Parts.PANEL_PART);
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
