/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as dom from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr, IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IModernityAuthService, ModernityAuthState } from '../../../../platform/modernityAuth/common/modernityAuth.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IWorkbenchLayoutService } from '../../../services/layout/browser/layoutService.js';
import './media/modernityAuth.css';

const MODERNITY_AUTHENTICATED = new RawContextKey<boolean>('modernity.authenticated', false);

interface GatedElementState {
	readonly inert: boolean;
	readonly ariaHidden: string | null;
}

export class ModernityAuthContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.modernityAuth';

	private readonly renderDisposables = this._register(new MutableDisposable<DisposableStore>());
	private readonly authenticatedContext: IContextKey<boolean>;
	private readonly gatedElements = new Map<HTMLElement, GatedElementState>();
	private overlay: HTMLElement | undefined;
	private gateObserver: MutationObserver | undefined;
	private mode: 'signin' | 'signup' = 'signin';
	private focusableButtons: HTMLButtonElement[] = [];

	constructor(
		@IModernityAuthService private readonly authService: IModernityAuthService,
		@IWorkbenchLayoutService private readonly layoutService: IWorkbenchLayoutService,
		@IOpenerService private readonly openerService: IOpenerService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@INotificationService private readonly notificationService: INotificationService,
		@IContextKeyService contextKeyService: IContextKeyService,
	) {
		super();
		this.authenticatedContext = MODERNITY_AUTHENTICATED.bindTo(contextKeyService);
		this._register(this.authService.onDidChangeState(state => this.render(state)));
		this.render({ status: 'loading' });
		void this.authService.initialize().then(state => this.render(state));
	}

	private render(state: ModernityAuthState): void {
		this.authenticatedContext.set(state.status === 'signedIn');
		if (state.status === 'signedIn') {
			this.removeGate();
			return;
		}

		const overlay = this.ensureGate();
		const store = new DisposableStore();
		this.renderDisposables.value = store;
		this.focusableButtons = [];
		dom.clearNode(overlay);

		const shell = dom.append(overlay, dom.$('.modernity-auth-shell'));
		const brand = dom.append(shell, dom.$('.modernity-auth-brand'));
		const brandMark = dom.append(brand, dom.$('.modernity-auth-brand-mark'));
		brandMark.textContent = 'M';
		dom.append(brand, dom.$('span')).textContent = 'Modernity';

		const content = dom.append(shell, dom.$('.modernity-auth-content'));
		content.setAttribute('role', 'dialog');
		content.setAttribute('aria-modal', 'true');
		content.setAttribute('aria-live', 'polite');

		switch (state.status) {
			case 'loading':
				this.renderLoading(content);
				break;
			case 'signedOut':
				this.renderSignedOut(content, store);
				break;
			case 'authorizing':
				this.renderAuthorizing(content, state, store);
				break;
			case 'error':
				this.renderError(content, state, store);
				break;
		}

		const firstFocusable = this.focusableButtons.find(button => !button.disabled);
		firstFocusable?.focus();
		store.add(dom.addDisposableListener(overlay, 'keydown', event => this.trapFocus(event)));
	}

	private renderLoading(content: HTMLElement): void {
		const icon = this.appendIcon(content, Codicon.loading, 'modernity-auth-state-icon');
		icon.classList.add('codicon-modifier-spin');
		icon.setAttribute('aria-hidden', 'true');
		const title = dom.append(content, dom.$('h1'));
		title.textContent = localize('modernityAuth.restoring', "Restoring Your Session");
		content.setAttribute('aria-labelledby', this.ensureId(title, 'modernity-auth-title'));
	}

	private renderSignedOut(content: HTMLElement, store: DisposableStore): void {
		const tabs = dom.append(content, dom.$('.modernity-auth-modes'));
		tabs.setAttribute('role', 'tablist');
		tabs.setAttribute('aria-label', localize('modernityAuth.accountAccess', "Account Access"));
		this.createModeButton(tabs, 'signin', localize('modernityAuth.signIn', "Sign In"), store);
		this.createModeButton(tabs, 'signup', localize('modernityAuth.signUp', "Sign Up"), store);

		const title = dom.append(content, dom.$('h1'));
		title.textContent = this.mode === 'signin'
			? localize('modernityAuth.welcomeBack', "Welcome Back")
			: localize('modernityAuth.createAccount', "Create Your Account");
		content.setAttribute('aria-labelledby', this.ensureId(title, 'modernity-auth-title'));

		const subtitle = dom.append(content, dom.$('p.modernity-auth-subtitle'));
		subtitle.textContent = this.mode === 'signin'
			? localize('modernityAuth.signInSubtitle', "Continue with the GitHub account connected to Modernity.")
			: localize('modernityAuth.signUpSubtitle', "Your GitHub identity securely creates your Modernity account.");

		const primary = this.createButton(
			content,
			this.mode === 'signin'
				? localize('modernityAuth.continueGithub', "Continue with GitHub")
				: localize('modernityAuth.createGithub', "Create Account with GitHub"),
			'modernity-auth-primary',
			Codicon.github,
			store,
			async button => {
				button.disabled = true;
				const state = await this.authService.startAuthentication();
				if (state.status === 'authorizing') {
					await this.openAuthorization(state);
				}
			}
		);
		primary.setAttribute('data-default-focus', 'true');
	}

	private renderAuthorizing(content: HTMLElement, state: Extract<ModernityAuthState, { status: 'authorizing' }>, store: DisposableStore): void {
		const icon = this.appendIcon(content, Codicon.github, 'modernity-auth-state-icon');
		icon.setAttribute('aria-hidden', 'true');
		const title = dom.append(content, dom.$('h1'));
		title.textContent = localize('modernityAuth.finishBrowser', "Finish in Your Browser");
		content.setAttribute('aria-labelledby', this.ensureId(title, 'modernity-auth-title'));

		const subtitle = dom.append(content, dom.$('p.modernity-auth-subtitle'));
		subtitle.textContent = localize('modernityAuth.waitingGithub', "Modernity is waiting for GitHub approval.");

		const codeRow = dom.append(content, dom.$('.modernity-auth-code-row'));
		const code = dom.append(codeRow, dom.$('code.modernity-auth-code'));
		code.textContent = state.authorization.userCode;
		const copyButton = this.createIconButton(
			codeRow,
			Codicon.copy,
			localize('modernityAuth.copyCode', "Copy Code"),
			store,
			async () => this.copyAuthorizationCode(copyButton, state.authorization.userCode),
		);
		copyButton.classList.add('modernity-auth-copy');

		this.createButton(
			content,
			localize('modernityAuth.openGithub', "Open GitHub"),
			'modernity-auth-primary',
			Codicon.linkExternal,
			store,
			async () => this.openAuthorization(state),
		);
		this.createButton(
			content,
			localize('modernityAuth.cancel', "Cancel"),
			'modernity-auth-secondary',
			undefined,
			store,
			async () => this.authService.cancelAuthentication(),
		);

		const pending = dom.append(content, dom.$('.modernity-auth-pending'));
		const spinner = this.appendIcon(pending, Codicon.loading);
		spinner.classList.add('codicon-modifier-spin');
		spinner.setAttribute('aria-hidden', 'true');
		dom.append(pending, dom.$('span')).textContent = localize('modernityAuth.checking', "Checking for approval...");
	}

	private renderError(content: HTMLElement, state: Extract<ModernityAuthState, { status: 'error' }>, store: DisposableStore): void {
		const icon = this.appendIcon(content, Codicon.error, 'modernity-auth-state-icon', 'modernity-auth-error-icon');
		icon.setAttribute('aria-hidden', 'true');
		const title = dom.append(content, dom.$('h1'));
		title.textContent = localize('modernityAuth.failed', "Sign In Unavailable");
		content.setAttribute('aria-labelledby', this.ensureId(title, 'modernity-auth-title'));
		const message = dom.append(content, dom.$('p.modernity-auth-subtitle'));
		message.setAttribute('role', 'alert');
		message.textContent = this.errorMessage(state.code);

		if (state.canRetry) {
			this.createButton(
				content,
				localize('modernityAuth.retry', "Try Again"),
				'modernity-auth-primary',
				Codicon.refresh,
				store,
				async button => {
					button.disabled = true;
					const next = await this.authService.retry();
					if (next.status === 'authorizing') {
						await this.openAuthorization(next);
					}
				},
			);
		}
		this.createButton(
			content,
			localize('modernityAuth.anotherAccount', "Use Another Account"),
			'modernity-auth-secondary',
			undefined,
			store,
			async () => this.authService.logout(),
		);
	}

	private createModeButton(container: HTMLElement, mode: 'signin' | 'signup', label: string, store: DisposableStore): void {
		const button = dom.append(container, dom.$('button.modernity-auth-mode')) as HTMLButtonElement;
		button.type = 'button';
		button.textContent = label;
		button.setAttribute('role', 'tab');
		button.setAttribute('aria-selected', String(this.mode === mode));
		button.classList.toggle('active', this.mode === mode);
		this.focusableButtons.push(button);
		store.add(dom.addDisposableListener(button, 'click', () => {
			this.mode = mode;
			this.render({ status: 'signedOut' });
		}));
	}

	private createButton(
		container: HTMLElement,
		label: string,
		className: string,
		icon: ThemeIcon | undefined,
		store: DisposableStore,
		run: (button: HTMLButtonElement) => Promise<void>,
	): HTMLButtonElement {
		const button = dom.append(container, dom.$(`button.modernity-auth-button.${className}`)) as HTMLButtonElement;
		button.type = 'button';
		this.focusableButtons.push(button);
		if (icon) {
			const iconElement = this.appendIcon(button, icon);
			iconElement.setAttribute('aria-hidden', 'true');
		}
		dom.append(button, dom.$('span')).textContent = label;
		store.add(dom.addDisposableListener(button, 'click', () => void run(button)));
		return button;
	}

	private createIconButton(
		container: HTMLElement,
		icon: ThemeIcon,
		label: string,
		store: DisposableStore,
		run: () => Promise<void>,
	): HTMLButtonElement {
		const button = dom.append(container, dom.$('button.modernity-auth-icon-button')) as HTMLButtonElement;
		button.type = 'button';
		this.focusableButtons.push(button);
		button.title = label;
		button.setAttribute('aria-label', label);
		const iconElement = this.appendIcon(button, icon);
		iconElement.setAttribute('aria-hidden', 'true');
		store.add(dom.addDisposableListener(button, 'click', () => void run()));
		return button;
	}

	private async openAuthorization(state: Extract<ModernityAuthState, { status: 'authorizing' }>): Promise<void> {
		const target = state.authorization.verificationUriComplete ?? state.authorization.verificationUri;
		await this.openerService.open(URI.parse(target), { openExternal: true });
	}

	private async copyAuthorizationCode(button: HTMLButtonElement, code: string): Promise<void> {
		try {
			await this.clipboardService.writeText(code);
			button.title = localize('modernityAuth.codeCopied', "Code Copied");
			button.setAttribute('aria-label', button.title);
			dom.clearNode(button);
			const icon = this.appendIcon(button, Codicon.check);
			icon.setAttribute('aria-hidden', 'true');
			this.notificationService.info(localize('modernityAuth.codeCopiedNotification', "GitHub device code copied."));
		} catch {
			this.notificationService.error(localize('modernityAuth.codeCopyFailed', "Modernity could not copy the GitHub device code."));
		}
	}

	private appendIcon(container: HTMLElement, icon: ThemeIcon, ...classNames: string[]): HTMLElement {
		const element = dom.append(container, dom.$('span'));
		element.classList.add(...ThemeIcon.asClassNameArray(icon), ...classNames);
		element.setAttribute('aria-hidden', 'true');
		return element;
	}

	private errorMessage(code: string): string {
		switch (code) {
			case 'AUTH_DEVICE_DENIED':
				return localize('modernityAuth.denied', "GitHub authorization was not approved.");
			case 'AUTH_DEVICE_EXPIRED':
				return localize('modernityAuth.expired', "The sign-in request expired. Start again to continue.");
			case 'GITHUB_RATE_LIMITED':
				return localize('modernityAuth.rateLimited', "GitHub is receiving too many requests. Try again shortly.");
			case 'AUTH_SECURE_STORAGE_UNAVAILABLE':
				return localize('modernityAuth.storageUnavailable', "Modernity could not securely store your session on this device.");
			default:
				return localize('modernityAuth.serviceUnavailable', "Modernity could not reach the authentication service.");
		}
	}

	private ensureGate(): HTMLElement {
		if (this.overlay) {
			return this.overlay;
		}

		const container = this.layoutService.mainContainer;
		container.classList.add('modernity-auth-gated');
		this.overlay = dom.append(container, dom.$('.modernity-auth-gate'));
		for (const child of Array.from(container.children)) {
			this.gateElement(child);
		}
		this.gateObserver = new MutationObserver(records => {
			for (const record of records) {
				for (const node of Array.from(record.addedNodes)) {
					if (dom.isHTMLElement(node)) {
						this.gateElement(node);
					}
				}
			}
		});
		this.gateObserver.observe(container, { childList: true });
		return this.overlay;
	}

	private gateElement(element: unknown): void {
		if (!dom.isHTMLElement(element) || element === this.overlay || this.gatedElements.has(element)) {
			return;
		}
		this.gatedElements.set(element, { inert: element.inert, ariaHidden: element.getAttribute('aria-hidden') });
		element.inert = true;
		element.setAttribute('aria-hidden', 'true');
	}

	private removeGate(): void {
		this.renderDisposables.clear();
		this.gateObserver?.disconnect();
		this.gateObserver = undefined;
		for (const [element, state] of this.gatedElements) {
			element.inert = state.inert;
			if (state.ariaHidden === null) {
				element.removeAttribute('aria-hidden');
			} else {
				element.setAttribute('aria-hidden', state.ariaHidden);
			}
		}
		this.gatedElements.clear();
		this.overlay?.remove();
		this.overlay = undefined;
		this.layoutService.mainContainer.classList.remove('modernity-auth-gated');
	}

	private trapFocus(event: KeyboardEvent): void {
		if (event.key !== 'Tab' || !this.overlay) {
			return;
		}
		const focusable = this.focusableButtons.filter(button => button.isConnected && !button.disabled);
		if (focusable.length === 0) {
			event.preventDefault();
			return;
		}
		const active = this.overlay.ownerDocument.activeElement;
		const index = focusable.findIndex(button => button === active);
		const next = event.shiftKey
			? focusable[(index <= 0 ? focusable.length : index) - 1]
			: focusable[(index + 1) % focusable.length];
		event.preventDefault();
		next.focus();
	}

	private ensureId(element: HTMLElement, id: string): string {
		element.id = id;
		return id;
	}

	override dispose(): void {
		this.removeGate();
		this.authenticatedContext.reset();
		super.dispose();
	}
}

