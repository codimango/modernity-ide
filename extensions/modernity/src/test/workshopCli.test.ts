/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as assert from 'assert';
import { suite, test } from 'mocha';
import { workshopCommandFailureDetail } from '../workshopCli';

suite('Modernity Workshop CLI', () => {
	test('surfaces diagnostics from failed commands before interpreting their payload', () => {
		assert.deepStrictEqual([
			workshopCommandFailureDetail(
				{ exitCode: 1, stdout: '', stderr: 'docker fallback' },
				{ status: 'fail', error: '  image resolution failed  ' },
			),
			workshopCommandFailureDetail(
				{ exitCode: 1, stdout: '', stderr: '  docker inspect returned 1  ' },
				{ status: 'fail' },
			),
			workshopCommandFailureDetail(
				{ exitCode: 1, stdout: '', stderr: '' },
				{ status: 'fail', gradeable: false },
			),
			workshopCommandFailureDetail(
				{ exitCode: 0, stdout: '', stderr: 'ignored warning' },
				{ status: 'ok' },
			),
		], [
			'image resolution failed',
			'docker inspect returned 1',
			undefined,
			undefined,
		]);
	});
});
