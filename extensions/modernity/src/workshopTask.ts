/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as fs from 'fs';
import * as path from 'path';

/**
 * Reads a Codimango task bundle emitted by `services.workshop.cli end`.
 *
 * The panel reads the emitted artifacts rather than the backend episodes API so
 * that it shows exactly what would be submitted. Only two files are required:
 * `instruction.md` and `.modernity/provenance.json`.
 */

export const MANIFEST_RELATIVE_PATH = path.join('.modernity', 'provenance.json');
export const INSTRUCTION_RELATIVE_PATH = 'instruction.md';
export const SUPPORTED_MANIFEST_SCHEMA = 1;

export interface WorkshopTaskMetadata {
	readonly authorName?: string;
	readonly difficulty?: string;
	readonly rewardType?: string;
	readonly taskFormat?: string;
	readonly workstream?: string;
	readonly categoryUsecase?: string;
	readonly categorySubdomain?: string;
}

export interface WorkshopTaskEnvironment {
	readonly toolchainMode?: string;
	readonly fromImage?: string;
	readonly minecraftVersion?: string;
	readonly neoforgeVersion?: string;
	readonly javaVersion?: string;
	readonly portable: boolean;
}

export interface WorkshopTaskProvenance {
	readonly generatedProse: boolean;
	readonly chars: number;
	readonly sources: readonly string[];
}

export interface WorkshopTaskBundle {
	readonly directory: string;
	readonly taskName: string;
	readonly instanceId?: string;
	readonly repository?: string;
	readonly baseCommit?: string;
	readonly finalCommit?: string;
	readonly defaultBranch?: string;
	readonly instruction: string;
	readonly metadata: WorkshopTaskMetadata;
	readonly environment: WorkshopTaskEnvironment;
	readonly provenance: WorkshopTaskProvenance;
	readonly failToPass: readonly string[];
	readonly passToPass: readonly string[];
	readonly blockers: readonly string[];
	readonly submittable: boolean;
}

export class WorkshopTaskError extends Error { }

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
	return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {};
}

function asText(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined;
}

function asList(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function asCount(value: unknown): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readMetadata(value: unknown): WorkshopTaskMetadata {
	const source = asRecord(value);
	return {
		authorName: asText(source.author_name),
		difficulty: asText(source.difficulty),
		rewardType: asText(source.reward_type),
		taskFormat: asText(source.task_format),
		workstream: asText(source.workstream),
		categoryUsecase: asText(source.category_usecase),
		categorySubdomain: asText(source.category_subdomain)
	};
}

function readEnvironment(value: unknown): WorkshopTaskEnvironment {
	const source = asRecord(value);
	return {
		toolchainMode: asText(source.toolchain_mode),
		fromImage: asText(source.from_image),
		minecraftVersion: asText(source.minecraft_version),
		neoforgeVersion: asText(source.neoforge_version),
		javaVersion: asText(source.java_version),
		// Absent means the bundle predates the field. Treat that as portable
		// rather than falsely flagging an older task as unsubmittable.
		portable: source.portable === undefined ? true : source.portable === true
	};
}

function readProvenance(value: unknown): WorkshopTaskProvenance {
	const source = asRecord(value);
	const blocks = Array.isArray(source.blocks) ? source.blocks : [];
	return {
		generatedProse: source.generated_prose === true,
		chars: asCount(source.chars),
		sources: blocks
			.map(block => asText(asRecord(block).source))
			.filter((item): item is string => item !== undefined)
	};
}

/** Parse a manifest and instruction that were already read from disk. */
export function parseTaskBundle(directory: string, manifestJson: string, instruction: string): WorkshopTaskBundle {
	let parsed: unknown;
	try {
		parsed = JSON.parse(manifestJson);
	} catch {
		throw new WorkshopTaskError('provenance.json is not valid JSON.');
	}
	const manifest = asRecord(parsed);
	const schema = manifest.schema_version;
	if (typeof schema === 'number' && schema > SUPPORTED_MANIFEST_SCHEMA) {
		throw new WorkshopTaskError(`This task uses manifest schema ${schema}, newer than this build supports.`);
	}
	const taskName = asText(manifest.task);
	if (!taskName) {
		throw new WorkshopTaskError('provenance.json is missing its task name.');
	}
	if (instruction.trim().length === 0) {
		throw new WorkshopTaskError('instruction.md is empty.');
	}
	const blockers = asList(manifest.blockers);
	return {
		directory,
		taskName,
		instanceId: asText(manifest.instance_id),
		repository: asText(manifest.repository),
		baseCommit: asText(manifest.base_commit),
		finalCommit: asText(manifest.final_commit),
		defaultBranch: asText(manifest.default_branch),
		instruction,
		metadata: readMetadata(manifest.metadata),
		environment: readEnvironment(manifest.environment),
		provenance: readProvenance(manifest.instruction_provenance),
		failToPass: asList(manifest.fail_to_pass),
		passToPass: asList(manifest.pass_to_pass),
		blockers,
		submittable: manifest.submittable === undefined ? blockers.length === 0 : manifest.submittable === true
	};
}

/** Read an emitted task directory from disk. */
export function readTaskBundle(directory: string): WorkshopTaskBundle {
	const manifestPath = path.join(directory, MANIFEST_RELATIVE_PATH);
	const instructionPath = path.join(directory, INSTRUCTION_RELATIVE_PATH);
	if (!fs.existsSync(manifestPath) || !fs.existsSync(instructionPath)) {
		throw new WorkshopTaskError(`${directory} is not an emitted task directory.`);
	}
	return parseTaskBundle(
		directory,
		fs.readFileSync(manifestPath, 'utf8'),
		fs.readFileSync(instructionPath, 'utf8')
	);
}

/**
 * Find the most recently emitted task directory under a root.
 *
 * `workshop end` writes one directory per task, so the newest by modification
 * time is the one the user just submitted.
 */
export function findLatestTaskDirectory(root: string): string | undefined {
	let entries: fs.Dirent[];
	try {
		entries = fs.readdirSync(root, { withFileTypes: true });
	} catch {
		return undefined;
	}
	const candidates = entries
		.filter(entry => entry.isDirectory())
		.map(entry => path.join(root, entry.name))
		.filter(candidate => fs.existsSync(path.join(candidate, MANIFEST_RELATIVE_PATH)))
		.map(candidate => ({ candidate, modified: fs.statSync(candidate).mtimeMs }))
		.sort((left, right) => right.modified - left.modified);
	return candidates.length > 0 ? candidates[0].candidate : undefined;
}
