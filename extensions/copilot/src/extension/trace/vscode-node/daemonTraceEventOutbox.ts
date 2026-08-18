/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createHash } from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { IConfigurationService } from '../../../platform/configuration/common/configurationService';
import { IVSCodeExtensionContext } from '../../../platform/extContext/common/extensionContext';
import { CanonicalTraceEventV1, IRecoverableTraceEventOutbox, mapTranscriptEntryToTraceEvent } from '../../../platform/trace/common/trace';
import { URI } from '../../../util/vs/base/common/uri';
import type { TranscriptEntry } from '../../../platform/chat/common/sessionTranscriptService';
import { activateModernityEpisodeProvider, isModernityBenchmarkEpisode } from './modernityEpisodeTrace';

const MAX_BATCH_EVENTS = 100;
const MAX_BATCH_BYTES = 1024 * 1024;
const MAX_SCAN_BYTES = 4 * 1024 * 1024;
const DIGEST_BYTES = 4 * 1024;
const REQUEST_TIMEOUT_MS = 3000;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface IDaemonRuntime {
	readonly host: string;
	readonly port: number;
	readonly token: string;
}

interface ITraceCheckpoint {
	readonly version: 1;
	readonly sessionId: string;
	readonly generation: number;
	readonly byteOffset: number;
	readonly sourceSequence: number;
	readonly prefixDigest: string;
	readonly prefixBytes: number;
}

interface IEnqueueResponse {
	readonly accepted: readonly string[];
	readonly duplicates: readonly string[];
}

export class DaemonTraceEventOutbox implements IRecoverableTraceEventOutbox {
	declare readonly _serviceBrand: undefined;

	private readonly _checkpointDirectory: string;
	private readonly _recoveries = new Map<string, Promise<void>>();

	constructor(
		@IVSCodeExtensionContext extensionContext: IVSCodeExtensionContext,
		@IConfigurationService private readonly _configurationService: IConfigurationService,
	) {
		this._checkpointDirectory = path.join(extensionContext.globalStorageUri.fsPath, 'modernity.trace', 'transcript-checkpoints');
	}

	async enqueue(event: CanonicalTraceEventV1): Promise<'enqueued' | 'duplicate'> {
		const response = await this._enqueueBatch([event]);
		if (response.accepted.includes(event.event_id)) {
			return 'enqueued';
		}
		if (response.duplicates.includes(event.event_id)) {
			return 'duplicate';
		}
		throw new Error('daemon did not account for trace event');
	}

	recoverTranscript(sessionId: string, transcriptUri: URI): Promise<void> {
		const previous = this._recoveries.get(sessionId) ?? Promise.resolve();
		const recovery = previous.then(
			() => this._recoverTranscript(sessionId, transcriptUri.fsPath),
			() => this._recoverTranscript(sessionId, transcriptUri.fsPath),
		).finally(() => {
			if (this._recoveries.get(sessionId) === recovery) {
				this._recoveries.delete(sessionId);
			}
		});
		this._recoveries.set(sessionId, recovery);
		return recovery;
	}

	private async _recoverTranscript(sessionId: string, transcriptPath: string): Promise<void> {
		if (!UUID_PATTERN.test(sessionId)) {
			return;
		}
		await activateModernityEpisodeProvider(this._configurationService);
		const handle = await fs.promises.open(transcriptPath, 'r');
		try {
			const stat = await handle.stat();
			const checkpoint = await this._readCheckpoint(sessionId);
			const identity = await this._resolveIdentity(handle, stat.size, checkpoint);
			const available = Math.min(MAX_SCAN_BYTES, Math.max(0, stat.size - identity.byteOffset));
			if (available === 0) {
				return;
			}
			const buffer = Buffer.alloc(available);
			const { bytesRead } = await handle.read(buffer, 0, available, identity.byteOffset);
			const completeBytes = lastCompleteLineOffset(buffer.subarray(0, bytesRead));
			if (completeBytes === 0) {
				return;
			}

			let sourceSequence = identity.sourceSequence;
			const events: CanonicalTraceEventV1[] = [];
			for (const line of buffer.subarray(0, completeBytes).toString('utf8').split('\n')) {
				if (!line) {
					continue;
				}
				sourceSequence++;
				const entry = JSON.parse(line) as TranscriptEntry;
				const event = mapTranscriptEntryToTraceEvent(sessionId, entry, sourceSequence, {
					includeVisibleContent: isModernityBenchmarkEpisode(this._configurationService, sessionId),
				});
				if (event) {
					events.push(event);
				}
			}
			await this._enqueueBounded(events);

			const nextOffset = identity.byteOffset + completeBytes;
			const prefixBytes = Math.min(DIGEST_BYTES, stat.size);
			const prefixDigest = await digestPrefix(handle, prefixBytes);
			await this._writeCheckpoint({
				version: 1,
				sessionId,
				generation: identity.generation,
				byteOffset: nextOffset,
				sourceSequence,
				prefixDigest,
				prefixBytes,
			});
		} finally {
			await handle.close();
		}
	}

