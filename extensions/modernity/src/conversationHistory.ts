/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *  Phase 0: Simple Local History + Resume - no backend, globalState + local file
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';

export interface StoredMessage {
	role: 'user' | 'assistant';
	text: string;
	timestamp: string;
}

export interface StoredConversation {
	conversationId: string;
	title: string;
	lastMessageAt: string;
	messages: StoredMessage[];
}

const GLOBAL_STATE_KEY = 'modernity.conversations';
const LAST_SESSION_KEY = 'modernity.lastSessionId';
const MAX_CONVERSATIONS = 50;
const MAX_MESSAGES_PER_CONVERSATION = 200;
const LOCAL_FILE = path.join(os.homedir(), '.modernity', 'conversations.json');

function nowIso(): string {
	return new Date().toISOString();
}

function generateTitle(firstText: string): string {
	const trimmed = firstText.trim().slice(0, 50);
	return trimmed || 'New Conversation';
}

function ensureDir(filePath: string): void {
	try {
		fs.mkdirSync(path.dirname(filePath), { recursive: true });
	} catch { }
}

export class ConversationHistory {
	private conversations: StoredConversation[] = [];
	private lastSessionId: string | undefined;

	constructor(private readonly context: vscode.ExtensionContext) {
		this.loadFromGlobalState();
		this.loadFromFile();
	}

	private loadFromGlobalState(): void {
		try {
			const stored = this.context.globalState.get<StoredConversation[]>(GLOBAL_STATE_KEY);
			if (Array.isArray(stored)) {
				this.conversations = stored;
			}
			const lastId = this.context.globalState.get<string>(LAST_SESSION_KEY);
			if (lastId) {
				this.lastSessionId = lastId;
			}
		} catch { }
	}

	private loadFromFile(): void {
		try {
			if (!fs.existsSync(LOCAL_FILE)) { return; }
			const raw = fs.readFileSync(LOCAL_FILE, 'utf8');
			const parsed = JSON.parse(raw) as StoredConversation[];
			if (!Array.isArray(parsed)) { return; }
			const existingIds = new Set(this.conversations.map(c => c.conversationId));
			for (const conv of parsed) {
				if (!existingIds.has(conv.conversationId)) {
					this.conversations.push(conv);
				}
			}
		} catch { }
	}

	private async saveToGlobalState(): Promise<void> {
		try {
			if (this.conversations.length > MAX_CONVERSATIONS) {
				this.conversations.sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt));
				this.conversations = this.conversations.slice(0, MAX_CONVERSATIONS);
			}
			await this.context.globalState.update(GLOBAL_STATE_KEY, this.conversations);
			if (this.lastSessionId) {
				await this.context.globalState.update(LAST_SESSION_KEY, this.lastSessionId);
			}
		} catch { }
	}

	private saveToFile(): void {
		try {
			ensureDir(LOCAL_FILE);
			fs.writeFileSync(LOCAL_FILE, JSON.stringify(this.conversations, null, 2), 'utf8');
		} catch { }
	}

	private async persist(): Promise<void> {
		await this.saveToGlobalState();
		this.saveToFile();
	}

	public getLastSessionId(): string | undefined {
		return this.lastSessionId;
	}

	public setLastSessionId(id: string): void {
		this.lastSessionId = id;
		void this.persist();
	}

	public getConversations(): StoredConversation[] {
		return [...this.conversations].sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt));
	}

	public getConversation(id: string): StoredConversation | undefined {
		return this.conversations.find(c => c.conversationId === id);
	}

	public getOrCreateConversation(conversationId: string, firstText?: string): StoredConversation {
		let conv = this.getConversation(conversationId);
		if (!conv) {
			conv = {
				conversationId,
				title: firstText ? generateTitle(firstText) : 'New Conversation',
				lastMessageAt: nowIso(),
				messages: []
			};
			this.conversations.push(conv);
		}
		this.lastSessionId = conversationId;
		return conv;
	}

	public async addMessage(conversationId: string, role: 'user' | 'assistant', text: string): Promise<void> {
		if (!text.trim()) { return; }
		const conv = this.getOrCreateConversation(conversationId, role === 'user' ? text : undefined);
		if (conv.messages.length === 0 && role === 'user') {
			conv.title = generateTitle(text);
		}
		conv.messages.push({
			role,
			text: text.slice(0, 10000),
			timestamp: nowIso()
		});
		if (conv.messages.length > MAX_MESSAGES_PER_CONVERSATION) {
			conv.messages = conv.messages.slice(-MAX_MESSAGES_PER_CONVERSATION);
		}
		conv.lastMessageAt = nowIso();
		this.lastSessionId = conversationId;
		await this.persist();
	}

	public async clear(): Promise<void> {
		this.conversations = [];
		this.lastSessionId = undefined;
		await this.persist();
	}

	public getFilePath(): string {
		return LOCAL_FILE;
	}
}

export function createTitlePreview(text: string, maxLen = 100): string {
	const singleLine = text.replace(/\s+/g, ' ').trim();
	if (singleLine.length <= maxLen) { return singleLine; }
	return singleLine.slice(0, maxLen - 3) + '...';
}
