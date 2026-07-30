/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  Licensed under the MIT License.
 *  T23: Project platform models — typed, stable, no business logic.
 *--------------------------------------------------------------------------------------------*/

export type Visibility = 'private' | 'public';
export type LifecycleStatus = 'provisioning' | 'awaiting_checkout' | 'awaiting_push' | 'active' | 'error' | 'archived';
export type RepositoryStatus = 'active' | 'missing' | 'unauthorized';
export type CheckoutState = 'present' | 'missing' | 'moved' | 'detached';

export type Sha40 = string;
export type Rfc3339 = string;
export type Uuid = string;

export interface Failure {
	readonly code: string;
	readonly message: string;
	readonly retryable: boolean;
}

export interface RepositorySummary {
	readonly id: Uuid;
	readonly github_repository_id: string; // decimal-string
	readonly installation_id: Uuid;
	readonly owner: string;
	readonly name: string;
	readonly full_name: string;
	readonly visibility: Visibility;
	readonly default_branch: string;
	readonly html_url: string;
	readonly clone_url: string;
	readonly archived: boolean;
	readonly status: RepositoryStatus;
	/** Backend's latest GitHub observation — never inferred from local Git. */
	readonly head_sha: Sha40 | null;
	readonly head_observed_at: Rfc3339 | null;
	readonly version: number;
}

export interface Project {
	readonly id: Uuid;
	readonly name: string;
	readonly slug: string;
	readonly description: string | null;
	readonly mod_id: string;
	readonly mod_name: string;
	readonly group_id: string;
	readonly mod_version: string;
	readonly license: string;
	readonly template_id: string;
	readonly template_version: string;
	readonly minecraft_version: string;
	readonly neoforge_version: string;
	readonly java_version: string;
	readonly gradle_version: string;
	readonly visibility: Visibility;
	readonly default_branch: string;
	readonly settings: Readonly<Record<string, unknown>>;
	readonly lifecycle_status: LifecycleStatus;
	readonly failure: Failure | null;
	readonly repository: RepositorySummary | null;
	readonly created_at: Rfc3339;
	readonly updated_at: Rfc3339;
	readonly archived_at: Rfc3339 | null;
	readonly last_opened_at: Rfc3339 | null;
	readonly version: number;
}

export interface MachineRef {
	readonly id: Uuid;
	readonly display_name: string;
}

export interface Checkout {
	readonly id: Uuid;
	readonly project_id: Uuid;
	readonly machine: MachineRef;
	/** Present only for current machine's checkout. Omitted for other machines. */
	readonly absolute_path?: string;
	readonly folder_basename: string;
	readonly state: CheckoutState;
	readonly is_primary: boolean;
	readonly manifest_version: number;
	readonly last_seen_at: Rfc3339;
	readonly version: number;
}

export interface Page<T> {
	readonly items: ReadonlyArray<T>;
	readonly next_cursor: string | null;
}

export interface CursorParams {
	readonly limit?: number; // 1..100, default 50
	readonly cursor?: string; // opaque
	readonly include_archived?: boolean;
}

// ---- Git adapter models ----

export type GitClassification =
	| 'clean'
	| 'dirty'
	| 'local_ahead'
	| 'remote_ahead'
	| 'diverged'
	| 'detached'
	| 'unpublished'
	| 'missing'
	| 'error';

export interface LocalGitStatus {
	readonly branch: string | null;
	readonly head_sha: Sha40 | null;
	readonly upstream_sha: Sha40 | null;
	readonly dirty: boolean;
	readonly ahead: number | null;
	readonly behind: number | null;
	readonly detached: boolean;
	readonly conflicted: boolean;
	readonly unpublished: boolean;
	readonly classification: GitClassification;
}

export type GitOperation =
	| 'status'
	| 'init'
	| 'clone'
	| 'import'
	| 'fetch'
	| 'fast_forward_pull'
	| 'push';

export interface GitAdapterOptions {
	readonly trustedIdentity?: { owner: string; name: string };
	readonly branch?: string;
	readonly remoteUrl?: string;
	readonly defaultBranch?: string;
	readonly depth?: number;
	readonly force?: boolean; // disallowed for push; adapter must reject
}

export interface GitPreviewResult {
	readonly operation: GitOperation;
	readonly wouldNeed: string[];
	readonly safe: boolean;
	readonly reason?: string;
}

export interface GitActionResult {
	readonly operation: GitOperation;
	readonly status: LocalGitStatus;
	readonly changed: boolean;
}
