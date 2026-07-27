/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { McpResourceURI, McpServerDefinition, McpServerTransportType } from '../../common/mcpTypes.js';
import * as assert from 'assert';
import { URI } from '../../../../../base/common/uri.js';
import { addModernityTraceMetadata } from '../../common/mcpServer.js';

suite('MCP Types', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('McpResourceURI - round trips', () => {
		const roundTrip = (uri: string) => {
			const from = McpResourceURI.fromServer({ label: '', id: 'my-id' }, uri);
			const to = McpResourceURI.toServer(from);
			assert.strictEqual(to.definitionId, 'my-id');
			assert.strictEqual(to.resourceURL.toString(), uri, `expected to round trip ${uri}`);
		};

		roundTrip('file:///path/to/file.txt');
		roundTrip('custom-scheme://my-path/to/resource.txt');
		roundTrip('custom-scheme://my-path');
		roundTrip('custom-scheme://my-path/');
		roundTrip('custom-scheme://my-path/?with=query&params=here');

		roundTrip('custom-scheme:///my-path');
		roundTrip('custom-scheme:///my-path/foo/?with=query&params=here');
	});

	test('Modernity trace context is added only to MCP metadata', () => {
		const meta: Record<string, unknown> = {
			progressToken: 'progress',
			'vscode.requestId': 'request',
			traceparent: '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01',
		};
		addModernityTraceMetadata(meta, {
			chatSessionResource: undefined,
			traceContext: {
				sessionId: '095baf79-0e1b-4c71-b698-67e8167291ce',
				turnId: '3',
				modelRequestId: '10000000-0000-4000-8000-000000000001',
				toolCallId: 'native-call',
				projectId: '20000000-0000-4000-8000-000000000001',
				checkoutId: '30000000-0000-4000-8000-000000000001',
				machineId: '40000000-0000-4000-8000-000000000001',
			},
		});

		assert.deepStrictEqual(meta, {
			progressToken: 'progress',
			'vscode.requestId': 'request',
			traceparent: '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01',
			'modernity/sessionId': '095baf79-0e1b-4c71-b698-67e8167291ce',
			'modernity/turnId': '3',
			'modernity/modelRequestId': '10000000-0000-4000-8000-000000000001',
			'modernity/toolCallId': 'native-call',
			'modernity/projectId': '20000000-0000-4000-8000-000000000001',
			'modernity/checkoutId': '30000000-0000-4000-8000-000000000001',
			'modernity/machineId': '40000000-0000-4000-8000-000000000001',
		});
	});

	suite('McpServerDefinition.equals', () => {
		const createBasicDefinition = (overrides?: Partial<McpServerDefinition>): McpServerDefinition => ({
			id: 'test-server',
			label: 'Test Server',
			cacheNonce: 'v1.0.0',
			launch: {
				type: McpServerTransportType.Stdio,
				cwd: undefined,
				command: 'test-command',
				args: [],
				env: {},
				envFile: undefined,
				sandbox: undefined
			},
			...overrides
		});

		test('returns true for identical definitions', () => {
			const def1 = createBasicDefinition();
			const def2 = createBasicDefinition();
			assert.strictEqual(McpServerDefinition.equals(def1, def2), true);
		});

		test('returns false when cacheNonce differs', () => {
			const def1 = createBasicDefinition({ cacheNonce: 'v1.0.0' });
			const def2 = createBasicDefinition({ cacheNonce: 'v2.0.0' });
			assert.strictEqual(McpServerDefinition.equals(def1, def2), false);
		});

		test('returns false when id differs', () => {
			const def1 = createBasicDefinition({ id: 'server-1' });
			const def2 = createBasicDefinition({ id: 'server-2' });
			assert.strictEqual(McpServerDefinition.equals(def1, def2), false);
		});

		test('returns false when label differs', () => {
			const def1 = createBasicDefinition({ label: 'Server A' });
			const def2 = createBasicDefinition({ label: 'Server B' });
			assert.strictEqual(McpServerDefinition.equals(def1, def2), false);
		});

		test('returns false when roots differ', () => {
			const def1 = createBasicDefinition({ roots: [URI.file('/path1')] });
			const def2 = createBasicDefinition({ roots: [URI.file('/path2')] });
			assert.strictEqual(McpServerDefinition.equals(def1, def2), false);
		});

		test('returns true when roots are both undefined', () => {
			const def1 = createBasicDefinition({ roots: undefined });
			const def2 = createBasicDefinition({ roots: undefined });
			assert.strictEqual(McpServerDefinition.equals(def1, def2), true);
		});

		test('returns false when launch differs', () => {
			const def1 = createBasicDefinition({
				launch: {
					type: McpServerTransportType.Stdio,
					cwd: undefined,
					command: 'command1',
					args: [],
					env: {},
					envFile: undefined,
					sandbox: undefined
				}
			});
			const def2 = createBasicDefinition({
				launch: {
					type: McpServerTransportType.Stdio,
					cwd: undefined,
					command: 'command2',
					args: [],
					env: {},
					envFile: undefined,
					sandbox: undefined
				}
			});
			assert.strictEqual(McpServerDefinition.equals(def1, def2), false);
		});
	});
});
