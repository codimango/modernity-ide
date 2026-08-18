/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { describe, expect, it } from 'vitest';
import { NullSessionTranscriptService } from '../../../chat/common/sessionTranscriptService';
import type { ILogTarget, ILogger } from '../../../log/common/logService';
import { mapTranscriptEntryToTraceEvent, type ITraceInvocationContext } from '../trace';
import { ModelRequestTraceService } from '../../../../extension/trace/vscode-node/modelRequestTraceService';

const SESSION_ID = '095baf79-0e1b-4c71-b698-67e8167291ce';
const MODEL_REQUEST_ID = '20000000-0000-4000-8000-000000000001';

class RecordingTranscriptService extends NullSessionTranscriptService {
	readonly entries: { type: string; values: readonly (string | number | boolean | undefined)[] }[] = [];

	override logModelRequestStarted(sessionId: string, provider: 'copilot' | 'openai_compatible', model: string, traceContext: ITraceInvocationContext, entryId: string, parentEventId?: string): void {
		this.entries.push({ type: 'started', values: [sessionId, provider, model, traceContext.modelRequestId, entryId, parentEventId] });
	}

	override logModelResponseCompleted(sessionId: string, durationMs: number, traceContext: ITraceInvocationContext, usage?: { readonly inputTokens?: number; readonly outputTokens?: number }): void {
		this.entries.push({ type: 'completed', values: [sessionId, durationMs, traceContext.modelRequestId, usage?.inputTokens, usage?.outputTokens] });
	}

	override logModelResponseFailed(sessionId: string, code: string, retryable: boolean, cancelled: boolean, durationMs: number, traceContext: ITraceInvocationContext): void {
		this.entries.push({ type: 'failed', values: [sessionId, code, retryable, cancelled, durationMs, traceContext.modelRequestId] });
	}
}

class TestLogService {
	declare readonly _serviceBrand: undefined;
	readonly diagnostics: string[] = [];
	debug(message: string) { this.diagnostics.push(message); }
	info() { }
	warn() { }
	error() { }
	trace() { }
	show() { }
	createSubLogger(): ILogger { return this; }
	withExtraTarget(_target: ILogTarget): ILogger { return this; }
}

