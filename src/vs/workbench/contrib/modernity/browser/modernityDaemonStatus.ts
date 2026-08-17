/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { mainWindow } from '../../../../base/browser/window.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IEnvironmentService } from '../../../../platform/environment/common/environment.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { modernityDaemonRuntimeFileCandidates } from '../../../../platform/modernityDaemon/common/modernityDaemon.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { IStatusbarEntry, IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';

export interface IModernityDaemonRuntime {
	readonly port: number;
	readonly workspace_root?: string;
	readonly runtimePath: string;
}

export async function readModernityDaemonRuntime(
	fileService: IFileService,
	userDataPath: string,
): Promise<IModernityDaemonRuntime> {
	for (const runtimePath of modernityDaemonRuntimeFileCandidates(userDataPath)) {
		try {
			const content = await fileService.readFile(URI.file(runtimePath));
			const runtime = JSON.parse(content.value.toString()) as Omit<IModernityDaemonRuntime, 'runtimePath'>;
			if (Number.isInteger(runtime.port) && runtime.port > 0 && runtime.port <= 65_535) {
				return { ...runtime, runtimePath };
			}
		} catch {
			// Continue to the next supported discovery file.
		}
	}
	throw new Error('Modernity daemon runtime file was not found.');
}

export class ModernityDaemonStatusBarEntry extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.modernityDaemonStatus';

	private entry: IStatusbarEntryAccessor | undefined;
	private intervalId: number | undefined;

	constructor(
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@IFileService private readonly fileService: IFileService,
		@IEnvironmentService private readonly environmentService: IEnvironmentService,
	) {
		super();
		this.update();
		this.intervalId = mainWindow.setInterval(() => this.update(), 2000);
		this._register({
			dispose: () => {
				if (this.intervalId) {
					mainWindow.clearInterval(this.intervalId);
				}
			}
		});
	}

	private async update(): Promise<void> {
		try {
			const data = await readModernityDaemonRuntime(
				this.fileService,
				this.environmentService.cacheHome.fsPath,
			);
			const port = data.port;

			const props: IStatusbarEntry = {
				name: localize('modernityDaemonStatus', "Modernity Daemon"),
				text: `$(server-process) ${localize('modernityDaemonRunningText', "Daemon :{0}", port)}`,
				ariaLabel: localize('modernityDaemonRunning', "Sandbox daemon running on port {0}", port),
				tooltip: localize(
					'modernityDaemonRunningTooltip',
					"Modernity Sandbox Daemon\n\nStatus: Running\nPort: {0}\nWorkspace: {1}\nRuntime: {2}\n\nClick to open visual status page at http://127.0.0.1:{0}/",
					port,
					data.workspace_root || localize('modernityDaemonUnknownWorkspace', "Unknown"),
					data.runtimePath,
				),
				command: {
					id: 'workbench.action.openModernityDaemonStatus',
					title: localize('modernityDaemonOpenStatus', "Open Daemon Status"),
					tooltip: localize('modernityDaemonOpenStatusTooltip', "Open daemon visual status"),
				},
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
				text: `$(server-environment) ${localize('modernityDaemonStoppedText', "Daemon: Stopped")}`,
				ariaLabel: localize('modernityDaemonStopped', "Sandbox daemon not running"),
				tooltip: localize('modernityDaemonStoppedTooltip', "Modernity Sandbox Daemon\n\nStatus: Stopped"),
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
			mainWindow.clearInterval(this.intervalId);
		}
	}
}
