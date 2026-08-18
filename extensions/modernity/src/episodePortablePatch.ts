/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createHash } from 'crypto';

export interface IPortablePatch {
	readonly commit_sha: string;
	readonly patch_sha256: string;
	readonly patch_bytes: number;
	readonly content?: string;
	readonly content_omitted_reason?: 'size_limit' | 'suspected_secret';
}

/** Package an ASCII Git binary patch without blindly exporting likely credentials. */
export function createPortablePatch(commitSha: string, patch: string, contentLimit: number): IPortablePatch {
	const patchBytes = Buffer.byteLength(patch, 'utf8');
	const shared = {
		commit_sha: commitSha,
		patch_sha256: createHash('sha256').update(patch).digest('hex'),
		patch_bytes: patchBytes,
	};
	if (containsPotentialSecret(patch)) {
		return { ...shared, content_omitted_reason: 'suspected_secret' };
	}
	if (patchBytes > contentLimit) {
		return { ...shared, content_omitted_reason: 'size_limit' };
	}
	return { ...shared, content: patch };
}

function containsPotentialSecret(patch: string): boolean {
	return /(?:authorization\s*:\s*bearer\s+|github_pat_|gh[pousr]_|api[_-]?key\s*[=:]|access[_-]?token\s*[=:]|password\s*[=:]|private[_-]?key\s*[=:])/i.test(patch);
}
