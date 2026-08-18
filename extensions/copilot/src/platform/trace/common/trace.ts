/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { TranscriptEntry } from '../../chat/common/sessionTranscriptService';
import { createServiceIdentifier } from '../../../util/common/services';
import { URI } from '../../../util/vs/base/common/uri';

export type TraceJsonValue = string | number | boolean | null | TraceJsonObject | readonly TraceJsonValue[];
export interface TraceJsonObject { readonly [key: string]: TraceJsonValue }

const MAX_VISIBLE_CONTENT_BYTES = 48 * 1024;
const MAX_SINGLE_VISIBLE_VALUE_BYTES = MAX_VISIBLE_CONTENT_BYTES - 512;
const MAX_ASSISTANT_VISIBLE_VALUE_BYTES = 23 * 1024;
const TRACE_TEXT_ENCODER = new TextEncoder();
const TRACE_SENSITIVE_KEY = /^(?:authorization|api[_-]?key|(?:access|auth|bearer|refresh)?[_-]?token|password|secret|client[_-]?secret)$/i;

export interface ITraceMappingOptions {
	/** Include user-visible messages and tool I/O. Hidden reasoning is always omitted. */
	readonly includeVisibleContent?: boolean;
}

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

export function mapTranscriptEntryToTraceEvent(sessionId: string, entry: TranscriptEntry, sourceSequence: number, options?: ITraceMappingOptions): CanonicalTraceEventV1 | undefined {
	let eventType: CanonicalTraceEventV1['event_type'];
	let payload: TraceJsonObject;
	let context: ITraceInvocationContext | undefined;
	const includeVisibleContent = options?.includeVisibleContent === true;

	switch (entry.type) {
		case 'session.start':
			eventType = 'session.started';
			payload = {
				transcript_version: entry.data.version,
				producer: bounded(entry.data.producer),
				copilot_version: bounded(entry.data.copilotVersion),
				vscode_version: bounded(entry.data.vscodeVersion),
				has_cwd: entry.data.context?.cwd !== undefined,
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
				...(includeVisibleContent ? visibleTraceFields({ content: boundedVisibleText(entry.data.content, MAX_SINGLE_VISIBLE_VALUE_BYTES) }) : {}),
			};
			break;
		case 'assistant.message':
			eventType = 'assistant.message';
			context = entry.data.traceContext;
			payload = {
				content_length: entry.data.content.length,
				tool_request_count: entry.data.toolRequests.length,
				has_reasoning: entry.data.reasoningText !== undefined,
				...(includeVisibleContent ? visibleTraceFields({
					content: boundedVisibleText(entry.data.content, MAX_ASSISTANT_VISIBLE_VALUE_BYTES),
					tool_requests: safeTraceValue(entry.data.toolRequests, MAX_ASSISTANT_VISIBLE_VALUE_BYTES),
				}) : {}),
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
				...(includeVisibleContent ? visibleTraceFields({ arguments: safeTraceValue(entry.data.arguments, MAX_SINGLE_VISIBLE_VALUE_BYTES) }) : {}),
			};
			break;
		case 'tool.execution_complete':
			eventType = entry.data.success ? 'mcp.tool.completed' : 'mcp.tool.failed';
			context = entry.data.traceContext;
			payload = {
				success: entry.data.success,
				result_length: entry.data.result?.content.length ?? 0,
				...(includeVisibleContent && entry.data.result?.content !== undefined
					? visibleTraceFields({ result_content: boundedVisibleText(entry.data.result.content, MAX_SINGLE_VISIBLE_VALUE_BYTES) })
					: {}),
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

function nonNegative(value: number): number {
	return Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

function safeTraceValue(value: unknown, maxSerializedBytes: number): TraceJsonValue {
	try {
		const encoded = JSON.stringify(value, (key, item) => {
			if (key && TRACE_SENSITIVE_KEY.test(key)) {
				return '[REDACTED]';
			}
			return typeof item === 'string' ? redactSensitiveText(item) : item;
		});
		if (encoded === undefined) {
			return null;
		}
		const encodedBytes = utf8ByteLength(encoded);
		if (encodedBytes > maxSerializedBytes) {
			return { truncated: true, encoded_length_bytes: encodedBytes };
		}
		return JSON.parse(encoded) as TraceJsonValue;
	} catch {
		return { serialization_failed: true };
	}
}

function visibleTraceFields(fields: TraceJsonObject): TraceJsonObject {
	const encodedBytes = jsonByteLength(fields);
	if (encodedBytes <= MAX_VISIBLE_CONTENT_BYTES) {
		return fields;
	}
	return { content_truncated: true, encoded_length_bytes: encodedBytes };
}

function boundedVisibleText(value: string, maxSerializedBytes: number): string {
	const redacted = redactSensitiveText(value);
	if (jsonByteLength(redacted) <= maxSerializedBytes) {
		return redacted;
	}

	const marker = '\n[Modernity trace truncated]';
	const availableInnerBytes = Math.max(0, maxSerializedBytes - 2);
	let usedBytes = jsonStringInnerByteLength(marker);
	if (usedBytes > availableInnerBytes) {
		return '';
	}
	const chunks: string[] = [];
	for (const character of redacted) {
		const characterBytes = jsonStringInnerByteLength(character);
		if (usedBytes + characterBytes > availableInnerBytes) {
			break;
		}
		chunks.push(character);
		usedBytes += characterBytes;
	}
	return chunks.join('') + marker;
}

function jsonStringInnerByteLength(value: string): number {
	return utf8ByteLength(JSON.stringify(value)) - 2;
}

function jsonByteLength(value: TraceJsonValue | TraceJsonObject): number {
	return utf8ByteLength(JSON.stringify(value));
}

function utf8ByteLength(value: string): number {
	return TRACE_TEXT_ENCODER.encode(value).byteLength;
}

function redactSensitiveText(value: string): string {
	return value
		.replace(/(authorization\s*:\s*bearer\s+)[a-z0-9._~+\/-]{12,}/gi, '$1[REDACTED]')
		.replace(/\b(?:github_pat_|ghp_|gho_|ghu_|ghs_|ghr_)[a-z0-9_]{12,}\b/gi, '[REDACTED_GITHUB_TOKEN]')
		.replace(/((?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*["']?)[^\s,"'}]{4,}/gi, '$1[REDACTED]');
}
