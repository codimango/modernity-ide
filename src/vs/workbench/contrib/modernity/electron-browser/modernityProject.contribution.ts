/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { basename } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Categories } from '../../../../platform/action/common/actionCommonCategories.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IModernityAuthService } from '../../../../platform/modernityAuth/common/modernityAuth.js';
import { IModernityProjectService, IModernityProjectSummary } from '../../../../platform/modernityProject/common/modernityProject.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService, IQuickPickItem, QuickPickInput } from '../../../../platform/quickinput/common/quickInput.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceContextService, WorkbenchState } from '../../../../platform/workspace/common/workspace.js';
import { isRecentFolder, IRecentlyOpened, IWorkspacesService } from '../../../../platform/workspaces/common/workspaces.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IHostService } from '../../../services/host/browser/host.js';
import { ModernityHomeInput, ModernityHomePage } from './modernityHome.js';

const OPEN_MODERNITY_PROJECT_COMMAND = 'workbench.action.openModernityProject';
const CREATE_MODERNITY_PROJECT_COMMAND = 'workbench.action.createModernityProject';
const OPEN_MODERNITY_HOME_COMMAND = 'workbench.action.openModernityHome';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(
		ModernityHomePage,
		ModernityHomePage.ID,
		localize('modernity.home.editorLabel', "Modernity"),
	),
	[new SyncDescriptor(ModernityHomeInput)],
);

type ModernityProjectPickKind = 'create' | 'recentFolder' | 'recentWorkspace' | 'project';

interface IModernityProjectPick extends IQuickPickItem {
	readonly kind: ModernityProjectPickKind;
	readonly folderUri?: URI;
	readonly workspaceUri?: URI;
	readonly project?: IModernityProjectSummary;
}

