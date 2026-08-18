/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { ChildProcess, spawn } from 'child_process';
import { closeSync, openSync } from 'fs';
import { CancellationToken } from '../../../base/common/cancellation.js';
import { Disposable } from '../../../base/common/lifecycle.js';
import { isAbsolute, join, resolve } from '../../../base/common/path.js';
import { URI } from '../../../base/common/uri.js';
import { IEnvironmentMainService } from '../../environment/electron-main/environmentMainService.js';
import { IFileService } from '../../files/common/files.js';
import { ILogService } from '../../log/common/log.js';
import { resolveModernityApiBaseUrl } from '../../product/common/modernityApi.js';
import { IProductService } from '../../product/common/productService.js';
import { asText, IRequestService } from '../../request/common/request.js';
import {
	IModernityDaemonConnection,
	IModernityDaemonService,
	modernityDaemonRuntimeFileCandidates,
	ModernityTemplateMode,
} from '../common/modernityDaemon.js';

const START_TIMEOUT_MS = 10_000;
const HEALTH_TIMEOUT_MS = 2_000;

interface DaemonRuntimeFile {
	readonly host: string;
	readonly port: number;
	readonly token: string;
}

interface DaemonHealthResponse {
	readonly template_mode: ModernityTemplateMode;
	readonly control_plane_url: string | null;
	readonly trace_ingestion_url: string | null;
}

export class ModernityDaemonMainService extends Disposable implements IModernityDaemonService {
	declare readonly _serviceBrand: undefined;

	private ensureOperation: Promise<IModernityDaemonConnection> | undefined;
	private childProcess: ChildProcess | undefined;

	constructor(
		@IEnvironmentMainService private readonly environmentService: IEnvironmentMainService,
		@IFileService private readonly fileService: IFileService,
		@ILogService private readonly logService: ILogService,
		@IProductService private readonly productService: IProductService,
		@IRequestService private readonly requestService: IRequestService,
	) {
		super();
	}

	ensureRunning(): Promise<IModernityDaemonConnection> {
		if (!this.ensureOperation) {
			this.ensureOperation = this.doEnsureRunning().then(
				connection => {
					this.ensureOperation = undefined;
					return connection;
				},
				error => {
					this.ensureOperation = undefined;
					throw error;
				},
			);
		}
		return this.ensureOperation;
	}

	private async doEnsureRunning(): Promise<IModernityDaemonConnection> {
		for (const runtimeFile of this.runtimeFileCandidates()) {
			const connection = await this.healthyConnection(runtimeFile);
			if (connection) {
				return connection;
			}
		}

		const executable = await this.daemonExecutable();
		const runtimeFile = this.defaultRuntimeFile();
		const workspaceRoot = join(this.environmentService.userDataPath, 'workspaces');
		const templateCacheRoot = join(this.environmentService.userDataPath, 'templates');
		const logFile = join(this.environmentService.userDataPath, 'daemon.log');
		const templateMode = this.templateMode();
		const apiBaseUrl = resolveModernityApiBaseUrl(this.productService.modernityApiBaseUrl);
		const controlPlaneUrl = this.controlPlaneUrl(templateMode);
		await this.fileService.createFolder(URI.file(this.environmentService.userDataPath));

		const daemonArguments = [
			'daemon',
			'start',
			'--foreground',
			'--host',
			'127.0.0.1',
			'--port',
			'0',
			'--workspace-root',
			workspaceRoot,
			'--runtime-file',
			runtimeFile,
			'--template-mode',
			templateMode,
			'--template-cache-root',
			templateCacheRoot,
			'--trace-ingestion-url',
			apiBaseUrl,
		];
		if (controlPlaneUrl) {
			daemonArguments.push('--control-plane-url', controlPlaneUrl);
		}

		const logDescriptor = openSync(logFile, 'a');
		try {
			this.childProcess = spawn(executable, daemonArguments, {
				cwd: this.environmentService.appRoot,
				env: {
					...process.env,
					GRADLE_OPTS: this.gradleOptions(),
				},
				stdio: ['ignore', logDescriptor, logDescriptor],
			});
		} finally {
			closeSync(logDescriptor);
		}
		const child = this.childProcess;
		child.once('exit', (code, signal) => {
			if (this.childProcess === child) {
				this.childProcess = undefined;
			}
			this.logService.info(`[Modernity Daemon] Process exited with code ${code ?? 'none'} and signal ${signal ?? 'none'}.`);
		});
		child.once('error', error => {
			this.logService.error('[Modernity Daemon] Process launch failed.', error);
		});

		const deadline = Date.now() + START_TIMEOUT_MS;
		while (Date.now() < deadline) {
			const connection = await this.healthyConnection(runtimeFile);
			if (connection) {
				return connection;
			}
			if (child.exitCode !== null) {
				throw new Error(`The Modernity daemon exited before becoming ready. See ${logFile}.`);
			}
			await timeout(100);
		}
		throw new Error(`The Modernity daemon did not become ready. See ${logFile}.`);
	}

