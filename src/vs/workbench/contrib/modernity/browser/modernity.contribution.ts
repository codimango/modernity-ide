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
