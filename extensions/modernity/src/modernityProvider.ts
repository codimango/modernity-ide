/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';

/*
 * Built-in Modernity language-model provider.
 * Implements vendor "modernity" via LanguageModelChatProvider.
 * - Model discovery: GET /api/inference/v1/models
 * - Chat: POST /api/inference/v1/chat/completions with SSE streaming
 */

interface GatewayModelCapabilities {
	tool_calling?: boolean;
	streaming?: boolean;
	vision?: boolean;
}

interface GatewayModel {
	id: string;
	object?: string;
	owned_by?: string;
	capabilities?: GatewayModelCapabilities;
}

interface GatewayModelList {
	object: string;
	data: GatewayModel[];
}

interface ChatCompletionsToolCall {
	index?: number;
	id?: string;
	type?: string;
	function?: {
		name?: string;
		arguments?: string;
	};
}

interface ChatCompletionsChunk {
	id?: string;
	object?: string;
	created?: number;
	model?: string;
	choices?: Array<{
		index: number;
		delta?: {
			role?: string;
			content?: string;
			tool_calls?: ChatCompletionsToolCall[];
			refusal?: string;
		};
		finish_reason?: string | null;
	}>;
	usage?: unknown;
	error?: {
		message: string;
		type: string;
		code?: string;
		param?: string | null;
	};
}

