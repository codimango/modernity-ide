/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

/**
 * OpenAI-compatible types used for the gateway.
 */
interface OpenAITool {
	type: 'function';
	function: {
		name: string;
		description?: string;
		parameters?: object;
	};
}

interface OpenAIToolCall {
	id: string;
	type: 'function';
	function: {
		name: string;
		arguments: string;
	};
}

interface OpenAIChatMessage {
	role: 'system' | 'user' | 'assistant' | 'tool';
	content: string | null | Array<{ type: string; text?: string; image_url?: { url: string } }>;
	name?: string;
	tool_calls?: OpenAIToolCall[];
	tool_call_id?: string;
}

interface OpenAIChatCompletionRequest {
	model: string;
	messages: OpenAIChatMessage[];
	tools?: OpenAITool[];
	tool_choice?: 'auto' | 'required' | 'none' | { type: 'function'; function: { name: string } };
	stream: boolean;
	stream_options?: { include_usage: boolean };
	temperature?: number;
	top_p?: number;
	[key: string]: unknown;
}

interface OpenAIChatDelta {
	role?: string;
	content?: string;
	tool_calls?: Array<{
		index: number;
		id?: string;
		type?: string;
		function?: {
			name?: string;
			arguments?: string;
		};
	}>;
}

interface OpenAIStreamChunk {
	id?: string;
	choices?: Array<{
		delta?: OpenAIChatDelta;
		finish_reason?: string | null;
		index?: number;
	}>;
}

interface ModelsListResponse {
	data?: Array<{ id: string; name?: string; family?: string; version?: string; maxInputTokens?: number; maxOutputTokens?: number; context_length?: number; capabilities?: { toolCalling?: boolean; imageInput?: boolean } }>;
	models?: Array<{ id: string; name?: string }>;
	object?: string;
}

type ToolCallAccumulator = {
	callId: string;
	name: string;
	args: string;
};

function getExtensionVersion(): string {
	try {
		const ext = vscode.extensions.getExtension('modernity.modernity');
		return (ext?.packageJSON?.version as string) || '0.0.1';
	} catch {
		return '0.0.1';
	}
}

function getGatewayBaseUrl(context: vscode.ExtensionContext): string {
	const configUrl = vscode.workspace.getConfiguration('modernity').get<string>('gatewayUrl')?.trim();

	// Product.json may contain private gateway URL override for packaged builds
	// For now we rely on configuration, but also check env var which can be injected in packaged builds.
	const envUrl = (typeof process !== 'undefined' && process.env && (process.env.MODERNITY_GATEWAY_URL || process.env.MODERNITY_PRIVATE_GATEWAY)) || '';

	const isDev = context.extensionMode === vscode.ExtensionMode.Development;

	// Development builds -> localhost per task requirement
	// Note: endpoint hardcoded to http://127.0.0.1:8000/api/inference/v1/chat/completions per instruction
	if (isDev) {
		return 'http://127.0.0.1:8000';
	}

	// Packaged builds -> configured private gateway URL
	if (configUrl && configUrl.length > 0) {
		return configUrl.replace(/\/+$/, '');
	}
	if (envUrl && envUrl.length > 0) {
		return envUrl.replace(/\/+$/, '');
	}

	// Fallback – still localhost until prod URL (modernity.dev/v1/chat/completions) is ready.
	// When prod is ready, change this string to e.g. https://modernity.dev
	return 'http://127.0.0.1:8000';
}

function getModelsUrl(context: vscode.ExtensionContext): string {
	const base = getGatewayBaseUrl(context);
	const path = vscode.workspace.getConfiguration('modernity').get<string>('modelsPath')?.trim() || '/api/inference/v1/models';
	const normalizedBase = base.replace(/\/+$/, '');
	const normalizedPath = path.startsWith('/') ? path : `/${path}`;
	return `${normalizedBase}${normalizedPath}`;
}

