/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { IConfigurationService } from '../../../platform/configuration/common/configurationService';

const MODERNITY_EXTENSION_ID = 'modernity.modernity';

interface IModernityExtensionApi {
	isBenchmarkEpisodeSession(sessionId: string): boolean;
}

/** Activate the Modernity provider before transcript recovery needs its episode registry. */
export async function activateModernityEpisodeProvider(configurationService: IConfigurationService): Promise<void> {
	if (configurationService.getNonExtensionConfig<boolean>('modernity.benchmarkEpisodes.enabled') !== true) {
		return;
	}
	const extension = vscode.extensions?.getExtension<IModernityExtensionApi>(MODERNITY_EXTENSION_ID);
	if (extension && !extension.isActive) {
		await extension.activate();
	}
}

/** Return whether visible transcript content may be attached to this trace session. */
export function isModernityBenchmarkEpisode(configurationService: IConfigurationService, sessionId: string): boolean {
	if (configurationService.getNonExtensionConfig<boolean>('modernity.benchmarkEpisodes.enabled') !== true) {
		return false;
	}
	const extension = vscode.extensions?.getExtension<IModernityExtensionApi>(MODERNITY_EXTENSION_ID);
	return extension?.isActive === true && extension.exports?.isBenchmarkEpisodeSession(sessionId) === true;
}
