/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as fs from 'fs';
import * as http from 'http';
import * as os from 'os';
import * as path from 'path';
import { AddressInfo } from 'net';
import { afterEach, describe, expect, it } from 'vitest';
import { DefaultsOnlyConfigurationService } from '../../../../platform/configuration/common/defaultsOnlyConfigurationService';
import { IVSCodeExtensionContext } from '../../../../platform/extContext/common/extensionContext';
import { URI } from '../../../../util/vs/base/common/uri';
import { DaemonTraceEventOutbox } from '../daemonTraceEventOutbox';

const SESSION_ID = '095baf79-0e1b-4c71-b698-67e8167291ce';

describe('DaemonTraceEventOutbox', () => {
	const originalRuntime = process.env.MODERNITY_DAEMON_FILE;

	afterEach(() => {
		if (originalRuntime === undefined) {
			delete process.env.MODERNITY_DAEMON_FILE;
		} else {
			process.env.MODERNITY_DAEMON_FILE = originalRuntime;
		}
	});

	it('checkpoints acknowledged transcript entries and rescans replacements', async () => {
		const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'modernity-trace-'));
		const received: { authorization: string | undefined; eventIds: readonly string[] }[] = [];
		const server = http.createServer((request, response) => {
			const chunks: Buffer[] = [];
			request.on('data', chunk => chunks.push(Buffer.from(chunk)));
			request.on('end', () => {
				const body = JSON.parse(Buffer.concat(chunks).toString('utf8')) as { events: readonly { event_id: string }[] };
				const eventIds = body.events.map(event => event.event_id);
				received.push({ authorization: request.headers.authorization, eventIds });
				response.writeHead(200, { 'Content-Type': 'application/json' });
				response.end(JSON.stringify({ accepted: eventIds, duplicates: [] }));
			});
		});
		await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
		try {
			const port = (server.address() as AddressInfo).port;
			const runtimePath = path.join(root, 'daemon.json');
			await fs.promises.writeFile(runtimePath, JSON.stringify({ host: '127.0.0.1', port, token: 'local-token' }));
			process.env.MODERNITY_DAEMON_FILE = runtimePath;
			const transcriptPath = path.join(root, `${SESSION_ID}.jsonl`);
			await fs.promises.writeFile(transcriptPath, transcriptLine('10000000-0000-4000-8000-000000000001', 'first'));
			const context = { globalStorageUri: URI.file(path.join(root, 'global')) } as IVSCodeExtensionContext;
			const outbox = new DaemonTraceEventOutbox(context, new DefaultsOnlyConfigurationService());

			await outbox.recoverTranscript(SESSION_ID, URI.file(transcriptPath));
			await outbox.recoverTranscript(SESSION_ID, URI.file(transcriptPath));
			await fs.promises.writeFile(transcriptPath, transcriptLine('10000000-0000-4000-8000-000000000002', 'replacement'));
			await outbox.recoverTranscript(SESSION_ID, URI.file(transcriptPath));

			const checkpoint = JSON.parse(await fs.promises.readFile(path.join(root, 'global', 'modernity.trace', 'transcript-checkpoints', `${SESSION_ID}.json`), 'utf8')) as { generation: number; byteOffset: number };
			expect({ received, checkpoint: { generation: checkpoint.generation, byteOffset: checkpoint.byteOffset } }).toEqual({
				received: [
					{ authorization: 'Bearer local-token', eventIds: ['10000000-0000-4000-8000-000000000001'] },
					{ authorization: 'Bearer local-token', eventIds: ['10000000-0000-4000-8000-000000000002'] },
				],
				checkpoint: { generation: 2, byteOffset: Buffer.byteLength(transcriptLine('10000000-0000-4000-8000-000000000002', 'replacement')) },
			});
		} finally {
			await new Promise<void>(resolve => server.close(() => resolve()));
			await fs.promises.rm(root, { recursive: true, force: true });
		}
	});
});

function transcriptLine(id: string, producer: string): string {
	return JSON.stringify({
		type: 'session.start',
		id,
		timestamp: '2026-07-27T12:00:00.000Z',
		parentId: null,
		data: {
			sessionId: SESSION_ID,
			version: 1,
			producer,
			copilotVersion: '1',
			vscodeVersion: '1',
			startTime: '2026-07-27T12:00:00.000Z',
		},
	}) + '\n';
}
