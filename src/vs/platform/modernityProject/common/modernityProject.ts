/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../base/common/event.js';
import { createDecorator } from '../../instantiation/common/instantiation.js';

export const MODERNITY_PROJECT_CHANNEL = 'modernityProject';

export interface IModernityCreateProjectRequest {
	readonly name: string;
	readonly repositoryName: string;
	readonly destinationPath: string;
}

export interface IModernityCreateProjectResult {
	readonly projectId: string;
	readonly projectPath: string;
	readonly repositoryUrl: string;
	readonly commitSha: string;
}

export interface IModernityProjectSummary {
	readonly projectId: string;
	readonly name: string;
	readonly modId: string;
	readonly lifecycleStatus: string;
	readonly repositoryFullName: string | undefined;
	readonly checkoutPath: string | undefined;
}

export interface IModernityCheckoutProjectRequest {
	readonly projectId: string;
	readonly destinationPath: string;
}

export type ModernityProjectProvisionPhase =
	| 'machine'
	| 'project'
	| 'repository'
	| 'credential'
	| 'local'
	| 'checkout'
	| 'refresh'
	| 'complete';

export interface IModernityProjectProvisionProgress {
	readonly phase: ModernityProjectProvisionPhase;
	readonly message: string;
}

export const IModernityProjectService = createDecorator<IModernityProjectService>('modernityProjectService');

export interface IModernityProjectService {
	readonly _serviceBrand: undefined;

	readonly onDidChangeProvisionProgress: Event<IModernityProjectProvisionProgress>;

	listProjects(): Promise<readonly IModernityProjectSummary[]>;
	createProject(request: IModernityCreateProjectRequest): Promise<IModernityCreateProjectResult>;
	checkoutProject(request: IModernityCheckoutProjectRequest): Promise<IModernityCreateProjectResult>;
}
