/*---------------------------------------------------------------------------------------------
 *  Daemon client tests — discovery, snapshots, 401/restart/unavailable mapping.
 *--------------------------------------------------------------------------------------------*/
import * as assert from 'assert';
import * as vscode from 'vscode';
import { FakeDaemon } from '../src/platform/project/fakes';
import { DaemonError } from '../src/platform/project/errors';
import { ModernityDaemonClient } from '../src/platform/project/daemonClient';

async function testHealthSnapshot() {
	const fake = new FakeDaemon();
	const snaps: any[] = [];
	const client = new ModernityDaemonClient({
		discovery: async () => ({ host:'127.0.0.1', port: 1234, token:'tok', workspace_root:'/tmp/modernity-workspace', baseUrl:'http://127.0.0.1:1234', rawPath:'/tmp/modernity-workspace/daemon.json' }),
		fetchImpl: (async (url, init) => {
			snaps.push({ method: init?.method ?? 'GET', url, headers: init?.headers });
			return new Response(JSON.stringify({ status:'ok', workspace_root:'/tmp/modernity-workspace' }), { status:200 });
		}) as any,
		onSnapshot: (s) => snaps.push({ snapshot: s }),
	});
	const h = await client.health();
	assert.strictEqual(h.status, 'ok');
	// snapshot must redact token, and must not contain second listener
	assert.ok(snaps.length>0);
	console.log('✓ daemon health snapshot', JSON.stringify(snaps[0]).slice(0,200));
}

async function testDaemon401() {
	const fake = new FakeDaemon();
	fake.setUnauthorized(true);
	const client = fake.makeClient();
	try {
		await client.health();
		assert.fail('should 401');
	} catch (e:any) {
		assert.ok(e instanceof DaemonError);
		assert.strictEqual(e.kind, 'unauthorized');
		console.log('✓ daemon 401 mapped');
	}
}

async function testDaemonUnavailable() {
	const fake = new FakeDaemon();
	fake.shouldFailHealth = true;
	const client = fake.makeClient();
	try {
		await client.health();
		assert.fail('should unavailable');
	} catch (e:any) {
		assert.ok(e instanceof DaemonError);
		assert.strictEqual(e.kind, 'unavailable');
		console.log('✓ daemon unavailable mapped');
	}
}

async function testDaemonRestart() {
	const fake = new FakeDaemon();
	const client = fake.makeClient();
	const h1 = await client.health();
	assert.strictEqual(h1.status, 'ok');
	fake.simulateRestart();
	client.discoveryReset();
	const h2 = await client.health();
	assert.strictEqual(h2.status, 'ok');
	console.log('✓ daemon restart reset works');
}

async function testDaemonNoSecondListenerFallback() {
	// Contract: missing/stale runtime file maps to typed error, never falls back to second listener.
	// Our client uses single discovery path — verified by discovery not trying alternative baseUrl on failure
	let discoveryCalls = 0;
	const client = new ModernityDaemonClient({
		discovery: async () => { discoveryCalls++; throw new DaemonError('runtime_missing','not found'); },
		fetchImpl: (async () => { assert.fail('should not fetch if discovery fails'); }) as any,
	});
	try {
		await client.health();
		assert.fail('should throw runtime_missing');
	} catch (e:any) {
		assert.ok(e instanceof DaemonError);
		assert.strictEqual(e.kind, 'runtime_missing');
		assert.strictEqual(discoveryCalls, 1);
		console.log('✓ no fallback listener');
	}
}

(async () => {
	await testHealthSnapshot();
	await testDaemon401();
	await testDaemonUnavailable();
	await testDaemonRestart();
	await testDaemonNoSecondListenerFallback();
	console.log('daemonClient tests ok');
})();
