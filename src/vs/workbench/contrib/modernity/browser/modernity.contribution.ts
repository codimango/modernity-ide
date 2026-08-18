/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { ModernityDaemonStatusBarEntry, readModernityDaemonRuntime } from './modernityDaemonStatus.js';
import { ModernityInferenceStatusBarEntry } from './modernityInferenceStatus.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { URI } from '../../../../base/common/uri.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IEnvironmentService } from '../../../../platform/environment/common/environment.js';
import { resolveModernityApiBaseUrl } from '../../../../platform/product/common/modernityApi.js';
import { IProductService } from '../../../../platform/product/common/productService.js';

registerWorkbenchContribution2(ModernityDaemonStatusBarEntry.ID, ModernityDaemonStatusBarEntry, WorkbenchPhase.AfterRestored);
registerWorkbenchContribution2(ModernityInferenceStatusBarEntry.ID, ModernityInferenceStatusBarEntry, WorkbenchPhase.AfterRestored);

class OpenModernityDaemonStatusAction extends Action2 {
	constructor() {
		super({
			id: 'workbench.action.openModernityDaemonStatus',
			title: { value: 'Modernity: Open Daemon Status', original: 'Modernity: Open Daemon Status' },
		});
	}

	async run(accessor: ServicesAccessor): Promise<void> {
		const environmentService = accessor.get(IEnvironmentService);
		const fileService = accessor.get(IFileService);
		const openerService = accessor.get(IOpenerService);
		try {
			const data = await readModernityDaemonRuntime(
				fileService,
				environmentService.cacheHome.fsPath,
			);
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
		const productService = accessor.get(IProductService);
		try {
			const url = `${resolveModernityApiBaseUrl(productService.modernityApiBaseUrl)}/health`;
			await openerService.open(URI.parse(url), { openExternal: true });
		} catch {
			// ignore
		}
	}
}

registerAction2(OpenModernityDaemonStatusAction);
registerAction2(OpenModernityInferenceStatusAction);
