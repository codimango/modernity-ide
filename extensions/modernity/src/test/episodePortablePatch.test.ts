/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as assert from 'assert';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import { suite, test } from 'mocha';
import * as os from 'os';
import * as path from 'path';
import { isSelectedRepositoryRoot, sameNamedBranchPushRefspec } from '../episodeGit';
import { createPortablePatch } from '../episodePortablePatch';

suite('Modernity Episode Portable Patch', () => {
	test('includes bounded patches and omits oversized or suspicious content', () => {
		const safe = createPortablePatch('abcdef1', 'diff --git a/A.java b/A.java\n+mana++;\n', 1024);
		const oversized = createPortablePatch('abcdef2', 'x'.repeat(10), 4);
		const secret = createPortablePatch('abcdef3', '+api_key=super-secret-value\n', 1024);

		assert.deepStrictEqual({
			safeContent: safe.content,
			safeDigestLength: safe.patch_sha256.length,
			oversizedReason: oversized.content_omitted_reason,
			oversizedContent: oversized.content,
			secretReason: secret.content_omitted_reason,
			secretContent: secret.content,
		}, {
			safeContent: 'diff --git a/A.java b/A.java\n+mana++;\n',
			safeDigestLength: 64,
			oversizedReason: 'size_limit',
			oversizedContent: undefined,
			secretReason: 'suspected_secret',
			secretContent: undefined,
		});
	});

	test('pushes only the accepted feature branch', () => {
		assert.deepStrictEqual({
			acceptedRefspec: sameNamedBranchPushRefspec('modernity/episode/mana'),
			baselineRefspec: sameNamedBranchPushRefspec('modernity/episode/previous-feature'),
		}, {
			acceptedRefspec: 'HEAD:refs/heads/modernity/episode/mana',
			baselineRefspec: 'HEAD:refs/heads/modernity/episode/previous-feature',
		});
	});

	test('requires the selected folder to equal the repository root', () => {
		assert.deepStrictEqual({
			root: isSelectedRepositoryRoot('/workspace/mod', '/workspace/mod'),
			nested: isSelectedRepositoryRoot('/workspace/mod/src', '/workspace/mod'),
			parent: isSelectedRepositoryRoot('/workspace', '/workspace/mod'),
		}, {
			root: true,
			nested: false,
			parent: false,
		});
	});

	test('isolates a selected folder from its parent repository', () => {
		const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'modernity-nested-repository-'));
		try {
			const parent = path.join(temporaryRoot, 'parent');
			const selected = path.join(parent, 'minecraft-project');
			fs.mkdirSync(parent, { recursive: true });
			execFileSync('git', ['init', '-b', 'main', parent]);
			fs.mkdirSync(selected, { recursive: true });
			const inheritedRoot = execFileSync('git', ['-C', selected, 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();

			execFileSync('git', ['-C', selected, 'init', '-b', 'main']);
			const isolatedRoot = execFileSync('git', ['-C', selected, 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();

			assert.deepStrictEqual({
				inheritedMatches: isSelectedRepositoryRoot(fs.realpathSync(selected), fs.realpathSync(inheritedRoot)),
				isolatedMatches: isSelectedRepositoryRoot(fs.realpathSync(selected), fs.realpathSync(isolatedRoot)),
			}, {
				inheritedMatches: false,
				isolatedMatches: true,
			});
		} finally {
			fs.rmSync(temporaryRoot, { recursive: true, force: true });
		}
	});
});