function getChatCompletionsUrl(context: vscode.ExtensionContext): string {
	const base = getGatewayBaseUrl(context);
	const path = vscode.workspace.getConfiguration('modernity').get<string>('chatCompletionsPath')?.trim() || '/api/inference/v1/chat/completions';
	const normalizedBase = base.replace(/\/+$/, '');
	const normalizedPath = path.startsWith('/') ? path : `/${path}`;
	// Hardcode requirement: endpoint must be localhost when needed
	// The task note says hardcode to http://127.0.0.1:8000/api/inference/v1/chat/completions for now
	if (normalizedBase.includes('127.0.0.1') || normalizedBase.includes('localhost')) {
		// Ensure path matches spec exactly
		return `${normalizedBase}/api/inference/v1/chat/completions`;
	}
	return `${normalizedBase}${normalizedPath}`;
}

function convertIdeMessagesToOpenAI(
	messages: readonly vscode.LanguageModelChatRequestMessage[]
): OpenAIChatMessage[] {
	const result: OpenAIChatMessage[] = [];

	for (const msg of messages) {
		const roleVal: any = (msg.role as any);
		const isSystem = roleVal === (vscode.LanguageModelChatMessageRole as any).System || roleVal === 3;
		const isAssistant = roleVal === vscode.LanguageModelChatMessageRole.Assistant || roleVal === 2;
		const role = isSystem ? 'system' : isAssistant ? 'assistant' : 'user';

		const textParts: string[] = [];
		const toolCalls: OpenAIToolCall[] = [];
		const toolResults: Array<{ callId: string; content: string }> = [];
		const imageContents: Array<{ type: 'image_url'; image_url: { url: string } }> = [];

		for (const part of msg.content) {
			if (part instanceof vscode.LanguageModelTextPart) {
				textParts.push(part.value);
			} else if (part instanceof vscode.LanguageModelToolCallPart) {
				toolCalls.push({
					id: part.callId,
					type: 'function',
					function: {
						name: part.name,
						arguments: JSON.stringify(part.input)
					}
				});
			} else if (part instanceof vscode.LanguageModelToolResultPart) {
				let resultText = '';
				for (const inner of part.content) {
					if (inner instanceof vscode.LanguageModelTextPart) {
						resultText += inner.value;
					} else if (inner instanceof vscode.LanguageModelDataPart) {
						try {
							const decoded = new TextDecoder().decode(inner.data);
							resultText += decoded;
						} catch {
							// ignore
						}
					} else if (typeof inner === 'object' && inner !== null && 'value' in (inner as any)) {
						resultText += String((inner as any).value);
					} else if (typeof inner === 'string') {
						resultText += inner;
					}
				}
				toolResults.push({ callId: part.callId, content: resultText });
			} else if (part instanceof vscode.LanguageModelDataPart) {
				if (part.mimeType.startsWith('image/')) {
					try {
						const base64 = Buffer.from(part.data).toString('base64');
						const dataUrl = `data:${part.mimeType};base64,${base64}`;
						imageContents.push({ type: 'image_url', image_url: { url: dataUrl } });
					} catch {
						// ignore
					}
				}
			} else {
				const anyPart: any = part as any;
				if (typeof anyPart?.value === 'string') {
					textParts.push(anyPart.value);
				}
			}
		}

		if (toolResults.length > 0) {
			for (const tr of toolResults) {
				result.push({
					role: 'tool',
					tool_call_id: tr.callId,
					content: tr.content
				});
			}
			if (textParts.length > 0) {
				result.push({
					role: 'user',
					content: textParts.join('')
				});
			}
		} else if (toolCalls.length > 0) {
			result.push({
				role: 'assistant',
				content: textParts.join('') || null,
				tool_calls: toolCalls
			});
		} else {
			const joinedText = textParts.join('');
			if (imageContents.length > 0) {
				const contentArray: Array<{ type: string; text?: string; image_url?: { url: string } }> = [];
				if (joinedText) {
					contentArray.push({ type: 'text', text: joinedText });
				}
				for (const img of imageContents) {
					contentArray.push({ type: 'image_url', image_url: img.image_url });
				}
				result.push({
					role: role as any,
					content: contentArray as any,
					name: msg.name || undefined
				});
			} else {
				result.push({
					role: role as any,
					content: joinedText,
					name: msg.name || undefined
				});
			}
		}
	}

	return result;
}

