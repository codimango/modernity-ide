/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { bufferToStream, VSBuffer } from '../../../../base/common/buffer.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { IRequestContext, IRequestOptions } from '../../../../base/parts/request/common/request.js';
import { NullLogService } from '../../../log/common/log.js';
import { IProductService } from '../../../product/common/productService.js';
import { AbstractRequestService, AuthInfo, Credentials } from '../../../request/common/request.js';
import { ModernityDaemonMainService } from '../../electron-main/modernityDaemonMainService.js';

class TestRequestService extends AbstractRequestService {
	readonly requests: IRequestOptions[] = [];

	constructor(private readonly health: object) {
		super(new NullLogService());
	}

	async request(options: IRequestOptions, _token: CancellationToken): Promise<IRequestContext> {
		this.requests.push(options);
		return {
			res: { statusCode: 200, headers: {} },
			stream: bufferToStream(VSBuffer.fromString(JSON.stringify(this.health))),
		};
	}

	async resolveProxy(): Promise<string | undefined> { return undefined; }
	async lookupAuthorization(_authInfo: AuthInfo): Promise<Credentials | undefined> { return undefined; }
	async lookupKerberosAuthorization(): Promise<string | undefined> { return undefined; }
	async loadCertificates(): Promise<string[]> { return []; }
}

suite('ModernityDaemonMainService', () => {
	const disposables = ensureNoDisposablesAreLeakedInTestSuite();

	test('reuses a healthy configuration-compatible daemon', async () => {
		const productService = {
			_serviceBrand: undefined,
			modernityApiBaseUrl: 'https://api.modernity.test',
			modernityTemplateMode: 'remote',
			modernityDaemonExecutable: '../modernity/bin/modernity',
		} as IProductService;
		const templateMode = process.env['MODERNITY_TEMPLATE_MODE'] ?? 'remote';
		const controlPlaneUrl = templateMode === 'remote'
			? productService.modernityApiBaseUrl
			: null;
		const requests = disposables.add(new TestRequestService({
			template_mode: templateMode,
			control_plane_url: controlPlaneUrl,
			trace_ingestion_url: productService.modernityApiBaseUrl,
		}));
		const fileService = {
			async readFile() {
				return {
					value: VSBuffer.fromString(JSON.stringify({
						host: '127.0.0.1',
						port: 43123,
						token: 'daemon-token',
					})),
				};
			},
			async exists() {
				throw new Error('A healthy daemon should not launch another process.');
			},
		};
		const service = disposables.add(new ModernityDaemonMainService(
			{ userDataPath: '/state', appRoot: '/app' } as never,
			fileService as never,
			new NullLogService(),
			productService,
			requests,
		));

		const connection = await service.ensureRunning();

		assert.deepStrictEqual({
			connection,
			request: {
				type: requests.requests[0].type,
				url: requests.requests[0].url,
				authorization: requests.requests[0].headers?.Authorization,
			},
		}, {
			connection: {
				host: '127.0.0.1',
				port: 43123,
				token: 'daemon-token',
				runtimeFile: process.env['MODERNITY_DAEMON_FILE'] ?? '/state/daemon.json',
			},
			request: {
				type: 'GET',
				url: 'http://127.0.0.1:43123/v1/health',
				authorization: 'Bearer daemon-token',
			},
		});
	});
});
