/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { URI } from '../../../../base/common/uri.js';
import { localize, localize2 } from '../../../../nls.js';
import { Categories } from '../../../../platform/action/common/actionCommonCategories.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { IDialogService, IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IModernityAuthService } from '../../../../platform/modernityAuth/common/modernityAuth.js';
import { IModernityProjectService } from '../../../../platform/modernityProject/common/modernityProject.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { IHostService } from '../../../services/host/browser/host.js';

class CreateModernityProjectAction extends Action2 {
	constructor() {
		super({
			id: 'workbench.action.createModernityProject',
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