function convertIdeToolsToOpenAI(
	tools?: readonly vscode.LanguageModelChatTool[]
): OpenAITool[] | undefined {
	if (!tools || tools.length === 0) {
		return undefined;
	}
	return tools.map(t => ({
		type: 'function',
		function: {
			name: t.name,
			description: t.description,
			parameters: t.inputSchema as object ?? { type: 'object', properties: {} }
		}
	}));
}

function mapGatewayError(status: number, bodyText: string): Error {
	const message = `Modernity gateway error ${status}: ${bodyText.slice(0, 1000)}`;
	switch (status) {
		case 400:
			return vscode.LanguageModelError.Blocked(message);
		case 401:
		case 403:
			return vscode.LanguageModelError.NoPermissions(message);
		case 404:
			return vscode.LanguageModelError.NotFound(message);
		case 429:
			return vscode.LanguageModelError.Blocked(message);
		case 503:
			return vscode.LanguageModelError.Blocked(message);
		case 504:
			return vscode.LanguageModelError.Blocked(message);
		default:
			if (status >= 400 && status < 500) {
				return vscode.LanguageModelError.Blocked(message);
			}
			if (status >= 500) {
				return vscode.LanguageModelError.Blocked(message);
			}
			return new Error(message);
	}
}

export class ModernityLanguageModelProvider implements vscode.LanguageModelChatProvider {
	private readonly _onDidChange = new vscode.EventEmitter<void>();
	readonly onDidChangeLanguageModelChatInformation = this._onDidChange.event;

	private readonly _sessionId: string;
	private _turnCounter: number = 0;
	private _context: vscode.ExtensionContext;