async function showModernityProjectPicker(accessor: ServicesAccessor): Promise<void> {
	const commandService = accessor.get(ICommandService);
	const fileDialogService = accessor.get(IFileDialogService);
	const hostService = accessor.get(IHostService);
	const notificationService = accessor.get(INotificationService);
	const progressService = accessor.get(IProgressService);
	const projectService = accessor.get(IModernityProjectService);
	const quickInputService = accessor.get(IQuickInputService);
	const workspacesService = accessor.get(IWorkspacesService);

	let projects: readonly IModernityProjectSummary[];
	let recentlyOpened: IRecentlyOpened;
	try {
		[projects, recentlyOpened] = await Promise.all([
			projectService.listProjects(),
			workspacesService.getRecentlyOpened(),
		]);
	} catch (error) {
		notificationService.error(localize(
			'modernity.projects.loadFailed',
			"Modernity could not load your projects: {0}",
			error instanceof Error ? error.message : String(error),
		));
		return;
	}

	const picks: QuickPickInput<IModernityProjectPick>[] = [];
	if (recentlyOpened.workspaces.length) {
		picks.push({ type: 'separator', label: localize('modernity.projects.recent', "Recent") });
		for (const recent of recentlyOpened.workspaces.slice(0, 8)) {
			if (isRecentFolder(recent)) {
				picks.push({
					kind: 'recentFolder',
					label: recent.label ?? basename(recent.folderUri),
					detail: recent.folderUri.scheme === 'file' ? recent.folderUri.fsPath : recent.folderUri.toString(),
					folderUri: recent.folderUri,
					iconClasses: ThemeIcon.asClassNameArray(Codicon.folder),
				});
			} else {
				picks.push({
					kind: 'recentWorkspace',
					label: recent.label ?? basename(recent.workspace.configPath),
					detail: recent.workspace.configPath.scheme === 'file' ? recent.workspace.configPath.fsPath : recent.workspace.configPath.toString(),
					workspaceUri: recent.workspace.configPath,
					iconClasses: ThemeIcon.asClassNameArray(Codicon.rootFolder),
				});
			}
		}
	}

	picks.push({ type: 'separator', label: localize('modernity.projects.yours', "Your Projects") });
	for (const project of projects) {
		const repositoryReady = typeof project.repositoryFullName === 'string';
		picks.push({
			kind: 'project',
			label: project.name,
			description: project.checkoutPath
				? localize('modernity.projects.onMachine', "On This Mac")
				: repositoryReady
					? localize('modernity.projects.checkoutRequired', "Checkout Required")
					: localize('modernity.projects.repositoryPending', "Repository Not Ready"),
			detail: project.checkoutPath ?? project.repositoryFullName ?? project.modId,
			project,
			disabled: !repositoryReady,
			iconClasses: ThemeIcon.asClassNameArray(project.checkoutPath ? Codicon.folderOpened : Codicon.repoClone),
		});
	}
	if (!projects.length) {
		picks.push({
			kind: 'project',
			label: localize('modernity.projects.none', "No Projects Yet"),
			description: localize('modernity.projects.createFirst', "Create your first project below"),
			disabled: true,
		});
	}
	picks.push(
		{ type: 'separator', label: localize('modernity.projects.actions', "Actions") },
		{
			kind: 'create',
			label: localize('modernity.projects.create', "Create New Project"),
			description: localize('modernity.projects.createDescription', "NeoForge 26.2"),
			iconClasses: ThemeIcon.asClassNameArray(Codicon.add),
		},
	);

	const selected = await quickInputService.pick(picks, {
		title: localize('modernity.projects.title', "Open Modernity Project"),
		placeHolder: localize('modernity.projects.placeholder', "Select a recent project, cloud project, or create a new one"),
		matchOnDescription: true,
		matchOnDetail: true,
	});
	if (!selected) {
		return;
	}
	if (selected.kind === 'create') {
		await commandService.executeCommand(CREATE_MODERNITY_PROJECT_COMMAND);
		return;
	}
	if (selected.folderUri) {
		await hostService.openWindow([{ folderUri: selected.folderUri }], { forceReuseWindow: true });
		return;
	}
	if (selected.workspaceUri) {
		await hostService.openWindow([{ workspaceUri: selected.workspaceUri }], { forceReuseWindow: true });
		return;
	}
	const project = selected.project;
	if (!project) {
		return;
	}
	if (project.checkoutPath) {
		await hostService.openWindow([{ folderUri: URI.file(project.checkoutPath) }], { forceReuseWindow: true });
		return;
	}

	const folders = await fileDialogService.showOpenDialog({
		canSelectFiles: false,
		canSelectFolders: true,
		canSelectMany: false,
		openLabel: localize('modernity.projects.checkoutDestinationButton', "Checkout Here"),
		title: localize('modernity.projects.checkoutDestinationTitle', "Select the Parent Folder for the Project"),
	});
	const destination = folders?.[0];
	if (!destination) {
		return;
	}

	try {
		const result = await progressService.withProgress({
			location: ProgressLocation.Dialog,
			title: localize('modernity.projects.checkoutProgressTitle', "Checking Out {0}", project.name),
			detail: localize('modernity.projects.checkoutProgressDetail', "Cloning and verifying the project."),
			cancellable: false,
			sticky: true,
		}, async progress => {
			const progressListener = projectService.onDidChangeProvisionProgress(update => {
				progress.report({ message: update.message });
			});
			try {
				return await projectService.checkoutProject({
					projectId: project.projectId,
					destinationPath: destination.fsPath,
				});
			} finally {
				progressListener.dispose();
			}
		});
		notificationService.info(localize('modernity.projects.checkoutSuccess', "Checked out {0}.", project.name));
		await hostService.openWindow([{ folderUri: URI.file(result.projectPath) }], { forceReuseWindow: true });
	} catch (error) {
		notificationService.error(localize(
			'modernity.projects.checkoutFailed',
			"Modernity could not check out the project: {0}",
			error instanceof Error ? error.message : String(error),
		));
	}
}

