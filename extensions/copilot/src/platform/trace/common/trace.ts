/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { TranscriptEntry } from '../../chat/common/sessionTranscriptService';
import { createServiceIdentifier } from '../../../util/common/services';
import { URI } from '../../../util/vs/base/common/uri';

export type TraceJsonValue = string | number | boolean | null | TraceJsonObject | readonly TraceJsonValue[];
export interface TraceJsonObject { readonly [key: string]: TraceJsonValue }

export interface ITraceInvocationContext {
	readonly sessionId: string;
	readonly turnId: string;
	readonly modelRequestId?: string;
	readonly toolCallId?: string;
	readonly projectId?: string;
	readonly checkoutId?: string;
	readonly machineId?: string;
}

export interface CanonicalTraceEventV1 {
	readonly schema_version: 1;
	readonly event_id: string;
	readonly occurred_at: string;
	readonly source_sequence: number;
	readonly source: 'ide';
	readonly event_type: 'session.started' | 'session.ended' | 'user.message' | 'assistant.message' | 'model.request.started' | 'model.response.completed' | 'model.response.failed' | 'mcp.tool.started' | 'mcp.tool.completed' | 'mcp.tool.failed';
	readonly session_id: string;
	readonly execution_session_id: null;
	readonly turn_id: string | null;
	readonly model_request_id: string | null;
	readonly tool_call_id: string | null;
	readonly sandbox_id: null;
	readonly project_id: string | null;
	readonly checkout_id: string | null;
	readonly machine_id: string | null;
	readonly parent_event_id: string | null;
	readonly payload: TraceJsonObject;
}

export const ITraceEventOutbox = createServiceIdentifier<ITraceEventOutbox>('ITraceEventOutbox');

export interface ITraceEventOutbox {
	readonly _serviceBrand: undefined;
	enqueue(event: CanonicalTraceEventV1): Promise<'enqueued' | 'duplicate'>;
}

export interface IRecoverableTraceEventOutbox extends ITraceEventOutbox {
	recoverTranscript(sessionId: string, transcriptUri: URI): Promise<void>;
}

export class NullTraceEventOutbox implements ITraceEventOutbox {
	declare readonly _serviceBrand: undefined;

	async enqueue(): Promise<'duplicate'> {
		return 'duplicate';
	}
}

export interface IModelRequestTraceStart {
	readonly sessionId: string;
	readonly turnId: string;
	readonly provider: 'copilot' | 'openai_compatible';
	readonly model: string;
	readonly projectId?: string;
	readonly checkoutId?: string;
	readonly machineId?: string;
	readonly parentEventId?: string;
}

export interface IModelRequestTraceHandle {
	readonly modelRequestId: string;
	readonly startedEventId: string;
	bindToolCall(nativeToolCallId: string): ITraceInvocationContext;
	complete(result: { readonly usage?: { readonly inputTokens?: number; readonly outputTokens?: number }; readonly durationMs: number }): void;
	fail(result: { readonly code: string; readonly retryable: boolean; readonly durationMs: number }): void;
	cancel(result: { readonly durationMs: number }): void;
}

export const IModelRequestTraceService = createServiceIdentifier<IModelRequestTraceService>('IModelRequestTraceService');

export interface IModelRequestTraceService {
	readonly _serviceBrand: undefined;
	begin(input: IModelRequestTraceStart): IModelRequestTraceHandle;
	getToolCallContext(sessionId: string, nativeToolCallId: string): ITraceInvocationContext | undefined;
}

export class NullModelRequestTraceService implements IModelRequestTraceService {
	declare readonly _serviceBrand: undefined;

	begin(input: IModelRequestTraceStart): IModelRequestTraceHandle {
		const context: ITraceInvocationContext = { sessionId: input.sessionId, turnId: input.turnId };
		return {
			modelRequestId: '',
			startedEventId: '',
			bindToolCall: nativeToolCallId => ({ ...context, toolCallId: nativeToolCallId }),
			complete() { },
			fail() { },
			cancel() { },
		};
	}

	getToolCallContext(): undefined {
		return undefined;
	}
}

