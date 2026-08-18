/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

const DEFAULT_MODERNITY_API_BASE_URL = 'http://127.0.0.1:8000';

/** Returns the normalized API base URL used by Modernity services. */
export function resolveModernityApiBaseUrl(configuredBaseUrl: string | undefined): string {
	return (configuredBaseUrl?.trim() || DEFAULT_MODERNITY_API_BASE_URL).replace(/\/+$/, '');
}
