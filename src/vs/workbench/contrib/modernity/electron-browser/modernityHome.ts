/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modernityHome.css';
import { $, addDisposableListener, append, clearNode, Dimension } from '../../../../base/browser/dom.js';
import { renderIcon } from '../../../../base/browser/ui/iconLabel/iconLabels.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { basename } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { IModernityProjectService, IModernityProjectSummary } from '../../../../platform/modernityProject/common/modernityProject.js';
import { IRecentFolder, IRecentWorkspace, isRecentFolder, IWorkspacesService } from '../../../../platform/workspaces/common/workspaces.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { EditorInputCapabilities, IEditorOpenContext, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IHostService } from '../../../services/host/browser/host.js';

const CREATE_MODERNITY_PROJECT_COMMAND = 'workbench.action.createModernityProject';
const MAX_RECENT_PROJECTS = 6;

export class ModernityHomeInput extends EditorInput {
	static readonly ID = 'workbench.editors.modernityHomeInput';
	static readonly RESOURCE = URI.from({ scheme: 'modernity-home', path: '/projects' });

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Singleton | super.capabilities;
	}

	override get typeId(): string {
		return ModernityHomeInput.ID;
	}

	override get editorId(): string {
		return ModernityHomePage.ID;
	}

	override get resource(): URI {
		return ModernityHomeInput.RESOURCE;
	}

	override getName(): string {
		return localize('modernity.home.name', "Modernity");
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof ModernityHomeInput;
	}
}

export class ModernityHomePage extends EditorPane {
	static readonly ID = 'workbench.editor.modernityHome';