export function mapTranscriptEntryToTraceEvent(sessionId: string, entry: TranscriptEntry, sourceSequence: number): CanonicalTraceEventV1 | undefined {
	let eventType: CanonicalTraceEventV1['event_type'];
	let payload: TraceJsonObject;
	let context: ITraceInvocationContext | undefined;

	switch (entry.type) {
		case 'session.start':
			eventType = 'session.started';
			payload = {
				transcript_version: entry.data.version,
				producer: bounded(entry.data.producer),
				copilot_version: bounded(entry.data.copilotVersion),
				vscode_version: bounded(entry.data.vscodeVersion),
				has_cwd: entry.data.context?.cwd !== undefined,
				...(entry.data.context?.cwd !== undefined ? textField('cwd', entry.data.context.cwd, 4_096) : {}),
			};
			break;
		case 'session.end':
			eventType = 'session.ended';
			payload = { status: entry.data.status };
			break;
		case 'user.message':
			eventType = 'user.message';
			payload = {
				content_length: entry.data.content.length,
				attachment_count: entry.data.attachments?.length ?? 0,
				...textField('content', entry.data.content, 32_000),
				...(entry.data.attachments?.length ? serializedField('attachments', entry.data.attachments, 8_000) : {}),
			};
			break;
		case 'assistant.message':
			eventType = 'assistant.message';
			context = entry.data.traceContext;
			payload = {
				content_length: entry.data.content.length,
				tool_request_count: entry.data.toolRequests.length,
				has_reasoning: entry.data.reasoningText !== undefined,
				...textField('content', entry.data.content, 20_000),
				...(entry.data.reasoningText !== undefined ? textField('reasoning', entry.data.reasoningText, 8_000) : {}),
				...(entry.data.toolRequests.length ? serializedField('tool_requests', entry.data.toolRequests, 8_000) : {}),
			};
			break;
		case 'model.request.started':
			eventType = 'model.request.started';
			context = entry.data.traceContext;
			payload = {
				provider: entry.data.provider,
				model: bounded(entry.data.model),
			};
			break;
		case 'model.response.completed':
			eventType = 'model.response.completed';
			context = entry.data.traceContext;
			payload = {
				duration_ms: nonNegative(entry.data.durationMs),
				...(entry.data.inputTokens !== undefined ? { input_tokens: nonNegative(entry.data.inputTokens) } : {}),
				...(entry.data.outputTokens !== undefined ? { output_tokens: nonNegative(entry.data.outputTokens) } : {}),
			};
			break;
		case 'model.response.failed':
			eventType = 'model.response.failed';
			context = entry.data.traceContext;
			payload = {
				code: bounded(entry.data.code, 128),
				retryable: entry.data.retryable,
				cancelled: entry.data.cancelled,
				duration_ms: nonNegative(entry.data.durationMs),
			};
			break;
		case 'tool.execution_start':
			eventType = 'mcp.tool.started';
			context = entry.data.traceContext;
			payload = {
				tool_name: bounded(entry.data.toolName, 512),
				...serializedField('arguments', entry.data.arguments, 24_000),
			};
			break;
		case 'tool.execution_complete':
			eventType = entry.data.success ? 'mcp.tool.completed' : 'mcp.tool.failed';
			context = entry.data.traceContext;
			payload = {
				success: entry.data.success,
				result_length: entry.data.result?.content.length ?? 0,
				...(entry.data.result !== undefined ? textField('result_content', entry.data.result.content, 24_000) : {}),
			};
			break;
		case 'assistant.turn_start':
		case 'assistant.turn_end':
			return undefined;
	}

	return {
		schema_version: 1,
		event_id: entry.id,
		occurred_at: normalizeTimestamp(entry.timestamp),
		source_sequence: sourceSequence,
		source: 'ide',
		event_type: eventType,
		session_id: sessionId,
		execution_session_id: null,
		turn_id: context?.turnId ?? null,
		model_request_id: context?.modelRequestId ?? null,
		tool_call_id: context?.toolCallId ?? null,
		sandbox_id: null,
		project_id: context?.projectId ?? null,
		checkout_id: context?.checkoutId ?? null,
		machine_id: context?.machineId ?? null,
		parent_event_id: entry.parentId,
		payload,
	};
}

function normalizeTimestamp(value: string): string {
	const timestamp = new Date(value);
	return Number.isNaN(timestamp.getTime()) ? new Date().toISOString() : timestamp.toISOString();
}

function bounded(value: string, limit = 256): string {
	return value.length <= limit ? value : value.slice(0, limit);
}

function textField(name: string, value: string, maxBytes: number): TraceJsonObject {
	const encoded = new TextEncoder().encode(value);
	if (encoded.byteLength <= maxBytes) {
		return { [name]: value, [`${name}_truncated`]: false };
	}
	let low = 0;
	let high = value.length;
	while (low < high) {
		const middle = Math.ceil((low + high) / 2);
		if (new TextEncoder().encode(value.slice(0, middle)).byteLength <= maxBytes) {
			low = middle;
		} else {
			high = middle - 1;
		}
	}
	return { [name]: value.slice(0, low), [`${name}_truncated`]: true };
}

function serializedField(name: string, value: unknown, maxBytes: number): TraceJsonObject {
	let serialized: string;
	try {
		serialized = JSON.stringify(value) ?? 'null';
	} catch {
		serialized = String(value);
	}
	return textField(name, serialized, maxBytes);
}

function nonNegative(value: number): number {
	return Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}
