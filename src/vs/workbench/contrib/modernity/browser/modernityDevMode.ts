/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity Contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { IViewDescriptorService, ViewContainerLocation } from '../../../common/views.js';
import { IWorkbenchLayoutService, Parts } from '../../../services/layout/browser/layoutService.js';
import { IPaneCompositePartService } from '../../../services/panecomposite/browser/panecomposite.js';

export const MODERNITY_DEVELOPER_MODE_SETTING = 'modernity.developerMode';

export const MODERNITY_DEVELOPER_MODE_CONTEXT_KEY = new RawContextKey<boolean>('modernityDeveloperMode', false);

/**
 * Built-in view containers unlocked in developer mode. They are hosted in the
 * auxiliary bar next to the chat because the primary side bar is never
 * restored: the left panel exposes custom extensions which can break the
 * product (T278837441).
 */
const DEVELOPER_MODE_VIEW_CONTAINERS = [
	'workbench.view.explorer', // file tree panel
	'workbench.view.search',
	'workbench.view.scm',
	'workbench.view.debug',
] as const;

/**
 * Swaps the workbench between the simple mode (locked chat panel) and the
 * developer mode (code viewer, file tree, debugging, search, source control).
 *
 * Enforced in both modes, per T278837441:
 * - the primary side bar and activity bar are never restored, so custom
 *   extensions cannot surface and break the product;
 * - the panel part is never shown, so the terminal stays unreachable.
 */
export class ModernityDevModeContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.modernityDevMode';

	private readonly developerModeContextKey: IContextKey<boolean>;

	constructor(
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IWorkbenchLayoutService private readonly layoutService: IWorkbenchLayoutService,
		@IViewDescriptorService private readonly viewDescriptorService: IViewDescriptorService,
		@IPaneCompositePartService private readonly paneCompositePartService: IPaneCompositePartService,
		@IContextKeyService contextKeyService: IContextKeyService,
	) {
		super();

		this.developerModeContextKey = MODERNITY_DEVELOPER_MODE_CONTEXT_KEY.bindTo(contextKeyService);

		this.applyMode();

		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(MODERNITY_DEVELOPER_MODE_SETTING)) {
				this.applyMode();
			}
		}));

		// The left panel and the terminal stay locked regardless of mode, so
		// re-hide those parts whenever something tries to surface them.
		this._register(this.layoutService.onDidChangePartVisibility(e => {
			if (!e.visible) {
				return;
			}
			if (e.partId === Parts.PANEL_PART || e.partId === Parts.SIDEBAR_PART || e.partId === Parts.ACTIVITYBAR_PART) {
				this.layoutService.setPartHidden(true, e.partId as Parts);
			}
		}));
	}

	private applyMode(): void {
		const developerMode = this.configurationService.getValue<boolean>(MODERNITY_DEVELOPER_MODE_SETTING) ?? false;
		this.developerModeContextKey.set(developerMode);
		if (developerMode) {
			this.applyDeveloperMode();
		} else {
			this.applySimpleMode();
		}
	}

	/**
	 * Simple mode: the locked chat panel covers the entire screen.
	 */
	private applySimpleMode(): void {
		// Park the developer view containers back at their default home. They
		// stay unreachable because the side bar is never shown.
		this.moveDeveloperViewContainers(ViewContainerLocation.Sidebar);

		this.layoutService.setPartHidden(true, Parts.ACTIVITYBAR_PART);
		this.layoutService.setPartHidden(true, Parts.SIDEBAR_PART);
		this.layoutService.setPartHidden(true, Parts.PANEL_PART);
		this.layoutService.setAuxiliaryBarMaximized(true);
	}

	/**
	 * Developer mode: code viewer plus file tree, debugging, search and source
	 * control next to the chat. The left panel and the terminal stay locked.
	 */
	private applyDeveloperMode(): void {
		this.layoutService.setPartHidden(true, Parts.ACTIVITYBAR_PART);
		this.layoutService.setPartHidden(true, Parts.SIDEBAR_PART);
		this.layoutService.setPartHidden(true, Parts.PANEL_PART);

		this.layoutService.setAuxiliaryBarMaximized(false);
		this.layoutService.setPartHidden(false, Parts.EDITOR_PART);

		this.moveDeveloperViewContainers(ViewContainerLocation.AuxiliaryBar);
		this.layoutService.setPartHidden(false, Parts.AUXILIARYBAR_PART);
		void this.paneCompositePartService.openPaneComposite(DEVELOPER_MODE_VIEW_CONTAINERS[0], ViewContainerLocation.AuxiliaryBar, false);
	}

	private moveDeveloperViewContainers(location: ViewContainerLocation): void {
		for (const id of DEVELOPER_MODE_VIEW_CONTAINERS) {
			const container = this.viewDescriptorService.getViewContainerById(id);
			if (container && this.viewDescriptorService.getViewContainerLocation(container) !== location) {
				this.viewDescriptorService.moveViewContainerToLocation(container, location, undefined, MODERNITY_DEVELOPER_MODE_SETTING);
			}
		}
	}
}