class ModernityLogoutAction extends Action2 {
	constructor() {
		super({
			id: 'modernity.auth.logout',
			title: localize2('modernityAuth.logout', "Sign Out of Modernity"),
			menu: [{
				id: MenuId.AccountsContext,
				when: ContextKeyExpr.equals(MODERNITY_AUTHENTICATED.key, true),
				order: 200,
			}],
			f1: true,
			precondition: ContextKeyExpr.equals(MODERNITY_AUTHENTICATED.key, true),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IModernityAuthService).logout();
	}
}

class ModernityManageAccountAction extends Action2 {
	constructor() {
		super({
			id: 'modernity.auth.manageAccount',
			title: localize2('modernityAuth.manageAccount', "Manage Modernity Account"),
			menu: [{
				id: MenuId.AccountsContext,
				when: ContextKeyExpr.equals(MODERNITY_AUTHENTICATED.key, true),
				order: 199,
			}],
			f1: true,
			precondition: ContextKeyExpr.equals(MODERNITY_AUTHENTICATED.key, true),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('aiCustomization.openModernityAccount');
	}
}

/**
 * Hand the signed-in Modernity bearer to built-in Modernity extensions.
 *
 * The account session already refreshes itself, so extensions must read the token
 * per request through this command instead of caching one. It is intentionally an
 * internal (underscore-prefixed) command and stays out of the command palette;
 * like the sandbox daemon bearer, it is scoped to the trust boundary of this
 * window's extensions.
 */
CommandsRegistry.registerCommand('_modernity.auth.getAccessToken', async (accessor: ServicesAccessor): Promise<string | undefined> => {
	return accessor.get(IModernityAuthService).getAccessToken();
});

registerAction2(ModernityManageAccountAction);
registerAction2(ModernityLogoutAction);
registerWorkbenchContribution2(ModernityAuthContribution.ID, ModernityAuthContribution, WorkbenchPhase.BlockRestore);