class OpenModernityProjectAction extends Action2 {
	constructor() {
		super({
			id: OPEN_MODERNITY_PROJECT_COMMAND,
			title: localize2('modernity.openProject', 'Open Modernity Project'),
			category: Categories.File,
			f1: true,
			menu: {
				id: MenuId.MenubarFileMenu,
				group: '2_open',
				order: 4,
			},
			precondition: ContextKeyExpr.equals('modernity.authenticated', true),
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return showModernityProjectPicker(accessor);
	}
}

class OpenModernityHomeAction extends Action2 {
	constructor() {
		super({
			id: OPEN_MODERNITY_HOME_COMMAND,
			title: localize2('modernity.openHome', 'Open Modernity Home'),
			category: Categories.File,
			f1: true,
			precondition: ContextKeyExpr.equals('modernity.authenticated', true),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const editorService = accessor.get(IEditorService);
		const instantiationService = accessor.get(IInstantiationService);
		await editorService.openEditor(
			instantiationService.createInstance(ModernityHomeInput),
			{ pinned: true },
		);
	}
}

class CreateModernityProjectAction extends Action2 {
	constructor() {
		super({
			id: CREATE_MODERNITY_PROJECT_COMMAND,
			title: localize2('modernity.createProject', 'Create Modernity Project'),
			category: Categories.File,
			f1: true,
			menu: {
				id: MenuId.MenubarFileMenu,
				group: '1_new',
				order: 3,
			},
			precondition: ContextKeyExpr.equals('modernity.authenticated', true),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const quickInputService = accessor.get(IQuickInputService);
		const fileDialogService = accessor.get(IFileDialogService);
		const dialogService = accessor.get(IDialogService);
		const authService = accessor.get(IModernityAuthService);
		const openerService = accessor.get(IOpenerService);
		const projectService = accessor.get(IModernityProjectService);
		const progressService = accessor.get(IProgressService);
		const notificationService = accessor.get(INotificationService);
		const hostService = accessor.get(IHostService);

		try {
			const installations = await authService.getGithubInstallations();
			if (!installations.items.some(installation => installation.status === 'active')) {
				const setup = await authService.startGithubInstallation();
				if (setup.installation?.status !== 'active') {
					await openerService.open(URI.parse(setup.authorizationUrl), { openExternal: true });
					const { confirmed } = await dialogService.confirm({
						message: localize('modernity.createProject.githubAccessTitle', "Finish GitHub Repository Access"),
						detail: localize('modernity.createProject.githubAccessDetail', "Approve the Modernity GitHub App in your browser, then return here and continue."),
						primaryButton: localize('modernity.createProject.githubAccessContinue', "Continue"),
						cancelButton: localize('modernity.createProject.githubAccessCancel', "Cancel"),
					});
					if (!confirmed) {
						return;
					}
					const refreshed = await authService.getGithubInstallations();
					if (!refreshed.items.some(installation => installation.status === 'active')) {
						notificationService.warn(localize('modernity.createProject.githubAccessPending', "GitHub repository access is not active yet. Finish the browser setup and try again."));
						return;
					}
				}
			}
		} catch (error) {
			notificationService.error(localize(
				'modernity.createProject.githubAccessFailed',
				"Modernity could not start GitHub repository setup: {0}",
				error instanceof Error ? error.message : String(error),
			));
			return;
		}

		const name = await quickInputService.input({
			title: localize('modernity.createProject.nameTitle', "Create Modernity Project"),
			prompt: localize('modernity.createProject.namePrompt', "Project name"),
			placeHolder: localize('modernity.createProject.namePlaceholder', "My Awesome Mod"),
			validateInput: async value => value.trim()
				? undefined
				: localize('modernity.createProject.nameRequired', "Enter a project name."),
		});
		if (!name) {
			return;
		}

		const suggestedRepository = name.trim().toLowerCase()
			.replace(/[^a-z0-9._-]+/g, '-')
			.replace(/^-+|-+$/g, '');
		const repositoryName = await quickInputService.input({
			title: localize('modernity.createProject.repositoryTitle', "GitHub Repository"),
			prompt: localize('modernity.createProject.repositoryPrompt', "Repository name"),
			value: suggestedRepository,
			validateInput: async value => /^[A-Za-z0-9._-]{1,100}$/.test(value.trim()) && value.trim() !== '.' && value.trim() !== '..'
				? undefined
				: localize('modernity.createProject.repositoryInvalid', "Use letters, numbers, periods, hyphens, or underscores."),
		});
		if (!repositoryName) {
			return;
		}

		const template = await quickInputService.pick([
			{
				label: localize('modernity.createProject.neoforgeTemplate', "NeoForge 26.2"),
				description: localize('modernity.createProject.neoforgeTemplateDescription', "Minecraft 26.2, Java 25, Gradle 9.2.1"),
			},
		], {
			title: localize('modernity.createProject.templateTitle', "Project Template"),
			placeHolder: localize('modernity.createProject.templatePlaceholder', "Select a template"),
		});
		if (!template) {
			return;
		}

		const folders = await fileDialogService.showOpenDialog({
			canSelectFiles: false,
			canSelectFolders: true,
			canSelectMany: false,
			openLabel: localize('modernity.createProject.destinationButton', "Use This Folder"),
			title: localize('modernity.createProject.destinationTitle', "Select the Parent Folder for Your Project"),
		});
		const destination = folders?.[0];
		if (!destination) {
			return;
		}

		try {
			const result = await progressService.withProgress({
				location: ProgressLocation.Dialog,
				title: localize('modernity.createProject.progressTitle', "Creating {0}", name.trim()),
				detail: localize('modernity.createProject.progressDetail', "NeoForge 26.2 project setup may take several minutes."),
				cancellable: false,
				sticky: true,
			}, async progress => {
				const progressListener = projectService.onDidChangeProvisionProgress(update => {
					progress.report({ message: update.message });
				});
				try {
					return await projectService.createProject({
						name: name.trim(),
						repositoryName: repositoryName.trim(),
						destinationPath: destination.fsPath,
					});
				} finally {
					progressListener.dispose();
				}
			});

			notificationService.info(localize(
				'modernity.createProject.success',
				"Created {0} and published it to GitHub.",
				name.trim(),
			));
			await hostService.openWindow([{ folderUri: URI.file(result.projectPath) }]);
		} catch (error) {
			notificationService.error(localize(
				'modernity.createProject.failed',
				"Modernity could not create the project: {0}",
				error instanceof Error ? error.message : String(error),
			));
		}
	}
}

registerAction2(CreateModernityProjectAction);
registerAction2(OpenModernityProjectAction);
registerAction2(OpenModernityHomeAction);

class ModernityProjectStartupContribution extends Disposable implements IWorkbenchContribution {
	static readonly ID = 'workbench.contrib.modernityProjectStartup';

	private shown = false;

	constructor(
		@IModernityAuthService private readonly authService: IModernityAuthService,
		@IEditorService private readonly editorService: IEditorService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@IWorkspaceContextService private readonly workspaceContextService: IWorkspaceContextService,
	) {
		super();
		if (this.workspaceContextService.getWorkbenchState() !== WorkbenchState.EMPTY) {
			return;
		}
		this._register(this.authService.onDidChangeState(state => {
			if (state.status === 'signedIn') {
				void this.show();
			}
		}));
		void this.authService.getState().then(state => {
			if (state.status === 'signedIn') {
				void this.show();
			}
		}, () => undefined);
	}

	private async show(): Promise<void> {
		if (this.shown || this.workspaceContextService.getWorkbenchState() !== WorkbenchState.EMPTY) {
			return;
		}
		this.shown = true;
		await this.editorService.openEditor(
			this.instantiationService.createInstance(ModernityHomeInput),
			{ pinned: false },
		);
	}
}

registerWorkbenchContribution2(
	ModernityProjectStartupContribution.ID,
	ModernityProjectStartupContribution,
	WorkbenchPhase.AfterRestored,
);
