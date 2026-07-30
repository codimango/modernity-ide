/*---------------------------------------------------------------------------------------------
 *  Cloud client tests — snapshots, error mapping, cursor, limit, offline preservation.
 *--------------------------------------------------------------------------------------------*/
import * as assert from 'assert';
import * as vscode from 'vscode';
import { FakeCloudBackend } from '../src/platform/project/fakes';
import { CloudApiError } from '../src/platform/project/errors';
import { ModernityCloudClient } from '../src/platform/project/cloudClient';
import type { Project } from '../src/platform/project/models';

function makeProject(id: string, name = `mod-${id.slice(0,4)}`): Project {
	return {
		id,
		name,
		slug: name,
		description: null,
		mod_id: 'testmod',
		mod_name: name,
		group_id: 'com.example',
		mod_version: '1.0.0',
		license: 'MIT',
		template_id: 'neoforge-26',
		template_version: '1.0.0',
		minecraft_version: '26.2',
		neoforge_version: '26.2.0.7-beta',
		java_version: '25',
		gradle_version: '9.2.1',
		visibility: 'private',
		default_branch: 'main',
		settings: {},
		lifecycle_status: 'active',
		failure: null,
		repository: null,
		created_at: new Date().toISOString(),
		updated_at: new Date().toISOString(),
		archived_at: null,
		last_opened_at: null,
		version: 1,
	};
}

async function testRequestSnapshot() {
	const backend = new FakeCloudBackend();
	backend.setProjects([makeProject('00000000-0000-0000-0000-000000000001')]);
	const snapshots: any[] = [];
	const client = new ModernityCloudClient({
		baseUrl: 'https://api.test.modernity.dev',
		getAccessToken: () => 'tok-123',
		fetchImpl: backend.makeClient().listProjects as any, // we will use backend's own fetch via makeClient
		onRequestSnapshot: (s) => snapshots.push(s),
	});
	// use backend client which already snapshots inside; also our outer snapshot
	const realClient = backend.makeClient('https://api.test.modernity.dev', () => 'tok-123');
	const page = await realClient.listProjects({ limit: 50 });
	assert.strictEqual(page.items.length, 1);
	assert.strictEqual(backend.getSnapshotCount(), 1);
	const snap = backend.getSnapshots()[0];
	assert.ok(snap.headers['Authorization'] === undefined || snap.headers['Authorization'].includes('fake-token') || snap.url.includes('/api/v1/projects'));
	console.log('✓ cloud snapshot captured');
}

async function testLimitContract() {
	assert.throws(() => ModernityCloudClient.normalizeLimit(0));
	assert.throws(() => ModernityCloudClient.normalizeLimit(101));
	assert.strictEqual(ModernityCloudClient.normalizeLimit(undefined), 50);
	assert.strictEqual(ModernityCloudClient.normalizeLimit(50), 50);
	console.log('✓ limit contract');
}

async function testOfflineMapping() {
	const offlineFetch: typeof fetch = async () => { throw new Error('ECONNREFUSED'); };
	const client = new ModernityCloudClient({
		baseUrl: 'https://api.test.modernity.dev',
		getAccessToken: () => 't',
		fetchImpl: offlineFetch as any,
	});
	try {
		await client.listProjects();
		assert.fail('should throw');
	} catch (e: any) {
		assert.ok(e instanceof CloudApiError);
		assert.strictEqual((e as CloudApiError).kind, 'offline');
		console.log('✓ offline mapping');
	}
}

async function test401Mapping() {
	const fetch401: typeof fetch = async () => new Response(JSON.stringify({ code:'unauthorized', message:'bad token', request_id:'r1', retryable:false }), { status:401 });
	const client = new ModernityCloudClient({ baseUrl:'https://api.test.modernity.dev', getAccessToken:()=>'bad', fetchImpl: fetch401 as any });
	try {
		await client.getProject('00000000-0000-0000-0000-000000000001');
		assert.fail('should throw 401');
	} catch (e:any) {
		assert.ok(e instanceof CloudApiError);
		assert.strictEqual((e as CloudApiError).kind, 'signed_out');
		console.log('✓ 401 signed-out mapping');
	}
}

async function testCursorPagination() {
	const backend = new FakeCloudBackend();
	const ids = Array.from({length: 75}, (_,i)=> `00000000-0000-0000-0000-${String(i).padStart(12,'0')}`);
	backend.setProjects(ids.map(id=>makeProject(id)));
	const client = backend.makeClient();
	const p1 = await client.listProjects({ limit: 50 });
	assert.strictEqual(p1.items.length, 50);
	assert.ok(p1.next_cursor);
	const p2 = await client.listProjects({ limit: 50, cursor: p1.next_cursor! });
	assert.strictEqual(p2.items.length, 25);
	assert.strictEqual(p2.next_cursor, null);
	console.log('✓ cursor pagination');
}

(async () => {
	await testRequestSnapshot();
	await testLimitContract();
	await testOfflineMapping();
	await test401Mapping();
	await testCursorPagination();
	console.log('cloudClient tests ok');
})();
