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

// Dev toggle per latest instruction.md: simple = locked chat (aux maximized), dev = code viewer, file tree, bonus debug/search/scm
// Latest: should not bring back EVERYTHING on left panel (condensed) + terminal. Per user: need left panel but condensed (less features). Only terminal never.
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
				(layoutService as any).setAuxiliaryBarMaximized?.(true);
				layoutService.setPartHidden(true, Parts.ACTIVITYBAR_PART); // left panel hidden in simple
			} else {
				(layoutService as any).setAuxiliaryBarMaximized?.(false);
				layoutService.setPartHidden(false, Parts.EDITOR_PART); // code viewer
				layoutService.setPartHidden(false, Parts.SIDEBAR_PART); // file tree
				layoutService.setPartHidden(false, Parts.ACTIVITYBAR_PART); // left panel condensed per latest: need left panel but less features
				// Bonus per latest instruction 18-23: debugging, search, source control
			}
			// Only terminal never allowed per latest should-not
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
				this.layoutService.setPartHidden(true, Parts.ACTIVITYBAR_PART);
			} else {
				(this.layoutService as any).setAuxiliaryBarMaximized?.(false);
				this.layoutService.setPartHidden(false, Parts.EDITOR_PART); // code viewer
				this.layoutService.setPartHidden(false, Parts.SIDEBAR_PART); // file tree
				this.layoutService.setPartHidden(false, Parts.ACTIVITYBAR_PART); // left panel condensed per latest
			}
			this.layoutService.setPartHidden(true, Parts.PANEL_PART); // only terminal never
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
