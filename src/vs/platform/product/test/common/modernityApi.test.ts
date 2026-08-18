/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../base/test/common/utils.js';
import { resolveModernityApiBaseUrl } from '../../common/modernityApi.js';

suite('Modernity API configuration', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('normalizes configured URLs and provides the development fallback', () => {
		assert.deepStrictEqual([
			resolveModernityApiBaseUrl(' https://api.modernity.test/// '),
			resolveModernityApiBaseUrl(''),
			resolveModernityApiBaseUrl(undefined),
		], [
			'https://api.modernity.test',
			'http://127.0.0.1:8000',
			'http://127.0.0.1:8000',
		]);
	});
});