	private async _resolveIdentity(handle: fs.promises.FileHandle, size: number, checkpoint: ITraceCheckpoint | undefined): Promise<{ byteOffset: number; sourceSequence: number; generation: number }> {
		if (checkpoint && checkpoint.byteOffset <= size && checkpoint.prefixBytes <= size) {
			const digest = await digestPrefix(handle, checkpoint.prefixBytes);
			if (digest === checkpoint.prefixDigest) {
				return {
					byteOffset: checkpoint.byteOffset,
					sourceSequence: checkpoint.sourceSequence,
					generation: checkpoint.generation,
				};
			}
		}
		return { byteOffset: 0, sourceSequence: 0, generation: (checkpoint?.generation ?? 0) + 1 };
	}

	private async _enqueueBounded(events: readonly CanonicalTraceEventV1[]): Promise<void> {
		let batch: CanonicalTraceEventV1[] = [];
		let batchBytes = 32;
		for (const event of events) {
			const eventBytes = Buffer.byteLength(JSON.stringify(event), 'utf8') + 1;
			if (batch.length > 0 && (batch.length >= MAX_BATCH_EVENTS || batchBytes + eventBytes > MAX_BATCH_BYTES)) {
				await this._enqueueBatch(batch);
				batch = [];
				batchBytes = 32;
			}
			batch.push(event);
			batchBytes += eventBytes;
		}
		if (batch.length > 0) {
			await this._enqueueBatch(batch);
		}
	}

	private async _enqueueBatch(events: readonly CanonicalTraceEventV1[]): Promise<IEnqueueResponse> {
		const runtime = await readDaemonRuntime();
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
		try {
			const response = await fetch(`http://${runtime.host}:${runtime.port}/v1/traces/events:enqueue`, {
				method: 'POST',
				headers: {
					'Authorization': `Bearer ${runtime.token}`,
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({ events }),
				signal: controller.signal,
			});
			if (!response.ok) {
				throw new Error(`daemon trace enqueue returned HTTP ${response.status}`);
			}
			const value = await response.json() as Partial<IEnqueueResponse>;
			if (!Array.isArray(value.accepted) || !Array.isArray(value.duplicates)) {
				throw new Error('daemon trace enqueue returned an invalid response');
			}
			return { accepted: value.accepted, duplicates: value.duplicates };
		} finally {
			clearTimeout(timer);
		}
	}

	private async _readCheckpoint(sessionId: string): Promise<ITraceCheckpoint | undefined> {
		try {
			const raw = await fs.promises.readFile(this._checkpointPath(sessionId), 'utf8');
			const value = JSON.parse(raw) as ITraceCheckpoint;
			return value.version === 1 && value.sessionId === sessionId ? value : undefined;
		} catch {
			return undefined;
		}
	}

	private async _writeCheckpoint(checkpoint: ITraceCheckpoint): Promise<void> {
		await fs.promises.mkdir(this._checkpointDirectory, { recursive: true, mode: 0o700 });
		const destination = this._checkpointPath(checkpoint.sessionId);
		const temporary = `${destination}.${process.pid}.${Date.now()}.tmp`;
		try {
			await fs.promises.writeFile(temporary, JSON.stringify(checkpoint), { encoding: 'utf8', mode: 0o600 });
			await fs.promises.rename(temporary, destination);
		} finally {
			await fs.promises.unlink(temporary).catch(() => { });
		}
	}

	private _checkpointPath(sessionId: string): string {
		return path.join(this._checkpointDirectory, `${sessionId}.json`);
	}
}

async function readDaemonRuntime(): Promise<IDaemonRuntime> {
	let lastError: Error | undefined;
	for (const candidate of daemonRuntimeCandidates()) {
		try {
			const value = JSON.parse(await fs.promises.readFile(candidate, 'utf8')) as Partial<IDaemonRuntime>;
			if (typeof value.host !== 'string' || typeof value.port !== 'number' || typeof value.token !== 'string') {
				throw new Error('daemon runtime file is invalid');
			}
			return { host: value.host, port: value.port, token: value.token };
		} catch (error) {
			lastError = error instanceof Error ? error : new Error(String(error));
		}
	}
	throw new Error(`daemon runtime is unavailable: ${lastError?.message ?? 'not found'}`);
}

function daemonRuntimeCandidates(): readonly string[] {
	const override = process.env.MODERNITY_DAEMON_FILE;
	const primary = '/tmp/modernity-workspace/daemon.json';
	if (override) {
		return [override];
	}
	if (process.platform === 'darwin') {
		return [primary, path.join(os.homedir(), 'Library', 'Application Support', 'Modernity', 'daemon.json')];
	}
	if (process.platform === 'win32') {
		return [primary, path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'), 'Modernity', 'daemon.json')];
	}
	return [primary, path.join(process.env.XDG_STATE_HOME ?? path.join(os.homedir(), '.local', 'state'), 'modernity', 'daemon.json')];
}

async function digestPrefix(handle: fs.promises.FileHandle, bytes: number): Promise<string> {
	const buffer = Buffer.alloc(bytes);
	const { bytesRead } = await handle.read(buffer, 0, bytes, 0);
	return createHash('sha256').update(buffer.subarray(0, bytesRead)).digest('hex');
}

function lastCompleteLineOffset(buffer: Buffer): number {
	const index = buffer.lastIndexOf(0x0A);
	return index < 0 ? 0 : index + 1;
}
