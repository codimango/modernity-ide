/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/
import path from 'path';
import { spawn } from 'child_process';
import { promises as fs } from 'fs';

const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const rootDir = path.resolve(import.meta.dirname, '..', '..');

function runProcess(command: string, args: ReadonlyArray<string> = []) {
	return new Promise<void>((resolve, reject) => {
		const child = spawn(command, args, { cwd: rootDir, stdio: 'inherit', env: process.env, shell: process.platform === 'win32' });
		child.on('exit', err => !err ? resolve() : process.exit(err ?? 1));
		child.on('error', reject);
	});
}

async function exists(subdir: string) {
	try {
		await fs.stat(path.join(rootDir, subdir));
		return true;
	} catch {
		return false;
	}
}

async function ensureNodeModules() {
	if (!(await exists('node_modules'))) {
		await runProcess(npm, ['ci']);
	}
}

async function getElectron() {
	// `npm run electron` deletes and re-downloads `.build/electron` on every
	// invocation. When preLaunch runs repeatedly (e.g. once per integration test
	// section) this is both wasteful and a source of flaky failures on Windows,
	// where the just-exited Electron process can still hold file locks while the
	// directory is being removed and re-extracted. Skip the refresh when the
	// already-present Electron matches the expected version; any detection
	// failure falls back to a (re)download to preserve the previous behavior.
	// Also skip if Modernity.app binary already exists - useful in Meta X2P
	// proxy env where direct GitHub downloads may EPERM without proxy.
	if (await isExpectedElectronInstalled()) {
		return;
	}
	try {
		await runProcess(npm, ['run', 'electron']);
	} catch (err) {
		// In Meta-managed macOS, GitHub fetches may fail with EPERM if fetch
		// doesn't respect http_proxy. If we already have a binary, keep it.
		const hasBinary = await exists('.build/electron/Modernity.app/Contents/MacOS/Modernity')
			|| await exists('.build/electron/Modernity.app/Contents/MacOS/Electron')
			|| await exists('node_modules/electron/dist/Electron.app/Contents/MacOS/Electron');
		if (hasBinary) {
			console.warn('[preLaunch] npm run electron failed (likely proxy EPERM), but existing Electron binary found - continuing with existing build');
			return;
		}
		throw err;
	}
}

async function isExpectedElectronInstalled(): Promise<boolean> {
	try {
		const { getElectronVersion } = await import('./util.ts');
		const { electronVersion } = getElectronVersion();
		const root = path.resolve(import.meta.dirname, '..', '..');
		// Check version file matches
		const versionPath = path.join(root, '.build', 'electron', 'version');
		const product = JSON.parse(await fs.readFile(path.join(root, 'product.json'), 'utf8'));
		const appName = product.nameLong;
		const binaryPath = path.join(root, '.build', 'electron', `${appName}.app`, 'Contents', 'MacOS', appName);
		const electronBinary = path.join(root, '.build', 'electron', `${appName}.app`, 'Contents', 'MacOS', 'Electron');
		// If version file missing but binary exists, consider it installed to avoid
		// re-download in proxy-restricted env (will be regenerated via make ide-electron if needed)
		try {
			const installedVersion = (await fs.readFile(versionPath, 'utf8')).trim().replace(/^v/, '');
			if (installedVersion === electronVersion) {
				return true;
			}
		} catch {
			// version file missing - check if binary exists as fallback
			if (await exists(`.build/electron/${appName}.app/Contents/MacOS/${appName}`) ||
				await exists(`.build/electron/${appName}.app/Contents/MacOS/Electron`)) {
				console.warn(`[preLaunch] version file missing but ${appName}.app binary exists - skipping electron download`);
				// Write version file to prevent future re-download attempts
				await fs.writeFile(versionPath, electronVersion, 'utf8').catch(() => {});
				return true;
			}
			return false;
		}
		return false;
	} catch {
		return false;
	}
}

async function ensureCompiled() {
	if (!(await exists('out'))) {
		await runProcess(npm, ['run', 'compile']);
	}
}

async function main() {
	await ensureNodeModules();
	await getElectron();
	await ensureCompiled();

	// Can't require this until after dependencies are installed
	const { getBuiltInExtensions } = await import('./builtInExtensions.ts');
	await getBuiltInExtensions();
}

if (import.meta.main) {
	main().catch(err => {
		console.error(err);
		process.exit(1);
	});
}
