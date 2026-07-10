/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../../base/common/themables.js';
// Modernity: hide Move Chat actions - URI no longer used
import { localize, localize2 } from '../../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../../platform/actions/common/actions.js';
import { ContextKeyExpr, ContextKeyExpression } from '../../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../../platform/instantiation/common/instantiation.js';
import { ActiveEditorContext } from '../../../../common/contextkeys.js';
import { ViewContainerLocation } from '../../../../common/views.js';
import { IEditorGroupsService } from '../../../../services/editor/common/editorGroupsService.js';
// Modernity: hide Move Chat actions - ACTIVE_GROUP and AUX_WINDOW_GROUP no longer used
import { IEditorService } from '../../../../services/editor/common/editorService.js';
import { IViewsService } from '../../../../services/views/common/viewsService.js';
// Modernity: hide Move Chat actions - isChatViewTitleActionContext no longer used
import { ChatContextKeys } from '../../common/actions/chatContextKeys.js';
// Modernity: hide Move Chat actions - ChatAgentLocation no longer used
import { ChatViewId } from '../chat.js';
// Modernity: hide Move Chat actions - IChatWidgetService no longer used
import { ChatEditor } from '../widgetHosts/editor/chatEditor.js';
// Modernity: hide Move Chat actions - IChatEditorOptions no longer used
import { ChatEditorInput } from '../widgetHosts/editor/chatEditorInput.js';
import { ChatViewPane } from '../widgetHosts/viewPane/chatViewPane.js';
import { CHAT_CATEGORY } from './chatActions.js';

// Modernity: hide Move Chat into Editor Area and New Window - MoveToNewLocation no longer used

export function registerMoveActions() {
	// Modernity: hide Move Chat into Editor Area and Move Chat into New Window for simple agent panel experience

	registerAction2(class GlobalMoveToSidebarAction extends Action2 {
		constructor() {
			super({
				id: 'workbench.action.chat.openInSidebar',
				title: localize2('interactiveSession.openInSidebar.label', "Move Chat into Side Bar"),
				category: CHAT_CATEGORY,
				precondition: ChatContextKeys.enabled,
				f1: true
			});
		}

		async run(accessor: ServicesAccessor, ...args: unknown[]) {
			return moveToSidebar(accessor);
		}
	});

	function appendOpenChatInViewMenuItem(menuId: MenuId, title: string, icon: ThemeIcon, locationContextKey: ContextKeyExpression) {
		MenuRegistry.appendMenuItem(menuId, {
			command: { id: 'workbench.action.chat.openInSidebar', title, icon },
			when: ContextKeyExpr.and(
				ActiveEditorContext.isEqualTo(ChatEditorInput.EditorID),
				locationContextKey
			),
			group: menuId === MenuId.CompactWindowEditorTitle ? 'navigation' : undefined,
			order: 0
		});
	}

	[MenuId.EditorTitle, MenuId.CompactWindowEditorTitle].forEach(id => {
		appendOpenChatInViewMenuItem(id, localize('interactiveSession.openInSecondarySidebar.label', "Move Chat into Secondary Side Bar"), Codicon.layoutSidebarRightDock, ChatContextKeys.panelLocation.isEqualTo(ViewContainerLocation.AuxiliaryBar));
		appendOpenChatInViewMenuItem(id, localize('interactiveSession.openInPrimarySidebar.label', "Move Chat into Primary Side Bar"), Codicon.layoutSidebarLeftDock, ChatContextKeys.panelLocation.isEqualTo(ViewContainerLocation.Sidebar));
		appendOpenChatInViewMenuItem(id, localize('interactiveSession.openInPanel.label', "Move Chat into Panel"), Codicon.layoutPanelDock, ChatContextKeys.panelLocation.isEqualTo(ViewContainerLocation.Panel));
	});
}

// Modernity: hide Move Chat into Editor Area and New Window - executeMoveToAction no longer used

async function moveToSidebar(accessor: ServicesAccessor): Promise<void> {
	const viewsService = accessor.get(IViewsService);
	const editorService = accessor.get(IEditorService);
	const editorGroupService = accessor.get(IEditorGroupsService);

	const chatEditor = editorService.activeEditorPane;
	const chatEditorInput = chatEditor?.input;
	let view: ChatViewPane;
	if (chatEditor instanceof ChatEditor && chatEditorInput instanceof ChatEditorInput && chatEditorInput.sessionResource) {
		const previousViewState = chatEditor.widget.getViewState();
		await editorService.closeEditor({ editor: chatEditor.input, groupId: editorGroupService.activeGroup.id });
		view = await viewsService.openView(ChatViewId) as ChatViewPane;

		// Todo: can possibly go away with https://github.com/microsoft/vscode/pull/278476
		const newModel = await view.loadSession(chatEditorInput.sessionResource);
		if (previousViewState && newModel && !newModel.inputModel.state.get()) {
			newModel.inputModel.setState(previousViewState);
		}
	} else {
		view = await viewsService.openView(ChatViewId) as ChatViewPane;
	}

	view.focus();
}
