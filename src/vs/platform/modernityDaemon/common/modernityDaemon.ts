/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { join } from '../../../base/common/path.js';
import { createDecorator } from '../../instantiation/common/instantiation.js';

export const MODERNITY_LEGACY_DAEMON_RUNTIME_FILE = '/tmp/modernity-workspace/daemon.json';

export function modernityDaemonRuntimeFileCandidates(
	userDataPath: string,
	configuredRuntimeFile?: string,
): readonly string[] {
	return Array.from(new Set([
		...(configuredRuntimeFile ? [configuredRuntimeFile] : []),
		join(userDataPath, 'daemon.json'),
		MODERNITY_LEGACY_DAEMON_RUNTIME_FILE,
	]));
}

export type ModernityTemplateMode = 'local' | 'remote';

export interface IModernityDaemonConnection {
	readonly host: string;
	readonly port: number;
	readonly token: string;
	readonly runtimeFile: string;
}

export const IModernityDaemonService = createDecorator<IModernityDaemonService>('modernityDaemonService');

export interface IModernityDaemonService {
	readonly _serviceBrand: undefined;

	ensureRunning(): Promise<IModernityDaemonConnection>;
}