	private runtimeFileCandidates(): readonly string[] {
		return modernityDaemonRuntimeFileCandidates(
			this.environmentService.userDataPath,
			process.env['MODERNITY_DAEMON_FILE'],
		);
	}

	private defaultRuntimeFile(): string {
		return join(this.environmentService.userDataPath, 'daemon.json');
	}

	private async daemonExecutable(): Promise<string> {
		const configured = process.env['MODERNITY_DAEMON_EXECUTABLE']
			?? this.productService.modernityDaemonExecutable;
		if (!configured) {
			throw new Error('The Modernity daemon executable is not configured.');
		}
		const executable = isAbsolute(configured)
			? configured
			: resolve(this.environmentService.appRoot, configured);
		if (!await this.fileService.exists(URI.file(executable))) {
			throw new Error(`The Modernity daemon executable was not found at ${executable}.`);
		}
		return executable;
	}

	private templateMode(): ModernityTemplateMode {
		const configured = process.env['MODERNITY_TEMPLATE_MODE']
			?? this.productService.modernityTemplateMode
			?? 'remote';
		if (configured !== 'local' && configured !== 'remote') {
			throw new Error('MODERNITY_TEMPLATE_MODE must be local or remote.');
		}
		return configured;
	}

	private controlPlaneUrl(templateMode: ModernityTemplateMode): string | undefined {
		if (templateMode === 'local') {
			return undefined;
		}
		return resolveModernityApiBaseUrl(this.productService.modernityApiBaseUrl);
	}

	private gradleOptions(): string {
		const required = '-Djava.net.preferIPv4Stack=true';
		const configured = process.env['GRADLE_OPTS']?.trim();
		return configured
			? configured.includes(required) ? configured : `${configured} ${required}`
			: required;
	}

	private async healthyConnection(runtimeFile: string): Promise<IModernityDaemonConnection | undefined> {
		let runtimeValue: object | null;
		try {
			const content = await this.fileService.readFile(URI.file(runtimeFile));
			runtimeValue = JSON.parse(content.value.toString()) as object | null;
		} catch {
			return undefined;
		}
		if (!isDaemonRuntime(runtimeValue)) {
			return undefined;
		}
		const runtime = runtimeValue;
		let health: DaemonHealthResponse;
		try {
			const context = await this.requestService.request({
				type: 'GET',
				url: `http://${runtime.host}:${runtime.port}/v1/health`,
				headers: { Authorization: `Bearer ${runtime.token}` },
				disableCache: true,
				timeout: HEALTH_TIMEOUT_MS,
				callSite: 'modernityDaemon',
			}, CancellationToken.None);
			const responseBody = await asText(context) ?? '';
			const statusCode = context.res.statusCode ?? 0;
			if (statusCode < 200 || statusCode >= 300) {
				return undefined;
			}
			health = JSON.parse(responseBody) as DaemonHealthResponse;
		} catch {
			return undefined;
		}
		const expectedMode = this.templateMode();
		const expectedApiBaseUrl = resolveModernityApiBaseUrl(this.productService.modernityApiBaseUrl);
		const expectedControlPlaneUrl = this.controlPlaneUrl(expectedMode);
		if (
			health.template_mode !== expectedMode
			|| health.trace_ingestion_url?.replace(/\/+$/, '') !== expectedApiBaseUrl
			|| (expectedMode === 'remote'
				&& health.control_plane_url?.replace(/\/+$/, '') !== expectedControlPlaneUrl)
		) {
			if (!await this.shutdownDaemon(runtime)) {
				throw new Error('An incompatible Modernity daemon is running and could not be stopped.');
			}
			return undefined;
		}
		return { ...runtime, runtimeFile };
	}

	private async shutdownDaemon(runtime: DaemonRuntimeFile): Promise<boolean> {
		try {
			const context = await this.requestService.request({
				type: 'POST',
				url: `http://${runtime.host}:${runtime.port}/v1/shutdown`,
				headers: { Authorization: `Bearer ${runtime.token}` },
				data: '{}',
				disableCache: true,
				timeout: HEALTH_TIMEOUT_MS,
				callSite: 'modernityDaemon',
			}, CancellationToken.None);
			await asText(context);
			const statusCode = context.res.statusCode ?? 0;
			return statusCode >= 200 && statusCode < 300;
		} catch {
			return false;
		}
	}

	override dispose(): void {
		if (this.childProcess && this.childProcess.exitCode === null) {
			this.childProcess.kill();
		}
		this.childProcess = undefined;
		super.dispose();
	}
}

function isDaemonRuntime(value: object | null): value is DaemonRuntimeFile {
	if (!value) {
		return false;
	}
	const runtime = value as Partial<DaemonRuntimeFile>;
	return (runtime.host === '127.0.0.1' || runtime.host === 'localhost' || runtime.host === '::1')
		&& typeof runtime.port === 'number'
		&& Number.isInteger(runtime.port)
		&& runtime.port > 0
		&& runtime.port <= 65_535
		&& typeof runtime.token === 'string'
		&& runtime.token.length > 0;
}

function timeout(milliseconds: number): Promise<void> {
	return new Promise(resolveTimeout => setTimeout(resolveTimeout, milliseconds));
}
