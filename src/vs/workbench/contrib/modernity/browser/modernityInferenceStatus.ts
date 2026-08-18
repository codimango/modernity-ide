/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { mainWindow } from '../../../../base/browser/window.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { resolveModernityApiBaseUrl } from '../../../../platform/product/common/modernityApi.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { IStatusbarEntry, IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';

interface InferenceModel {
	readonly id?: string;
}

interface ModelsResponse {
	readonly data?: readonly InferenceModel[];
}

export class ModernityInferenceStatusBarEntry extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.modernityInferenceStatus';

	private entry: IStatusbarEntryAccessor | undefined;
	private intervalId: number | undefined;
	private readonly gatewayUrl: string;

	constructor(
		@IStatusbarService private readonly statusbarService: IStatusbarService,
		@IProductService productService: IProductService,
	) {
		super();
		this.gatewayUrl = resolveModernityApiBaseUrl(productService.modernityApiBaseUrl);
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
		const gatewayUrl = this.gatewayUrl;
		const modelsUrl = `${gatewayUrl}/api/inference/v1/models`;
		try {
			// Try to fetch models to verify gateway is up (dev) or prod gateway reachable
			const controller = new AbortController();
			const timeout = setTimeout(() => controller.abort(), 1500);
			const resp = await fetch(modelsUrl, { method: 'GET', signal: controller.signal });
			clearTimeout(timeout);
			if (!resp.ok) {
				throw new Error(`status ${resp.status}`);
			}
			const json = await resp.json() as ModelsResponse;
			const models: readonly InferenceModel[] = Array.isArray(json.data) ? json.data : [];
			const modelCount = models.length;
			const firstId = models[0]?.id ?? 'muse-spark-1.1';

			const props: IStatusbarEntry = {
				name: localize('modernityInferenceStatus', "Modernity Inference"),
				text: `$(robot) Muse ${modelCount ? `(${firstId})` : ''}`,
				ariaLabel: localize('modernityInferenceRunning', "Inference gateway at {0} is running with {1} models", gatewayUrl, modelCount),
				tooltip: `Modernity Inference Gateway (Muse Spark)\n\nStatus: Running\nURL: ${gatewayUrl}\nModels endpoint: ${modelsUrl}\nModels: ${modelCount} (${models.map(model => model.id).join(', ')})\n\nClick to open gateway health: ${gatewayUrl}/health`,
				command: 'workbench.action.openModernityInferenceStatus',
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
				ariaLabel: localize('modernityInferenceStopped', "Inference gateway at {0} is not reachable", gatewayUrl),
				tooltip: `Modernity Inference Gateway (Muse Spark)\n\nStatus: Stopped\nExpected: ${modelsUrl}\n\nSet MODERNITY_API_BASE_URL to select a different Modernity API endpoint.`,
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
			mainWindow.clearInterval(this.intervalId);
		}
	}
}
