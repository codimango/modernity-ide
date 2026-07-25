import * as path from 'node:path';
import { run } from '../esbuild-extension-common.mts';

const srcDir = path.join(import.meta.dirname, 'src');
const outDir = path.join(import.meta.dirname, 'dist', 'browser');

run({
	platform: 'browser',
	entryPoints: {
		'extension': path.join(srcDir, 'extension.ts'),
	},
	srcDir,
	outdir: outDir,
	additionalOptions: {
		// Node-only sandbox tooling is dynamically imported and guarded at runtime, but the
		// bundler still resolves the chunk, so keep Node builtins external for the browser build.
		external: ['vscode', 'child_process', 'net', 'fs', 'path', 'os'],
	},
}, process.argv);
