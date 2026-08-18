/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { LocalChatSessionUri } from '../common/model/chatUri.js';
import { IChatWidget, IChatWidgetService } from './chat.js';

/** True only while the focused chat is the one that began the benchmark episode. */
export const MODERNITY_EPISODE_SESSION = new RawContextKey<boolean>('modernity.episode.session', false);

/** The chat session the Modernity extension registered as its active episode. */
let episodeSessionId: string | undefined;
const onDidChangeEpisodeSession = new Emitter<void>();

CommandsRegistry.registerCommand('_modernity.episode.setSessionId', (_accessor, sessionId?: unknown): void => {
	episodeSessionId = typeof sessionId === 'string' && sessionId ? sessionId : undefined;
	onDidChangeEpisodeSession.fire();
});

function sessionIdOf(resource: URI | undefined): string | undefined {
	if (!resource) {
		return undefined;
	}
	// Matches how the extension host derives ChatRequest.sessionId from the same resource.
	return LocalChatSessionUri.parseLocalSessionId(resource) ?? resource.toString();
}

/**
 * Scope Modernity's Submit action to the chat that started the episode.
 *
 * The episode itself belongs to the workspace, so without this the action would
 * offer to seal the episode from unrelated chats.
 */
export class ModernityEpisodeSessionContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.modernityEpisodeSession';

	private readonly episodeSession: IContextKey<boolean>;
	private readonly focusedWidgetListener = this._register(new MutableDisposable());

	constructor(
		@IChatWidgetService private readonly chatWidgetService: IChatWidgetService,
		@IContextKeyService contextKeyService: IContextKeyService,
	) {
		super();
		this.episodeSession = MODERNITY_EPISODE_SESSION.bindTo(contextKeyService);
		this._register(onDidChangeEpisodeSession.event(() => this.update()));
		this._register(this.chatWidgetService.onDidChangeFocusedWidget(widget => this.track(widget)));
		this.track(this.chatWidgetService.lastFocusedWidget);
	}

	private track(widget: IChatWidget | undefined): void {
		// A widget restores its view model asynchronously, so follow it rather than
		// reading a session that is not attached yet.
		this.focusedWidgetListener.value = widget?.onDidChangeViewModel(() => this.update());
		this.update();
	}

	private update(): void {
		const focused = sessionIdOf(this.chatWidgetService.lastFocusedWidget?.viewModel?.sessionResource);
		this.episodeSession.set(episodeSessionId !== undefined && focused === episodeSessionId);
	}

	override dispose(): void {
		this.episodeSession.reset();
		super.dispose();
	}
}
