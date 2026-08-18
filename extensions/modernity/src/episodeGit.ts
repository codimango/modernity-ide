/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

/** Build a refspec that can only publish HEAD to the same-named branch. */
export function sameNamedBranchPushRefspec(branch: string): string {
	return `HEAD:refs/heads/${branch}`;
}

/** Return whether two canonical filesystem paths identify the same repository root. */
export function isSelectedRepositoryRoot(selectedRealPath: string, repositoryRealPath: string): boolean {
	return selectedRealPath === repositoryRealPath;
}