	private readonly contentDisposables = this._register(new DisposableStore());
	private container!: HTMLElement;
	private content!: HTMLElement;
	private refreshSequence = 0;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileDialogService private readonly fileDialogService: IFileDialogService,
		@IHostService private readonly hostService: IHostService,
		@INotificationService private readonly notificationService: INotificationService,
		@IProgressService private readonly progressService: IProgressService,
		@IModernityProjectService private readonly projectService: IModernityProjectService,
		@IWorkspacesService private readonly workspacesService: IWorkspacesService,
	) {
		super(ModernityHomePage.ID, group, telemetryService, themeService, storageService);
		this._register(this.workspacesService.onDidChangeRecentlyOpened(() => {
			if (this.input instanceof ModernityHomeInput) {
				void this.refresh();
			}
		}));
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = append(parent, $('.modernity-home'));
		this.container.tabIndex = 0;
		this.container.setAttribute('role', 'main');
		this.container.setAttribute('aria-label', localize('modernity.home.ariaLabel', "Modernity Projects"));
		this.content = append(this.container, $('.modernity-home-content'));
	}

	override async setInput(
		input: ModernityHomeInput,
		options: object | undefined,
		context: IEditorOpenContext,
		token: CancellationToken,
	): Promise<void> {
		await super.setInput(input, options, context, token);
		await this.refresh();
	}

	override focus(): void {
		this.container.focus();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
	}

	private async refresh(): Promise<void> {
		const sequence = ++this.refreshSequence;
		this.renderLoading();
		try {
			const [projects, recentlyOpened] = await Promise.all([
				this.projectService.listProjects(),
				this.workspacesService.getRecentlyOpened(),
			]);
			if (sequence !== this.refreshSequence) {
				return;
			}
			this.render(projects, recentlyOpened.workspaces.slice(0, MAX_RECENT_PROJECTS));
		} catch (error) {
			if (sequence !== this.refreshSequence) {
				return;
			}
			this.renderError(error instanceof Error ? error.message : String(error));
		}
	}

	private renderLoading(): void {
		this.contentDisposables.clear();
		clearNode(this.content);
		this.renderHeader();
		const loading = append(this.content, $('.modernity-home-loading'));
		const icon = renderIcon(Codicon.loading);
		icon.classList.add('codicon-modifier-spin');
		loading.appendChild(icon);
		append(loading, $('span', {}, localize('modernity.home.loading', "Loading Projects...")));
	}

	private renderError(message: string): void {
		this.contentDisposables.clear();
		clearNode(this.content);
		this.renderHeader();
		const state = append(this.content, $('.modernity-home-state'));
		state.appendChild(renderIcon(Codicon.error));
		append(state, $('h2', {}, localize('modernity.home.loadFailed', "Projects Could Not Be Loaded")));
		append(state, $('p', {}, message));
		const retry = this.createButton(state, Codicon.refresh, localize('modernity.home.retry', "Retry"), 'secondary');
		this.contentDisposables.add(addDisposableListener(retry, 'click', () => void this.refresh()));
	}

	private render(
		projects: readonly IModernityProjectSummary[],
		recentProjects: readonly (IRecentWorkspace | IRecentFolder)[],
	): void {
		this.contentDisposables.clear();
		clearNode(this.content);
		this.renderHeader();

		if (recentProjects.length) {
			const recentSection = this.createSection(
				localize('modernity.home.recent', "Recent"),
				String(recentProjects.length),
			);
			const recentList = append(recentSection, $('.modernity-home-list'));
			for (const recent of recentProjects) {
				this.renderRecentProject(recentList, recent);
			}
		}

		const projectSection = this.createSection(
			localize('modernity.home.projects', "Projects"),
			String(projects.length),
		);
		const toolbar = append(projectSection, $('.modernity-home-project-toolbar'));
		const searchWrap = append(toolbar, $('.modernity-home-search'));
		searchWrap.appendChild(renderIcon(Codicon.search));
		const search = append(searchWrap, $('input')) as HTMLInputElement;
		search.type = 'search';
		search.placeholder = localize('modernity.home.filterProjects', "Filter Projects");
		search.setAttribute('aria-label', localize('modernity.home.filterProjectsAria', "Filter projects"));
		const projectList = append(projectSection, $('.modernity-home-list'));

		const renderProjects = (query: string): void => {
			clearNode(projectList);
			const normalized = query.trim().toLowerCase();
			const filtered = projects.filter(project => !normalized
				|| project.name.toLowerCase().includes(normalized)
				|| project.modId.toLowerCase().includes(normalized)
				|| project.repositoryFullName?.toLowerCase().includes(normalized));
			if (!filtered.length) {
				const empty = append(projectList, $('.modernity-home-empty'));
				empty.appendChild(renderIcon(projects.length ? Codicon.search : Codicon.package));
				append(empty, $('span', {}, projects.length
					? localize('modernity.home.noMatches', "No matching projects")
					: localize('modernity.home.noProjects', "No projects yet")));
				return;
			}
			for (const project of filtered) {
				this.renderProject(projectList, project);
			}
		};
		renderProjects('');
		this.contentDisposables.add(addDisposableListener(search, 'input', () => renderProjects(search.value)));
	}

	private renderHeader(): void {
		const header = append(this.content, $('.modernity-home-header'));
		const title = append(header, $('.modernity-home-title'));
		append(title, $('.modernity-home-brand', {}, localize('modernity.home.brand', "Modernity")));
		append(title, $('h1', {}, localize('modernity.home.heading', "Your Projects")));
		const actions = append(header, $('.modernity-home-actions'));
		const refresh = this.createIconButton(actions, Codicon.refresh, localize('modernity.home.refresh', "Refresh Projects"));
		this.contentDisposables.add(addDisposableListener(refresh, 'click', () => void this.refresh()));
		const create = this.createButton(actions, Codicon.add, localize('modernity.home.create', "Create Project"), 'primary');
		this.contentDisposables.add(addDisposableListener(create, 'click', () => {
			void this.commandService.executeCommand(CREATE_MODERNITY_PROJECT_COMMAND);
		}));
	}

	private createSection(title: string, count: string): HTMLElement {
		const section = append(this.content, $('section.modernity-home-section'));
		const heading = append(section, $('.modernity-home-section-heading'));
		append(heading, $('h2', {}, title));
		append(heading, $('span.modernity-home-count', {}, count));
		return section;
	}

	private renderRecentProject(container: HTMLElement, recent: IRecentWorkspace | IRecentFolder): void {
		const resource = isRecentFolder(recent) ? recent.folderUri : recent.workspace.configPath;
		const row = append(container, $('.modernity-home-row'));
		const identity = append(row, $('.modernity-home-identity'));
		identity.appendChild(renderIcon(isRecentFolder(recent) ? Codicon.folder : Codicon.rootFolder));
		const text = append(identity, $('.modernity-home-row-text'));
		append(text, $('.modernity-home-row-name', {}, recent.label ?? basename(resource)));
		append(text, $('.modernity-home-row-detail', {}, resource.scheme === 'file' ? resource.fsPath : resource.toString()));
		const open = this.createButton(row, Codicon.goToFile, localize('modernity.home.open', "Open"), 'secondary');
		this.contentDisposables.add(addDisposableListener(open, 'click', () => {
			void this.hostService.openWindow(
				[isRecentFolder(recent) ? { folderUri: resource } : { workspaceUri: resource }],
				{ forceReuseWindow: true },
			);
		}));
	}

	private renderProject(container: HTMLElement, project: IModernityProjectSummary): void {
		const row = append(container, $('.modernity-home-row'));
		const identity = append(row, $('.modernity-home-identity'));
		identity.appendChild(renderIcon(Codicon.repo));
		const text = append(identity, $('.modernity-home-row-text'));
		append(text, $('.modernity-home-row-name', {}, project.name));
		append(text, $('.modernity-home-row-detail', {}, project.repositoryFullName ?? project.modId));

		const local = typeof project.checkoutPath === 'string';
		const repositoryReady = typeof project.repositoryFullName === 'string';
		const status = append(row, $(`.modernity-home-status${local ? '.local' : repositoryReady ? '.remote' : '.pending'}`));
		append(status, $('span.modernity-home-status-dot'));
		append(status, $('span', {}, local
			? localize('modernity.home.onMachine', "On This Mac")
			: repositoryReady
				? localize('modernity.home.checkoutRequired', "Checkout Required")
				: localize('modernity.home.repositoryPending', "Repository Pending")));

		const action = this.createButton(
			row,
			local ? Codicon.goToFile : Codicon.repoClone,
			local ? localize('modernity.home.open', "Open") : localize('modernity.home.checkout', "Checkout"),
			local ? 'secondary' : 'primary',
		);
		action.disabled = !local && !repositoryReady;
		this.contentDisposables.add(addDisposableListener(action, 'click', () => void this.openProject(project)));
	}

	private async openProject(project: IModernityProjectSummary): Promise<void> {
		if (project.checkoutPath) {
			await this.hostService.openWindow(
				[{ folderUri: URI.file(project.checkoutPath) }],
				{ forceReuseWindow: true },
			);
			return;
		}
		if (!project.repositoryFullName) {
			return;
		}
		const folders = await this.fileDialogService.showOpenDialog({
			canSelectFiles: false,
			canSelectFolders: true,
			canSelectMany: false,
			openLabel: localize('modernity.home.checkoutHere', "Checkout Here"),
			title: localize('modernity.home.checkoutDestination', "Select the Parent Folder for the Project"),
		});
		const destination = folders?.[0];
		if (!destination) {
			return;
		}
		try {
			const result = await this.progressService.withProgress({
				location: ProgressLocation.Dialog,
				title: localize('modernity.home.checkingOut', "Checking Out {0}", project.name),
				detail: localize('modernity.home.checkoutDetail', "Cloning and verifying the project."),
				cancellable: false,
				sticky: true,
			}, async progress => {
				const progressListener = this.projectService.onDidChangeProvisionProgress(update => {
					progress.report({ message: update.message });
				});
				try {
					return await this.projectService.checkoutProject({
						projectId: project.projectId,
						destinationPath: destination.fsPath,
					});
				} finally {
					progressListener.dispose();
				}
			});
			await this.hostService.openWindow(
				[{ folderUri: URI.file(result.projectPath) }],
				{ forceReuseWindow: true },
			);
		} catch (error) {
			this.notificationService.error(localize(
				'modernity.home.checkoutFailed',
				"Modernity could not check out the project: {0}",
				error instanceof Error ? error.message : String(error),
			));
		}
	}

	private createButton(
		container: HTMLElement,
		icon: ThemeIcon,
		label: string,
		style: 'primary' | 'secondary',
	): HTMLButtonElement {
		const button = append(container, $(`button.modernity-home-button.${style}`)) as HTMLButtonElement;
		button.type = 'button';
		button.appendChild(renderIcon(icon));
		append(button, $('span', {}, label));
		return button;
	}

	private createIconButton(container: HTMLElement, icon: ThemeIcon, label: string): HTMLButtonElement {
		const button = append(container, $('button.modernity-home-icon-button')) as HTMLButtonElement;
		button.type = 'button';
		button.title = label;
		button.setAttribute('aria-label', label);
		button.appendChild(renderIcon(icon));
		return button;
	}
}
