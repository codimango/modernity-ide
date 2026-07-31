/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerMainProcessRemoteService } from '../../ipc/electron-browser/services.js';
import { IModernityProjectService, MODERNITY_PROJECT_CHANNEL } from '../common/modernityProject.js';

registerMainProcessRemoteService(IModernityProjectService, MODERNITY_PROJECT_CHANNEL);
