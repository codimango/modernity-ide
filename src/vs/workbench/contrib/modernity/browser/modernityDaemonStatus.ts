/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity Contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { IStatusbarEntry, IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';

export class ModernityDaemonStatusBarEntry extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.modernityDaemonStatus';

	private entry: IStatusbarEntryAccessor | undefined;
	private intervalId: ReturnType<typeof setInterval> | undefined;

	constructor(
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@IFileService private readonly fileService: IFileService,
	) {
		super();
		this.update();
		this.intervalId = setInterval(() => this.update(), 2000);
		this._register({
			dispose: () => {
				if (this.intervalId) {
					clearInterval(this.intervalId);
				}
			}
		});
	}

	private async update(): Promise<void> {
		const runtimePath = '/tmp/modernity-workspace/daemon.json';
		const uri = URI.file(runtimePath);

		try {
			const content = await this.fileService.readFile(uri);
			const data = JSON.parse(content.value.toString());
			const port = data.port;

			const props: IStatusbarEntry = {
				name: localize('modernityDaemonStatus', "Modernity Daemon"),
				text: `$(server-process) Daemon :${port}`,
				ariaLabel: localize('modernityDaemonRunning', "Sandbox daemon running on port {0}", port),
				tooltip: `Modernity Sandbox Daemon\n\nStatus: Running\nPort: ${port}\nWorkspace: ${data.workspace_root || '/tmp/modernity-workspace'}\nRuntime: ${runtimePath}\n\nClick to open visual status page at http://127.0.0.1:${port}/`,
				command: {
					id: 'workbench.action.openModernityDaemonStatus',
					title: 'Open Daemon Status',
					tooltip: 'Open daemon visual status'
				} as any,
				kind: 'standard',
			};

			if (this.entry) {
				this.entry.update(props);
			} else {
				this.entry = this.statusbarService.addEntry(props, 'modernity.daemonStatus', StatusbarAlignment.RIGHT, { location: { id: 'status.editor.mode', priority: 100 }, alignment: StatusbarAlignment.RIGHT });
			}
		} catch {
			const props: IStatusbarEntry = {
				name: localize('modernityDaemonStatus', "Modernity Daemon"),
				text: `$(server-environment) Daemon: stopped`,
				ariaLabel: localize('modernityDaemonStopped', "Sandbox daemon not running"),
				tooltip: `Modernity Sandbox Daemon\n\nStatus: Stopped\nExpected file: ${runtimePath}\n\nRun: ./scripts/code.sh to auto-start per T280149056`,
				kind: 'standard',
			};

			if (this.entry) {
				this.entry.update(props);
			} else {
				this.entry = this.statusbarService.addEntry(props, 'modernity.daemonStatus', StatusbarAlignment.RIGHT, { location: { id: 'status.editor.mode', priority: 100 }, alignment: StatusbarAlignment.RIGHT });
			}
		}
	}

	override dispose(): void {
		super.dispose();
		this.entry?.dispose();
		this.entry = undefined;
		if (this.intervalId) {
			clearInterval(this.intervalId);
		}
	}
}