function randomUUID(): string {
	try {
		// @ts-ignore - crypto may be available globally in node 19+ and browser
		const c = (globalThis as any).crypto;
		if (c && typeof c.randomUUID === 'function') {
			return c.randomUUID();
		}
	} catch { }
	return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

function isTextPart(part: any): part is vscode.LanguageModelTextPart {
	return !!part && typeof part.value === 'string' && typeof part.callId === 'undefined' && typeof part.name === 'undefined' && typeof (part as any).input === 'undefined' && typeof (part as any).mimeType === 'undefined';
}

function isToolCallPart(part: any): part is vscode.LanguageModelToolCallPart {
	return !!part && typeof part.callId === 'string' && typeof part.name === 'string' && typeof (part as any).input !== 'undefined';
}

function isToolResultPart(part: any): part is vscode.LanguageModelToolResultPart {
	return !!part && typeof part.callId === 'string' && Array.isArray(part.content);
}

function isDataPart(part: any): boolean {
	return !!part && typeof part.mimeType === 'string' && part.data instanceof Uint8Array;
}

function extractTextFromResultContent(content: ReadonlyArray<any>): string {
	let out = '';
	for (const p of content) {
		if (isTextPart(p)) {
			out += p.value;
		} else if (isDataPart(p)) {
			// For data parts that are text, try to decode, otherwise skip
			try {
				if (p.mimeType.startsWith('text/')) {
					out += new TextDecoder().decode(p.data);
				} else {
					// fallback to json stringify of mime
					out += `[${p.mimeType}]`;
				}
			} catch {
				// ignore
			}
		} else if (typeof (p as any).value === 'string') {
			out += (p as any).value;
		}
	}
	return out;
}

function getBaseUrlFromConfig(extensionMode?: number): string {
	// 1. VS Code setting modernity.gatewayUrl
	try {
		const config = vscode.workspace.getConfiguration('modernity');
		const configured = config.get<string>('gatewayUrl');
		if (configured && configured.trim()) {
			return configured.trim().replace(/\/+$/, '');
		}
	} catch { }

	// 2. Environment variables (useful for dev and for packaged builds with env injection)
	try {
		const env = (typeof process !== 'undefined' ? (process as any).env : undefined) as Record<string, string> | undefined;
		if (env) {
			const candidates = [
				env['MODERNITY_GATEWAY_URL'],
				env['MODERNITY_API_BASE_URL'],
				env['MODERNITY_INFERENCE_BASE_URL'],
				env['MODERNITY_API_URL'],
			];
			for (const c of candidates) {
				if (c && c.trim()) {
					return c.trim().replace(/\/+$/, '');
				}
			}
			const chatEnv = env['MODERNITY_CHAT_COMPLETIONS_URL'];
			if (chatEnv && chatEnv.trim()) {
				const trimmed = chatEnv.trim();
				if (trimmed.includes('/api/inference/')) {
					return trimmed.split('/api/inference/')[0].replace(/\/+$/, '');
				}
				return trimmed.replace(/\/+$/, '');
			}
		}
	} catch { }

	// 3. Distinguish development vs packaged builds
	// Development builds (ExtensionMode.Development or Test) point to localhost
	// Packaged builds (Production) point to configured private gateway URL, fallback to modernity.dev
	// VS Code ExtensionMode: 1=Production, 2=Development, 3=Test (enum values)
	const isProd = extensionMode === 1; // vscode.ExtensionMode.Production == 1
	if (isProd) {
		// In packaged builds, try to read private gateway URL from config or env, fallback to modernity.dev
		// When we have production we will change hardcoded string -> modernity.dev/v1/chat/completions
		// For now, keep localhost as fallback but allow override via settings for private gateway
		try {
			const config = vscode.workspace.getConfiguration('modernity');
			const prodUrl = config.get<string>('gatewayUrl');
			if (prodUrl && prodUrl.trim() && prodUrl.trim() !== 'http://127.0.0.1:8000') {
				return prodUrl.trim().replace(/\/+$/, '');
			}
		} catch {}
		// Private gateway URL for production - can be overridden via MODERNITY_GATEWAY_URL env or settings
		// TODO: change to https://modernity.dev when production gateway is ready
		return 'https://modernity.dev';
	}

	// Development default
	return 'http://127.0.0.1:8000';
}

function getEndpointUrls(extensionMode?: number): { base: string; modelsUrl: string; chatCompletionsUrl: string } {
	let base = getBaseUrlFromConfig(extensionMode);

	// Allow full URL overrides via settings
	let modelsUrlOverride: string | undefined;
	let chatUrlOverride: string | undefined;
	try {
		const config = vscode.workspace.getConfiguration('modernity');
		modelsUrlOverride = config.get<string>('modelsUrl')?.trim() || undefined;
		chatUrlOverride = config.get<string>('chatCompletionsUrl')?.trim() || undefined;
		// treat empty string as not set
		if (modelsUrlOverride === '') { modelsUrlOverride = undefined; }
		if (chatUrlOverride === '') { chatUrlOverride = undefined; }
	} catch { }

	// Environment overrides for full URLs
	try {
		const env = (typeof process !== 'undefined' ? (process as any).env : undefined) as Record<string, string> | undefined;
		if (env) {
			if (!modelsUrlOverride) {
				const m = env['MODERNITY_MODELS_URL']?.trim();
				if (m) { modelsUrlOverride = m; }
			}
			if (!chatUrlOverride) {
				const c = env['MODERNITY_CHAT_COMPLETIONS_URL']?.trim();
				if (c) { chatUrlOverride = c; }
			}
		}
	} catch { }

	// Production gateway detection: if base contains modernity.dev or custom domain, use it.
	// For packaged builds, the configured private gateway URL will be supplied via settings or env above.
	// Otherwise fallback to localhost for development builds.

	const modelsUrl = modelsUrlOverride || `${base}/api/inference/v1/models`;
	const chatCompletionsUrl = chatUrlOverride || `${base}/api/inference/v1/chat/completions`;

	return { base, modelsUrl, chatCompletionsUrl };
}

function makeLMError(message: string, code?: string): vscode.LanguageModelError {
	const err = new (vscode as any).LanguageModelError(message) as vscode.LanguageModelError;
	if (code) {
		try { (err as any).code = code; } catch {}
	}
	return err;
}

function mapGatewayError(status: number, body: any): never {
	const errorObj = body?.error;
	const message = errorObj?.message || body?.message || `Gateway error ${status}`;
	let code: string;
	switch (status) {
		case 400:
			code = errorObj?.code || 'invalid_request';
			throw makeLMError(`Invalid request: ${message}`, code);
		case 401:
		case 403:
			throw makeLMError(`Authentication failed: ${message}`, 'auth_failed');
		case 429:
			throw makeLMError(`Rate limited: ${message}`, 'rate_limit');
		case 503:
			throw makeLMError(`Service unavailable: ${message}`, 'server_busy');
		case 504:
			throw makeLMError(`Gateway timeout: ${message}`, 'server_timeout');
		default:
			throw makeLMError(message, String(status));
	}
}

export class ModernityLanguageModelProvider implements vscode.LanguageModelChatProvider {
	readonly onDidChangeLanguageModelChatInformation?: vscode.Event<void>;
	private readonly _onDidChange = new vscode.EventEmitter<void>();
	private readonly _sessionId: string;
	private _turnCounter: number = 0;
	private readonly _clientVersion: string;

	constructor(private readonly _context: vscode.ExtensionContext) {
		this.onDidChangeLanguageModelChatInformation = this._onDidChange.event;
		this._sessionId = randomUUID();
		this._clientVersion = (_context.extension.packageJSON as any)?.version ?? '0.0.1';

		// In a real packaged build, we could fetch product.json's gateway URL or use configurationDefaults.
		// For now, dev builds point to localhost via getEndpointUrls().

		// Listen to config changes to refresh model list
		this._context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration('modernity.gatewayUrl') || e.affectsConfiguration('modernity.modelsUrl') || e.affectsConfiguration('modernity.chatCompletionsUrl')) {
				this._onDidChange.fire();
			}
		}));
	}

	async provideLanguageModelChatInformation(_options: vscode.PrepareLanguageModelChatModelOptions, token: vscode.CancellationToken): Promise<vscode.LanguageModelChatInformation[]> {
		const { modelsUrl, base } = getEndpointUrls((this._context as any).extensionMode);
		const controller = new AbortController();
		const disposable = token.onCancellationRequested(() => controller.abort());

		try {
			const response = await fetch(modelsUrl, {
				method: 'GET',
				headers: {
					'Accept': 'application/json',
					'X-Modernity-Session-ID': this._sessionId,
					'X-Modernity-Client-Version': this._clientVersion,
					'X-Modernity-Request-ID': randomUUID(),
				},
				signal: controller.signal as any,
			});

			if (!response.ok) {
				let body: any;
				try { body = await response.json(); } catch { body = await response.text(); }
				if (!token.isCancellationRequested) {
					// If gateway not ready or unreachable, fallback to default model instead of hard failing in silent mode
					if (_options.silent) {
						return this._fallbackModels(base);
					}
					mapGatewayError(response.status, body);
				}
				return this._fallbackModels(base);
			}

			const json = await response.json() as GatewayModelList;
			const data = (json as any).data ?? (json as any).models ?? [];
			if (!Array.isArray(data) || data.length === 0) {
				return this._fallbackModels(base);
			}

			const mapped = data.map(m => this._toChatInfo(m, base)).filter((x): x is vscode.LanguageModelChatInformation => !!x);
			if (mapped.length === 0) { return this._fallbackModels(base); }
			return mapped;
		} catch (err: any) {
			if (err?.name === 'AbortError' || token.isCancellationRequested) {
				return [];
			}
			// On network failure, return fallback so agent panel still shows model
			if (_options.silent) {
				return this._fallbackModels(base);
			}
			// For non-silent, still return fallback but log
			console.warn('[Modernity] Failed to fetch models, using fallback', err);
			return this._fallbackModels(base);
		} finally {
			disposable.dispose();
		}
	}

	private _fallbackModels(base: string): vscode.LanguageModelChatInformation[] {
		// Muse Spark is primary default, Claude as secondary option (routed by model param)
		// User task example shows both sharing same endpoint http://127.0.0.1:8000/api/inference/v1/chat/completions
		const models: vscode.LanguageModelChatInformation[] = [
			{
				id: 'muse-spark-1.1',
				name: 'Muse Spark',
				family: 'muse-spark',
				version: '1.1',
				tooltip: `Modernity inference via ${base}`,
				detail: base,
				maxInputTokens: 128000,
				maxOutputTokens: 16000,
				capabilities: {
					toolCalling: true,
					imageInput: false,
				},
				isUserSelectable: true,
				isDefault: true,
			} as any,
			{
				id: 'claude-4-8-opus-gcp-aai-abs-infra',
				name: 'Claude 4.8 Opus',
				family: 'claude',
				version: '4.8',
				tooltip: `Modernity inference via ${base} (routed by model param)`,
				detail: base,
				maxInputTokens: 128000,
				maxOutputTokens: 16000,
				capabilities: {
					toolCalling: true,
					imageInput: false,
				},
				isUserSelectable: true,
			} as any,
		];
		return models;
	}

	private _toChatInfo(raw: GatewayModel, base: string): vscode.LanguageModelChatInformation | null {
		const id = raw.id;
		const lower = id.toLowerCase();

		// Support both Muse Spark and Claude - routed by model param per task description example
		// Skip legacy Avocado ids
		if (lower.includes('avocado')) {
			return null;
		}

		let name = id;
		let family = 'muse-spark';
		if (lower.includes('muse-spark') || lower === 'muse-spark-1.1') {
			name = 'Muse Spark';
			family = 'muse-spark';
		} else if (lower.includes('claude')) {
			name = 'Claude 4.8 Opus';
			family = 'claude';
		} else {
			// Allow any model id that gateway returns (future models), keep id as name
			name = id;
			family = id.split('/').pop()?.split('-')[0] ?? 'muse-spark';
		}

		const caps = raw.capabilities ?? { tool_calling: true, streaming: true, vision: false };

		return {
			id,
			name,
			family,
			version: '1.1',
			tooltip: `Modernity via ${base}`,
			detail: base,
			maxInputTokens: 128000,
			maxOutputTokens: 16000,
			capabilities: {
				toolCalling: caps.tool_calling ?? true,
				imageInput: caps.vision ?? false,
			},
			isUserSelectable: true,
			isDefault: lower === 'muse-spark-1.1' ? true : undefined,
		} as any;
	}

	async provideLanguageModelChatResponse(model: vscode.LanguageModelChatInformation, messages: readonly vscode.LanguageModelChatRequestMessage[], options: vscode.ProvideLanguageModelChatResponseOptions, progress: vscode.Progress<vscode.LanguageModelResponsePart>, token: vscode.CancellationToken): Promise<void> {
		const urls = getEndpointUrls((this._context as any).extensionMode);
		const requestId = randomUUID();
		this._turnCounter += 1;
		const turnId = `${this._turnCounter}`;

		// Convert IDE messages and tools into Chat Completions requests
		const chatMessages = this._convertMessages(messages);
		const tools = this._convertTools(options.tools ?? []);

		const body: any = {
			model: model.id,
			messages: chatMessages,
			stream: true,
			stream_options: { include_usage: false },
		};

		if (tools.length > 0) {
			body.tools = tools;
			// Gateway currently supports only "auto" for tool_choice
			// Map Required -> auto to avoid UnsupportedInferenceFeature
			if (options.toolMode === (vscode as any).LanguageModelChatToolMode?.Required) {
				body.tool_choice = 'auto';
				// Alternatively, if only one tool, could force that tool, but gateway rejects non-auto
				// So we keep auto.
			} else {
				body.tool_choice = 'auto';
			}
			body.parallel_tool_calls = true;
		}

		// Forward model options like temperature if present
		const modelOptions = (options as any).modelOptions ?? {};
		if (typeof modelOptions.temperature === 'number') { body.temperature = modelOptions.temperature; }
		if (typeof modelOptions.top_p === 'number') { body.top_p = modelOptions.top_p; }
		if (typeof modelOptions.max_tokens === 'number') { body.max_tokens = modelOptions.max_tokens; }
		if (typeof modelOptions.reasoning_effort === 'string') { body.reasoning_effort = modelOptions.reasoning_effort; }

		const headers: Record<string, string> = {
			'Content-Type': 'application/json',
			'Accept': 'text/event-stream',
			'X-Modernity-Request-ID': requestId,
			'X-Modernity-Session-ID': this._sessionId,
			'X-Modernity-Turn-ID': turnId,
			'X-Modernity-Client-Version': this._clientVersion,
		};

		const controller = new AbortController();
		const cancelListener = token.onCancellationRequested(() => {
			// Cancel the HTTP request when the IDE cancellation token fires
			controller.abort();
		});

		try {
			const response = await fetch(urls.chatCompletionsUrl, {
				method: 'POST',
				headers,
				body: JSON.stringify(body),
				signal: controller.signal as any,
			});

			if (!response.ok) {
				let errorBody: any;
				const contentType = response.headers.get('content-type') ?? '';
				try {
					if (contentType.includes('application/json')) {
						errorBody = await response.json();
					} else {
						errorBody = { error: { message: await response.text() } };
					}
				} catch {
					errorBody = { error: { message: response.statusText } };
				}
				// Map gateway 400/429/503/504 errors to IDE language-model errors
				mapGatewayError(response.status, errorBody);
			}

			if (!response.body) {
				throw makeLMError('No response body from gateway', 'no_body');
			}

			// Parse SSE text and tool-call argument deltas
			await this._parseSSE(response, progress, token);

		} catch (err: any) {
			if (err?.name === 'AbortError' || token.isCancellationRequested) {
				// Cancellation is not an error - just return
				return;
			}
			if (err instanceof vscode.LanguageModelError) {
				throw err;
			}
			// Network or parsing errors -> map to server busy / timeout where appropriate
			const msg = err?.message ?? String(err);
			if (msg.includes('Failed to fetch') || msg.includes('ECONNREFUSED') || msg.includes('fetch failed')) {
				throw makeLMError(`Modernity gateway unreachable at ${urls.base}. Is the inference server running? (python -m uvicorn services.backend.api.main:app --host 127.0.0.1 --port 8000) - ${msg}`, 'server_busy');
			}
			throw makeLMError(msg, 'unknown');
		} finally {
			cancelListener.dispose();
		}
	}

	private _convertMessages(vscodeMessages: readonly vscode.LanguageModelChatRequestMessage[]): any[] {
		const out: any[] = [];

		for (const vm of vscodeMessages) {
			const roleNum = (vm as any).role as number;
			const roleStr = roleNum === 1 ? 'user' : 'assistant';
			const name = vm.name;

			const parts = (vm.content ?? []) as any[];

			const textParts = parts.filter(isTextPart) as vscode.LanguageModelTextPart[];
			const toolCallParts = parts.filter(isToolCallPart) as vscode.LanguageModelToolCallPart[];
			const toolResultParts = parts.filter(isToolResultPart) as vscode.LanguageModelToolResultPart[];

			if (roleStr === 'user') {
				if (toolResultParts.length === 0) {
					const text = textParts.map(p => p.value).join('');
					// Even if empty, push a user message to keep turn alignment (unless completely empty)
					if (text || parts.length === 0) {
						out.push({
							role: 'user',
							content: text || '',
							...(name ? { name } : {}),
						});
					} else {
						// If there are only data parts treated as text, convert
						const fallback = extractTextFromResultContent(parts as any);
						if (fallback) {
							out.push({ role: 'user', content: fallback, ...(name ? { name } : {}) });
						}
					}
				} else {
					// User message may have text + tool results.
					// Emit user text first, then each tool result as separate "tool" role messages.
					const userText = textParts.map(p => p.value).join('');
					if (userText) {
						out.push({ role: 'user', content: userText, ...(name ? { name } : {}) });
					}
					for (const trp of toolResultParts) {
						const toolContent = extractTextFromResultContent(trp.content as any);
						out.push({
							role: 'tool',
							tool_call_id: trp.callId,
							content: toolContent,
						});
					}
				}
			} else {
				// Assistant
				const text = textParts.map(p => p.value).join('');
				if (toolCallParts.length === 0) {
					out.push({
						role: 'assistant',
						content: text || null,
						...(name ? { name } : {}),
					});
				} else {
					const tool_calls = toolCallParts.map(tcp => ({
						id: tcp.callId,
						type: 'function',
						function: {
							name: tcp.name,
							arguments: JSON.stringify(tcp.input),
						},
					}));
					out.push({
						role: 'assistant',
						content: text || null,
						tool_calls,
						...(name ? { name } : {}),
					});
				}
			}
		}

		return out;
	}

	private _convertTools(vsTools: readonly vscode.LanguageModelChatTool[]): any[] {
		return vsTools.map(t => ({
			type: 'function',
			function: {
				name: t.name,
				description: t.description,
				parameters: (t as any).inputSchema ?? { type: 'object', properties: {} },
			},
		}));
	}

	private async _parseSSE(response: Response, progress: vscode.Progress<vscode.LanguageModelResponsePart>, token: vscode.CancellationToken): Promise<void> {
		// Use streaming reader to parse SSE
		const body = response.body as any;
		// Compatibility: body may be Node ReadableStream or Web ReadableStream
		let reader: { read: () => Promise<{ done: boolean; value?: Uint8Array }> };
		if (body.getReader) {
			reader = body.getReader();
		} else {
			// Node stream fallback - wrap as async iterator
			const nodeStream = body as NodeJS.ReadableStream & AsyncIterable<Buffer>;
			const iterator = nodeStream[Symbol.asyncIterator]();
			reader = {
				read: async () => {
					try {
						const { value, done } = await iterator.next();
						if (done) { return { done: true }; }
						return { done: false, value: value as unknown as Uint8Array };
					} catch {
						return { done: true };
					}
				}
			};
		}

		const decoder = new TextDecoder('utf-8');
		let buffer = '';
		const toolCallsAcc = new Map<number, { id: string; name: string; args: string }>();

		const emitToolCalls = () => {
			if (toolCallsAcc.size === 0) { return; }
			for (const [, acc] of toolCallsAcc) {
				if (!acc.name) { continue; }
				let input: object;
				try {
					input = acc.args ? JSON.parse(acc.args) : {};
				} catch {
					// If arguments are still streaming or malformed, try best effort - keep as empty object if not parseable yet
					// For final emission we want parsed; if fails keep raw string in object?
					try {
						// attempt to handle incomplete JSON by returning {} and let model retry? We follow Copilot pattern: fallback to {}
						input = {};
					} catch {
						input = {};
					}
				}
				// Emit LanguageModelToolCallPart
				progress.report(new vscode.LanguageModelToolCallPart(acc.id || randomUUID(), acc.name, input));
			}
			toolCallsAcc.clear();
		};

		try {
			while (true) {
				if (token.isCancellationRequested) { break; }
				const { done, value } = await reader.read();
				if (done) { break; }
				if (!value) { continue; }
				buffer += decoder.decode(value, { stream: true });

				// Split buffer into lines, keep leftover
				const lines = buffer.split('\n');
				buffer = lines.pop() ?? '';

				for (let line of lines) {
					line = line.trim();
					if (!line) { continue; }
					if (line.startsWith(':')) { continue; } // SSE comment
					if (!line.startsWith('data:')) { continue; }
					const dataStr = line.slice(5).trim();
					if (!dataStr) { continue; }
					if (dataStr === '[DONE]') { continue; }

					let json: ChatCompletionsChunk;
					try {
						json = JSON.parse(dataStr) as ChatCompletionsChunk;
					} catch {
						continue;
					}

					// Check for error envelope yielded by inference service during streaming
					if ((json as any).error) {
						const err = (json as any).error;
						const message = err.message ?? 'Gateway streaming error';
						// Map error codes from stream to IDE errors
						const code = err.code ?? '';
						if (code.includes('rate_limit') || err.type === 'rate_limit_error') {
							throw makeLMError(message, 'rate_limit');
						}
						if (code.includes('timeout') || err.type === 'timeout_error') {
							throw makeLMError(message, 'server_timeout');
						}
						if (code.includes('provider_failed') || code.includes('incomplete')) {
							throw makeLMError(message, 'server_busy');
						}
						throw makeLMError(message, code || err.type || 'server_error');
					}

					const choice = json.choices?.[0];
					if (!choice) { continue; }

					const delta = choice.delta;
					if (delta) {
						// Emit LanguageModelTextPart
						if (typeof delta.content === 'string' && delta.content.length > 0) {
							progress.report(new vscode.LanguageModelTextPart(delta.content));
						}
						// Handle refusal as text as well (optional)
						if (typeof delta.refusal === 'string' && delta.refusal.length > 0) {
							progress.report(new vscode.LanguageModelTextPart(delta.refusal));
						}
						// Parse SSE text and tool-call argument deltas
						if (delta.tool_calls && delta.tool_calls.length > 0) {
							for (const tc of delta.tool_calls) {
								const idx = tc.index ?? 0;
								const existing = toolCallsAcc.get(idx) ?? { id: '', name: '', args: '' };
								if (tc.id) { existing.id = tc.id; }
								if (tc.function?.name) { existing.name = tc.function.name; }
								if (typeof tc.function?.arguments === 'string') {
									existing.args += tc.function.arguments;
								}
								toolCallsAcc.set(idx, existing);
							}
						}
					}

					if (choice.finish_reason) {
						if (choice.finish_reason === 'tool_calls' || toolCallsAcc.size > 0) {
							// Emit accumulated tool calls at finish
							// For toolCalls, arguments may have been streamed as deltas - we now emit final parts
							for (const [, acc] of toolCallsAcc) {
								if (!acc.name) { continue; }
								let input: object;
								try {
									input = acc.args ? JSON.parse(acc.args) : {};
								} catch {
									// fallback - if still not valid JSON, emit empty object
									input = {};
								}
								progress.report(new vscode.LanguageModelToolCallPart(acc.id || randomUUID(), acc.name, input));
							}
							toolCallsAcc.clear();
						}
						// stop or length also ends stream logically, but we continue to drain until DONE
					}
				}
			}

			// If stream ended but we still have pending tool calls (e.g. server closed without finish_reason)
			if (toolCallsAcc.size > 0) {
				emitToolCalls();
			}

			// Flush any remaining buffer that might contain a final data line without newline
			if (buffer.trim().startsWith('data:')) {
				const dataStr = buffer.trim().slice(5).trim();
				if (dataStr && dataStr !== '[DONE]') {
					try {
						const json = JSON.parse(dataStr) as ChatCompletionsChunk;
						const choice = json.choices?.[0];
						if (choice?.delta?.content) {
							progress.report(new vscode.LanguageModelTextPart(choice.delta.content));
						}
					} catch { }
				}
			}

		} finally {
			try {
				// Close reader if possible
				// @ts-ignore
				if (typeof reader.cancel === 'function') { await (reader as any).cancel(); }
				// @ts-ignore
				if (typeof reader.releaseLock === 'function') { (reader as any).releaseLock(); }
			} catch { }
		}
	}

	async provideTokenCount(_model: vscode.LanguageModelChatInformation, text: string | vscode.LanguageModelChatRequestMessage, _token: vscode.CancellationToken): Promise<number> {
		// Simple heuristic: ~4 chars per token, similar to OpenAI tokenizer estimate
		// For a proper implementation we could use tokenizer, but this satisfies VS Code's requirement
		if (typeof text === 'string') {
			return Math.ceil(text.length / 4);
		}
		// text is a chat request message
		const parts = (text as any).content as ReadonlyArray<any> ?? [];
		let total = 0;
		for (const p of parts) {
			if (isTextPart(p)) {
				total += Math.ceil(p.value.length / 4);
			} else if (isToolCallPart(p)) {
				total += Math.ceil((p.name.length + JSON.stringify(p.input).length) / 4) + 4;
			} else if (isToolResultPart(p)) {
				total += extractTextFromResultContent(p.content as any).length / 4;
			}
		}
		// overhead per message
		return Math.ceil(total) + 4;
	}
}
