/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { ISessionTranscriptService } from '../../../platform/chat/common/sessionTranscriptService';
import { ILogService } from '../../../platform/log/common/logService';
import { IModelRequestTraceHandle, IModelRequestTraceService, IModelRequestTraceStart, ITraceInvocationContext } from '../../../platform/trace/common/trace';
import { generateUuid } from '../../../util/vs/base/common/uuid';

const MAX_TOOL_CONTEXTS = 4096;
const MAX_DUPLICATE_TERMINAL_DIAGNOSTICS = 20;

export class ModelRequestTraceService implements IModelRequestTraceService {
	declare readonly _serviceBrand: undefined;

	private readonly _toolContexts = new Map<string, ITraceInvocationContext>();
	private _duplicateTerminalDiagnostics = 0;

	constructor(
		@ISessionTranscriptService private readonly _transcriptService: ISessionTranscriptService,
		@ILogService private readonly _logService: ILogService,
	) { }

	begin(input: IModelRequestTraceStart): IModelRequestTraceHandle {
		const modelRequestId = generateUuid();
		const startedEventId = generateUuid();
		const baseContext: ITraceInvocationContext = {
			sessionId: input.sessionId,
			turnId: input.turnId,
			modelRequestId,
			projectId: input.projectId,
			checkoutId: input.checkoutId,
			machineId: input.machineId,
		};
		this._transcriptService.logModelRequestStarted(
			input.sessionId,
			input.provider,
			input.model,
			baseContext,
			startedEventId,
			input.parentEventId,
		);

		let terminal = false;
		const finish = (callback: () => void): void => {
			if (terminal) {
				this._reportDuplicateTerminal(modelRequestId);
				return;
			}
			terminal = true;
			callback();
		};

		return {
			modelRequestId,
			startedEventId,
			bindToolCall: nativeToolCallId => {
				const toolCallId = nativeToolCallId.split('__vscode-')[0];
				const context = { ...baseContext, toolCallId };
				this._rememberToolContext(input.sessionId, toolCallId, context);
				return context;
			},
			complete: result => finish(() => this._transcriptService.logModelResponseCompleted(
				input.sessionId,
				result.durationMs,
				baseContext,
				result.usage,
			)),
			fail: result => finish(() => this._transcriptService.logModelResponseFailed(
				input.sessionId,
				result.code,
				result.retryable,
				false,
				result.durationMs,
				baseContext,
			)),
			cancel: result => finish(() => this._transcriptService.logModelResponseFailed(
				input.sessionId,
				'CANCELLED',
				false,
				true,
				result.durationMs,
				baseContext,
			)),
		};
	}

	getToolCallContext(sessionId: string, nativeToolCallId: string): ITraceInvocationContext | undefined {
		return this._toolContexts.get(this._toolKey(sessionId, nativeToolCallId));
	}

	private _rememberToolContext(sessionId: string, toolCallId: string, context: ITraceInvocationContext): void {
		const key = this._toolKey(sessionId, toolCallId);
		this._toolContexts.delete(key);
		this._toolContexts.set(key, context);
		while (this._toolContexts.size > MAX_TOOL_CONTEXTS) {
			const oldest = this._toolContexts.keys().next().value;
			if (oldest === undefined) {
				break;
			}
			this._toolContexts.delete(oldest);
		}
	}

	private _toolKey(sessionId: string, nativeToolCallId: string): string {
		return `${sessionId}:${nativeToolCallId.split('__vscode-')[0]}`;
	}

	private _reportDuplicateTerminal(modelRequestId: string): void {
		if (this._duplicateTerminalDiagnostics >= MAX_DUPLICATE_TERMINAL_DIAGNOSTICS) {
			return;
		}
		this._duplicateTerminalDiagnostics++;
		this._logService.debug(`[ModelRequestTrace] Ignored duplicate terminal result for ${modelRequestId}`);
	}
}
