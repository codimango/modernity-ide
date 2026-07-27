/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { OutputMode, Raw } from '@vscode/prompt-tsx';
import { describe, expect, test } from 'vitest';
import { CopilotToken, createTestExtendedTokenInfo } from '../../../../../platform/authentication/common/copilotToken';
import { ICopilotTokenStore } from '../../../../../platform/authentication/common/copilotTokenStore';
import type { IChatEndpoint } from '../../../../../platform/networking/common/networking';
import { ITokenizer, TokenizerType } from '../../../../../util/common/tokenizer';
import { IInstantiationService } from '../../../../../util/vs/platform/instantiation/common/instantiation';
import { createExtensionUnitTestingServices } from '../../../../test/node/services';
import { PromptRenderer } from '../../base/promptRenderer';
import { Image } from '../image';

function createEndpoint(isExtensionContributed: boolean): IChatEndpoint {
	return {
		family: 'claude',
		model: 'claude-test',
		modelMaxPromptTokens: 128000,
		maxOutputTokens: 4096,
		name: 'Claude Test',
		version: '1.0',
		modelProvider: isExtensionContributed ? 'modernity' : 'copilot',
		supportsToolCalls: true,
		supportsVision: true,
		supportsPrediction: false,
		showInModelPicker: true,
		isFallback: false,
		isExtensionContributed,
		tokenizer: TokenizerType.O200K,
		urlOrRequestMetadata: '',
		acquireTokenizer: (): ITokenizer => ({
			mode: OutputMode.Raw,
			tokenLength: async () => 0,
			countMessageTokens: async () => 0,
			countMessagesTokens: async () => 0,
			countToolTokens: async () => 0,
		}),
	} as IChatEndpoint;
}

async function renderImage(isExtensionContributed: boolean): Promise<Raw.ChatMessage[]> {
	const services = createExtensionUnitTestingServices();
	const accessor = services.createTestingAccessor();
	accessor.get(ICopilotTokenStore).copilotToken = new CopilotToken(createTestExtendedTokenInfo({
		token: 'editor_preview_features=0;tid=test',
	}));
	const renderer = PromptRenderer.create(
		accessor.get(IInstantiationService),
		createEndpoint(isExtensionContributed),
		Image,
		{
			variableName: 'image',
			variableValue: new Uint8Array([0x89, 0x50, 0x4e, 0x47]),
			omitReferences: true,
		},
	);
	return (await renderer.render()).messages;
}

describe('Image', () => {
	test('renders images for extension-contributed endpoints when Copilot preview is disabled', async () => {
		const messages = await renderImage(true);

		expect(messages.some(message => message.content.some(
			part => part.type === Raw.ChatCompletionContentPartKind.Image
		))).toBe(true);
	});

	test('keeps Copilot image entitlement when preview is disabled', async () => {
		const messages = await renderImage(false);

		expect(messages.some(message => message.content.some(
			part => part.type === Raw.ChatCompletionContentPartKind.Image
		))).toBe(false);
	});
});
