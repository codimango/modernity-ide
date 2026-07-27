/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity Contributors. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { IStatusbarEntry, IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { localize } from '../../../../nls.js';

export class ModernityInferenceStatusBarEntry extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.modernityInferenceStatus';

	private entry: IStatusbarEntryAccessor | undefined;
	private intervalId: ReturnType<typeof setInterval> | undefined;

	constructor(
		@IStatusbarService private readonly statusbarService: IStatusbarService,
	) {
		super();
		this.update();
		// Reduced polling to 10s to avoid contributing to 3-click race (was 2s causing many GET /models)
		this.intervalId = setInterval(() => this.update(), 10000);
		this._register({
			dispose: () => {
				if (this.intervalId) {
					clearInterval(this.intervalId);
				}
			}
		});
	}

	private async update(): Promise<void> {
		const gatewayUrl = 'http://127.0.0.1:8000';
		const modelsUrl = `${gatewayUrl}/api/inference/v1/models`;
		console.log(`[Modernity-Inference-Status] polling ${modelsUrl} time=${Date.now()}`);
		try {
			// Try to fetch models to verify gateway is up (dev) or prod gateway reachable
			const controller = new AbortController();
			const timeout = setTimeout(() => controller.abort(), 1500);
			const resp = await fetch(modelsUrl, { method: 'GET', signal: controller.signal } as any);
			clearTimeout(timeout);
			if (!resp.ok) {
				throw new Error(`status ${resp.status}`);
			}
			const json = await resp.json() as any;
			const modelCount = Array.isArray(json?.data) ? json.data.length : 0;
			const firstId = json?.data?.[0]?.id ?? 'muse-spark-1.1';

			const props: IStatusbarEntry = {
				name: localize('modernityInferenceStatus', "Modernity Inference"),
				text: `$(robot) Muse :8000 ${modelCount ? `(${firstId})` : ''}`,
				ariaLabel: localize('modernityInferenceRunning', "Inference gateway running on :8000 with {0} models", modelCount),
				tooltip: `Modernity Inference Gateway (Muse Spark)\n\nStatus: Running\nURL: ${gatewayUrl}\nModels endpoint: ${modelsUrl}\nModels: ${modelCount} (${(json?.data ?? []).map((m: any) => m.id).join(', ')})\n\nClick to open gateway health: ${gatewayUrl}/health\n\nThis is the other server at :8000 (vs Daemon dynamic port). Daemon = sandbox for Minecraft builds, Inference = LLM for Muse Spark.\nModernity-tooling server = full backend API (projects/auth/etc) which in dev reuses :8000 minimal gateway, in prod is separate service at modernity.dev.`,
				command: {
					id: 'workbench.action.openModernityInferenceStatus',
					title: 'Open Inference Gateway Status',
					tooltip: 'Open inference gateway status'
				} as any,
				kind: 'standard',
			};

			if (this.entry) {
				this.entry.update(props);
			} else {
				this.entry = this.statusbarService.addEntry(props, 'modernity.inferenceStatus', StatusbarAlignment.RIGHT, { location: { id: 'status.editor.mode', priority: 99 }, alignment: StatusbarAlignment.RIGHT });
			}
		} catch {
			const props: IStatusbarEntry = {
				name: localize('modernityInferenceStatus', "Modernity Inference"),
				text: `$(robot) Muse: stopped`,
				ariaLabel: localize('modernityInferenceStopped', "Inference gateway not running on :8000"),
				tooltip: `Modernity Inference Gateway (Muse Spark)\n\nStatus: Stopped\nExpected: http://127.0.0.1:8000/api/inference/v1/models\n\nRun: MODEL_API_KEY=... python -m uvicorn services.backend.api.minimal_inference_gateway:app --host 127.0.0.1 --port 8000\nOr via code.sh auto-start.\n\nDifference:\n- Daemon (status.editor.mode priority 100) = sandbox daemon, dynamic port from /tmp/modernity-workspace/daemon.json, handles Minecraft mod builds, file outbox, ingestion.\n- Inference :8000 = LLM gateway for Muse Spark, uses MODEL_API_KEY from .env or modernity.dev.secrets.\n- Modernity-tooling / full backend API = projects, auth, GitHub binding, trace ingestion, etc. In dev minimal gateway reuses :8000, in prod separate at modernity.dev / private gateway URL.`,
				kind: 'standard',
			};

			if (this.entry) {
				this.entry.update(props);
			} else {
				this.entry = this.statusbarService.addEntry(props, 'modernity.inferenceStatus', StatusbarAlignment.RIGHT, { location: { id: 'status.editor.mode', priority: 99 }, alignment: StatusbarAlignment.RIGHT });
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
