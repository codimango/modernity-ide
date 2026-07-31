/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../base/common/event.js';
import { InstantiationType, registerSingleton } from '../../instantiation/common/extensions.js';
import { IModernityCheckoutProjectRequest, IModernityCreateProjectRequest, IModernityCreateProjectResult, IModernityProjectService, IModernityProjectSummary } from '../common/modernityProject.js';

class BrowserModernityProjectService implements IModernityProjectService {
	declare readonly _serviceBrand: undefined;

	readonly onDidChangeProvisionProgress = Event.None;

	async listProjects(): Promise<readonly IModernityProjectSummary[]> {
		return [];
	}

	async createProject(_request: IModernityCreateProjectRequest): Promise<IModernityCreateProjectResult> {
		throw new Error('Modernity project creation is available in the desktop application.');
	}

	async checkoutProject(_request: IModernityCheckoutProjectRequest): Promise<IModernityCreateProjectResult> {
		throw new Error('Modernity project checkout is available in the desktop application.');
	}
}

registerSingleton(IModernityProjectService, BrowserModernityProjectService, InstantiationType.Delayed);