	constructor(context: vscode.ExtensionContext) {
		this._context = context;
		try {
			this._sessionId = (globalThis as any).crypto?.randomUUID?.() ?? this._generateUuidFallback();
		} catch {
			this._sessionId = this._generateUuidFallback();
		}

		vscode.workspace.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration('modernity.gatewayUrl') || e.affectsConfiguration('modernity.modelsPath') || e.affectsConfiguration('modernity.chatCompletionsPath')) {
				this._onDidChange.fire();
			}
		});
	}

	private _generateUuidFallback(): string {
		return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
			const r = Math.random() * 16 | 0;
			const v = c === 'x' ? r : (r & 0x3 | 0x8);
			return v.toString(16);
		});
	}

	private _generateRequestId(): string {
		try {
			return (globalThis as any).crypto?.randomUUID?.() ?? this._generateUuidFallback();
		} catch {
			return this._generateUuidFallback();
		}
	}

	async provideLanguageModelChatInformation(
		_options: vscode.PrepareLanguageModelChatModelOptions,
		_token: vscode.CancellationToken
	): Promise<vscode.LanguageModelChatInformation[]> {
		const modelsUrl = getModelsUrl(this._context);
		try {
			const controller = new AbortController();
			const timeout = setTimeout(() => controller.abort(), 10000);
			_token.onCancellationRequested(() => controller.abort());

			const response = await fetch(modelsUrl, {
				method: 'GET',
				headers: {
					'Accept': 'application/json',
					'X-Request-Id': this._generateRequestId(),
					'X-Session-Id': this._sessionId,
					'X-Client-Version': `${vscode.version}-${getExtensionVersion()}`
				},
				signal: controller.signal as any
			});
			clearTimeout(timeout);

			if (!response.ok) {
				const body = await response.text().catch(() => '');
				console.warn(`[Modernity] Models discovery failed ${response.status}: ${body}`);
				return this._getFallbackModels();
			}

			const json = await response.json() as ModelsListResponse;
			const rawModels = json.data ?? json.models ?? [];
			if (!Array.isArray(rawModels) || rawModels.length === 0) {
				return this._getFallbackModels();
			}

			return rawModels.map(m => {
				const id = m.id;
				return {
					id,
					name: (m as any).name || id,
					family: (m as any).family || id.split('/')[0] || 'modernity',
					version: (m as any).version || id,
					tooltip: `Modernity model ${id} via ${getGatewayBaseUrl(this._context)}`,
					detail: 'Modernity',
					maxInputTokens: (m as any).maxInputTokens || (m as any).context_length || 128000,
					maxOutputTokens: (m as any).maxOutputTokens || 8192,
					capabilities: {
						toolCalling: true,
						imageInput: (m as any).capabilities?.imageInput ?? false
					}
				} as vscode.LanguageModelChatInformation;
			});
		} catch (err: any) {
			if (err?.name === 'AbortError') {
				return [];
			}
			console.warn(`[Modernity] Failed to fetch models from ${modelsUrl}: ${err?.message ?? String(err)}`);
			return this._getFallbackModels();
		}
	}

	private _getFallbackModels(): vscode.LanguageModelChatInformation[] {
		return [
			{
				id: 'meta/avocado-5.14-agent',
				name: 'Avocado 5.14 Agent',
				family: 'meta',
				version: '5.14',
				detail: 'Modernity (fallback)',
				tooltip: 'Local dev fallback – gateway at http://127.0.0.1:8000',
				maxInputTokens: 128000,
				maxOutputTokens: 8192,
				capabilities: { toolCalling: true, imageInput: false }
			},
			{
				id: 'meta/avocado-code-flex',
				name: 'Avocado Code Flex',
				family: 'meta',
				version: 'flex',
				detail: 'Modernity (fallback)',
				tooltip: 'Local dev fallback',
				maxInputTokens: 128000,
				maxOutputTokens: 8192,
				capabilities: { toolCalling: true, imageInput: false }
			}
		] as vscode.LanguageModelChatInformation[];
	}

	async provideLanguageModelChatResponse(
		model: vscode.LanguageModelChatInformation,
		messages: readonly vscode.LanguageModelChatRequestMessage[],
		options: vscode.ProvideLanguageModelChatResponseOptions,
		progress: vscode.Progress<vscode.LanguageModelResponsePart>,
		token: vscode.CancellationToken
	): Promise<void> {
		const chatUrl = getChatCompletionsUrl(this._context);
		const requestId = this._generateRequestId();
		this._turnCounter++;
		const turn = this._turnCounter;
		const clientVersion = `${vscode.version}-${getExtensionVersion()}`;
		const extensionVersion = getExtensionVersion();

		const openAiMessages = convertIdeMessagesToOpenAI(messages);
		const openAiTools = convertIdeToolsToOpenAI(options.tools as any);

		let toolChoice: OpenAIChatCompletionRequest['tool_choice'] = 'auto';
		if (options.toolMode === vscode.LanguageModelChatToolMode.Required) {
			toolChoice = 'required';
		}

		const body: OpenAIChatCompletionRequest = {
			model: model.id,
			messages: openAiMessages,
			tools: openAiTools,
			tool_choice: openAiTools ? toolChoice : undefined,
			stream: true,
			stream_options: { include_usage: true },
			...(options.modelOptions as any ?? {})
		};

		const abortController = new AbortController();
		const cancellationListener = token.onCancellationRequested(() => {
			abortController.abort();
		});

		try {
			const response = await fetch(chatUrl, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Accept': 'text/event-stream',
					'X-Request-Id': requestId,
					'X-Request': requestId,
					'X-Session-Id': this._sessionId,
					'X-Session': this._sessionId,
					'X-Turn': String(turn),
					'X-Turn-Id': String(turn),
					'X-Client-Version': clientVersion,
					'X-Client': `modernity-ide/${extensionVersion}`,
					'X-Extension-Version': extensionVersion
				},
				body: JSON.stringify(body),
				signal: abortController.signal as any
			});

			if (!response.ok) {
				const errorBody = await response.text().catch(() => '');
				throw mapGatewayError(response.status, errorBody);
			}

			if (!response.body) {
				throw new Error('No response body from Modernity gateway');
			}

			const reader = (response.body as any).getReader();
			const decoder = new TextDecoder('utf-8');
			let buffer = '';
			const toolCallMap = new Map<number, ToolCallAccumulator>();

			while (true) {
				const { done, value } = await reader.read();
				if (done) {
					break;
				}
				if (token.isCancellationRequested) {
					abortController.abort();
					break;
				}
				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() ?? '';

				for (const lineRaw of lines) {
					const line = lineRaw.trim();
					if (!line) {
						continue;
					}
					if (line.startsWith(':')) {
						continue;
					}
					if (!line.startsWith('data:')) {
						continue;
					}
					const dataStr = line.slice(5).trim();
					if (!dataStr) {
						continue;
					}
					if (dataStr === '[DONE]') {
						continue;
					}
					let chunk: OpenAIStreamChunk;
					try {
						chunk = JSON.parse(dataStr) as OpenAIStreamChunk;
					} catch {
						continue;
					}

					const choice = chunk.choices?.[0];
					if (!choice) {
						continue;
					}
					const delta = choice.delta;
					if (!delta) {
						continue;
					}

					if (typeof delta.content === 'string' && delta.content.length > 0) {
						progress.report(new vscode.LanguageModelTextPart(delta.content));
					}

					if (delta.tool_calls && delta.tool_calls.length > 0) {
						for (const tc of delta.tool_calls) {
							const idx = tc.index ?? 0;
							let acc = toolCallMap.get(idx);
							if (!acc) {
								acc = { callId: '', name: '', args: '' };
								toolCallMap.set(idx, acc);
							}
							if (tc.id) {
								acc.callId = tc.id;
							}
							if (tc.function?.name) {
								acc.name = tc.function.name;
							}
							if (typeof tc.function?.arguments === 'string') {
								acc.args += tc.function.arguments;
							}
						}
					}
				}
			}

			for (const [idx, acc] of toolCallMap) {
				if (!acc.name && !acc.callId && !acc.args) {
					continue;
				}
				let parsedInput: object;
				try {
					parsedInput = acc.args ? JSON.parse(acc.args) : {};
				} catch {
					parsedInput = {};
				}
				const callId = acc.callId || `call_${idx}_${Date.now()}`;
				const name = acc.name || 'unknown_tool';
				progress.report(new vscode.LanguageModelToolCallPart(callId, name, parsedInput));
			}
		} catch (err: any) {
			if (err?.name === 'AbortError' && token.isCancellationRequested) {
				return;
			}
			if (err instanceof vscode.LanguageModelError) {
				throw err;
			}
			const abortCause = err?.cause;
			if (abortCause && token.isCancellationRequested) {
				return;
			}
			if (typeof err?.status === 'number') {
				throw mapGatewayError(err.status, err?.message ?? String(err));
			}
			throw err;
		} finally {
			cancellationListener.dispose();
		}
	}

	async provideTokenCount(
		_model: vscode.LanguageModelChatInformation,
		text: string | vscode.LanguageModelChatRequestMessage,
		_token: vscode.CancellationToken
	): Promise<number> {
		if (typeof text === 'string') {
			return Math.ceil(text.length / 4);
		}
		let total = 0;
		for (const part of text.content) {
			if (part instanceof vscode.LanguageModelTextPart) {
				total += part.value.length;
			} else if (part instanceof vscode.LanguageModelToolCallPart) {
				total += JSON.stringify(part.input).length;
			} else if (part instanceof vscode.LanguageModelToolResultPart) {
				for (const inner of part.content) {
					if (inner instanceof vscode.LanguageModelTextPart) {
						total += inner.value.length;
					}
				}
			}
		}
		return Math.ceil(total / 4);
	}
}