describe('Modernity canonical IDE tracing', () => {
	it('maps transcript entries with stable IDs and hides visible content by default', () => {
		const userEvent = mapTranscriptEntryToTraceEvent(SESSION_ID, {
			type: 'user.message',
			id: '10000000-0000-4000-8000-000000000001',
			timestamp: '2026-07-27T12:00:00.000Z',
			parentId: null,
			data: { content: 'secret prompt body', attachments: [{ secret: true }] },
		}, 1);
		const toolEvent = mapTranscriptEntryToTraceEvent(SESSION_ID, {
			type: 'tool.execution_start',
			id: '10000000-0000-4000-8000-000000000002',
			timestamp: '2026-07-27T12:00:01.000Z',
			parentId: userEvent!.event_id,
			data: {
				toolCallId: 'native-call',
				toolName: 'read_file',
				arguments: { apiKey: 'do-not-export' },
				traceContext: { sessionId: SESSION_ID, turnId: '0', modelRequestId: MODEL_REQUEST_ID, toolCallId: 'native-call' },
			},
		}, 2);

		expect({
			userEvent,
			toolEvent,
			serializedContainsContent: JSON.stringify([userEvent, toolEvent]).includes('secret prompt body'),
			serializedContainsArgument: JSON.stringify([userEvent, toolEvent]).includes('do-not-export'),
		}).toEqual({
			userEvent: {
				schema_version: 1,
				event_id: '10000000-0000-4000-8000-000000000001',
				occurred_at: '2026-07-27T12:00:00.000Z',
				source_sequence: 1,
				source: 'ide',
				event_type: 'user.message',
				session_id: SESSION_ID,
				execution_session_id: null,
				turn_id: null,
				model_request_id: null,
				tool_call_id: null,
				sandbox_id: null,
				project_id: null,
				checkout_id: null,
				machine_id: null,
				parent_event_id: null,
				payload: {
					content_length: 18,
					attachment_count: 1,
				},
			},
			toolEvent: {
				schema_version: 1,
				event_id: '10000000-0000-4000-8000-000000000002',
				occurred_at: '2026-07-27T12:00:01.000Z',
				source_sequence: 2,
				source: 'ide',
				event_type: 'mcp.tool.started',
				session_id: SESSION_ID,
				execution_session_id: null,
				turn_id: '0',
				model_request_id: MODEL_REQUEST_ID,
				tool_call_id: 'native-call',
				sandbox_id: null,
				project_id: null,
				checkout_id: null,
				machine_id: null,
				parent_event_id: '10000000-0000-4000-8000-000000000001',
				payload: {
					tool_name: 'read_file',
				},
			},
			serializedContainsContent: false,
			serializedContainsArgument: false,
		});
	});

	it('redacts sensitive keys from opted-in tool arguments', () => {
		const event = mapTranscriptEntryToTraceEvent(SESSION_ID, {
			type: 'tool.execution_start',
			id: '10000000-0000-4000-8000-000000000004',
			timestamp: '2026-07-27T12:00:03.000Z',
			parentId: null,
			data: {
				toolCallId: 'call-sensitive',
				toolName: 'write_file',
				arguments: { apiKey: 'do-not-export', path: 'Mana.java' },
			},
		}, 4, { includeVisibleContent: true });

		expect({
			arguments: event?.payload.arguments,
			containsSecret: JSON.stringify(event).includes('do-not-export'),
		}).toEqual({
			arguments: { apiKey: '[REDACTED]', path: 'Mana.java' },
			containsSecret: false,
		});
	});

	it('includes opted-in visible content without exporting hidden reasoning', () => {
		const event = mapTranscriptEntryToTraceEvent(SESSION_ID, {
			type: 'assistant.message',
			id: '10000000-0000-4000-8000-000000000003',
			timestamp: '2026-07-27T12:00:02.000Z',
			parentId: null,
			data: {
				messageId: 'message-1',
				content: 'Visible answer',
				reasoningText: 'Hidden chain of thought',
				toolRequests: [{ toolCallId: 'call-1', name: 'write_file', arguments: '{"path":"Mana.java"}', type: 'function' }],
			},
		}, 3, { includeVisibleContent: true });

		expect({
			payload: event?.payload,
			containsHiddenReasoning: JSON.stringify(event).includes('Hidden chain of thought'),
		}).toEqual({
			payload: {
				content_length: 14,
				tool_request_count: 1,
				has_reasoning: true,
				content: 'Visible answer',
				tool_requests: [{ toolCallId: 'call-1', name: 'write_file', arguments: '{"path":"Mana.java"}', type: 'function' }],
			},
			containsHiddenReasoning: false,
		});
	});

	it('keeps multibyte visible content below the durable event limit', () => {
		const huge = '😀"\\\n'.repeat(20_000);
		const entries = [
			{
				type: 'user.message' as const,
				id: '10000000-0000-4000-8000-000000000010',
				timestamp: '2026-07-27T12:00:10.000Z',
				parentId: null,
				data: { content: huge, attachments: [] },
			},
			{
				type: 'assistant.message' as const,
				id: '10000000-0000-4000-8000-000000000011',
				timestamp: '2026-07-27T12:00:11.000Z',
				parentId: null,
				data: {
					messageId: 'message-large',
					content: huge,
					toolRequests: [{ toolCallId: 'call-large', name: 'write_file', arguments: huge, type: 'function' as const }],
				},
			},
			{
				type: 'tool.execution_start' as const,
				id: '10000000-0000-4000-8000-000000000012',
				timestamp: '2026-07-27T12:00:12.000Z',
				parentId: null,
				data: { toolCallId: 'call-large', toolName: 'write_file', arguments: { content: huge } },
			},
			{
				type: 'tool.execution_complete' as const,
				id: '10000000-0000-4000-8000-000000000013',
				timestamp: '2026-07-27T12:00:13.000Z',
				parentId: null,
				data: { toolCallId: 'call-large', success: true, result: { content: huge } },
			},
		];
		const events = entries.map((entry, index) => mapTranscriptEntryToTraceEvent(
			SESSION_ID,
			entry,
			index + 10,
			{ includeVisibleContent: true },
		)!);
		const eventBytes = events.map(event => Buffer.byteLength(JSON.stringify(event), 'utf8'));
		const payloadBytes = events.map(event => Buffer.byteLength(JSON.stringify(event.payload), 'utf8'));

		expect({
			allEventsBelow64KiB: eventBytes.every(bytes => bytes < 64 * 1024),
			allPayloadsBelow50KiB: payloadBytes.every(bytes => bytes < 50 * 1024),
			allValuesTruncated: events.every(event => JSON.stringify(event.payload).includes('truncated')),
		}).toEqual({
			allEventsBelow64KiB: true,
			allPayloadsBelow50KiB: true,
			allValuesTruncated: true,
		});
	});

	it('creates one terminal event and binds parallel native tool calls', () => {
		const transcript = new RecordingTranscriptService();
		const log = new TestLogService();
		const service = new ModelRequestTraceService(transcript, log);
		const handle = service.begin({
			sessionId: SESSION_ID,
			turnId: '2',
			provider: 'copilot',
			model: 'model-a',
			parentEventId: '10000000-0000-4000-8000-000000000003',
		});
		const first = handle.bindToolCall('call-a__vscode-1');
		const second = handle.bindToolCall('call-b__vscode-2');
		handle.complete({ durationMs: 25, usage: { inputTokens: 10, outputTokens: 5 } });
		handle.fail({ code: 'late', retryable: false, durationMs: 30 });

		expect({
			entryTypes: transcript.entries.map(entry => entry.type),
			startedValues: transcript.entries[0].values,
			first,
			second,
			lookupA: service.getToolCallContext(SESSION_ID, 'call-a'),
			lookupB: service.getToolCallContext(SESSION_ID, 'call-b'),
			diagnosticCount: log.diagnostics.length,
		}).toEqual({
			entryTypes: ['started', 'completed'],
			startedValues: [SESSION_ID, 'copilot', 'model-a', handle.modelRequestId, handle.startedEventId, '10000000-0000-4000-8000-000000000003'],
			first: { sessionId: SESSION_ID, turnId: '2', modelRequestId: handle.modelRequestId, projectId: undefined, checkoutId: undefined, machineId: undefined, toolCallId: 'call-a' },
			second: { sessionId: SESSION_ID, turnId: '2', modelRequestId: handle.modelRequestId, projectId: undefined, checkoutId: undefined, machineId: undefined, toolCallId: 'call-b' },
			lookupA: first,
			lookupB: second,
			diagnosticCount: 1,
		});
	});
});
