/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Modernity. All rights reserved.
 *  T23: Stable typed errors — no stringly typing elsewhere.
 *--------------------------------------------------------------------------------------------*/

export type CloudErrorKind =
	| 'signed_out' // 401
	| 'unauthorized' // 403
	| 'missing' // 404
	| 'conflict' // 409
	| 'validation' // 422
	| 'rate_limited' // 429
	| 'offline' // 503 / network
	| 'unknown';

export interface CloudErrorEnvelope {
	readonly code: string;
	readonly message: string;
	readonly request_id: string;
	readonly retryable: boolean;
	readonly details?: Readonly<Record<string, unknown>>;
}

export class CloudApiError extends Error {
	readonly kind: CloudErrorKind;
	readonly envelope: CloudErrorEnvelope;
	readonly status: number;
	constructor(status: number, kind: CloudErrorKind, envelope: CloudErrorEnvelope) {
		super(envelope.message);
		this.name = 'CloudApiError';
		this.status = status;
		this.kind = kind;
		this.envelope = envelope;
	}
}

export type DaemonErrorKind =
	| 'runtime_missing' // file not found
	| 'runtime_invalid' // malformed JSON
	| 'unauthorized' // 401 / bad token
	| 'unavailable' // connection failure
	| 'restarted' // stale vs current PID/token, daemon restarted
	| 'backend' // daemon returned typed error
	| 'unknown';

export interface DaemonErrorPayload {
	readonly type: string;
	readonly where: string;
	readonly message: string;
	readonly fix_hint: string;
	readonly retryable: boolean;
	readonly evidence: Readonly<Record<string, unknown>>;
}

export class DaemonError extends Error {
	readonly kind: DaemonErrorKind;
	readonly payload?: DaemonErrorPayload;
	readonly causeDetails?: unknown;
	constructor(kind: DaemonErrorKind, message: string, payload?: DaemonErrorPayload, causeDetails?: unknown) {
		super(message);
		this.name = 'DaemonError';
		this.kind = kind;
		this.payload = payload;
		this.causeDetails = causeDetails;
	}
}

export type GitErrorKind =
	| 'missing' // no .git / not a repo
	| 'unauthorized' // credential provider failed
	| 'conflict'
	| 'offline'
	| 'invalid_argument'
	| 'unknown';

export class GitAdapterError extends Error {
	readonly kind: GitErrorKind;
	constructor(kind: GitErrorKind, message: string) {
		super(message);
		this.name = 'GitAdapterError';
		this.kind = kind;
	}
}

// Utility: map HTTP status + envelope to kind
export function mapHttpStatusToCloudKind(status: number): CloudErrorKind {
	switch (status) {
		case 401: return 'signed_out';
		case 403: return 'unauthorized';
		case 404: return 'missing';
		case 409: return 'conflict';
		case 422: return 'validation';
		case 429: return 'rate_limited';
		case 503: return 'offline';
		default:
			if (status >= 500) { return 'offline'; }
			return 'unknown';
	}
}
