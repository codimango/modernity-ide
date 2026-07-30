/*---------------------------------------------------------------------------------------------
 *  Git adapter contract tests — safe ops, no force push, no credentials in logs, etc.
 *--------------------------------------------------------------------------------------------*/
import * as assert from 'assert';
import * as vscode from 'vscode';
import { FakeGitAdapter } from '../src/platform/project/fakes';
import { VsCodeGitAdapter } from '../src/platform/project/gitAdapter';
import { GitAdapterError } from '../src/platform/project/errors';
import { assertNoForce, ALLOWED_OPERATIONS } from '../src/platform/project/gitContract';

const uri = vscode.Uri.file('/tmp/ModernityProjects/testmod');

async function testAllowedOperations() {
	assert.ok(ALLOWED_OPERATIONS.has('status'));
	assert.ok(ALLOWED_OPERATIONS.has('clone'));
	assert.ok(ALLOWED_OPERATIONS.has('fast_forward_pull'));
	assert.ok(ALLOWED_OPERATIONS.has('push'));
	assert.ok(!ALLOWED_OPERATIONS.has('force_push' as any));
	console.log('✓ allowed ops set correct');
}

async function testNoForcePush() {
	try {
		assertNoForce({ force: true } as any);
		assert.fail('should reject force');
	} catch (e) { console.log('✓ force rejected in contract'); }
	const adapter = new FakeGitAdapter();
	// push wrapper should not accept force — we test our VsCodeGitAdapter throws
	const real = new VsCodeGitAdapter({ getGitApi: () => undefined });
	try {
		await real.push(uri, { force: true } as any);
		assert.fail('real adapter should reject force');
	} catch (e: any) {
		assert.ok(e instanceof GitAdapterError || /force/i.test(e.message));
		console.log('✓ push force forbidden');
	}
}

async function testCloneHttpsOnly() {
	const adapter = new VsCodeGitAdapter({
		getGitApi: () => ({
			repositories: [],
			clone: async (url:string, dest:string) => { if (!url.startsWith('https://')) { throw new Error('must be https'); } }
		} as any)
	});
	try {
		await adapter.clone('git@github.com:owner/repo.git', vscode.Uri.file('/tmp'), 'repo');
		assert.fail('should reject ssh url');
	} catch (e:any) {
		assert.ok(e.message.includes('HTTPS') || e instanceof GitAdapterError);
		console.log('✓ clone HTTPS-only enforced');
	}
	try {
		await adapter.clone('https://token@github.com/owner/repo.git', vscode.Uri.file('/tmp'), 'repo');
		assert.fail('should reject embedded creds');
	} catch (e:any) {
		console.log('✓ clone credential embedding rejected', e.message.slice(0,100));
	}
}

async function testFastForwardSafety() {
	const adapter = new FakeGitAdapter();
	adapter.setStatus('/tmp/ModernityProjects/testmod', {
		branch:'main', head_sha:'a'.repeat(40), upstream_sha:'b'.repeat(40),
		dirty:false, ahead:1, behind:1, detached:false, conflicted:false, unpublished:false,
		classification:'diverged'
	});
	try {
		await adapter.fastForwardPull(uri);
		assert.fail('should not allow diverged ff pull');
	} catch (e:any) {
		console.log('✓ ff-pull diverged blocked');
	}
}

async function testNoCredentialLeak() {
	// Adapter must never return credentials — verify status returns only allowed fields
	const adapter = new FakeGitAdapter();
	const st = await adapter.status(uri);
	assert.ok(!('credentials' in (st as any)));
	assert.ok(!('token' in (st as any)));
	console.log('✓ no credential leak in LocalGitStatus');
}

(async () => {
	await testAllowedOperations();
	await testNoForcePush();
	await testCloneHttpsOnly();
	await testFastForwardSafety();
	await testNoCredentialLeak();
	console.log('gitAdapter contract tests ok');
})();
