import { useEffect, useState, type FormEvent } from "react";
import { AdminProjectsSummarySection } from "./AdminProjectsSummarySection";
import { WorkspaceSettingsPage } from "./projectsTab/WorkspaceSettingsPage";
import { WorkspaceSidePanel } from "./projectsTab/WorkspaceSidePanel";
import { WorkspaceCreateDrawer } from "./projectsTab/WorkspaceCreateDrawer";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import { pendingWorkspaceSettings, requestWorkspaceSettings, takeUrlWorkspaceSection } from "./projectsTab/workspaceSettingsLink";
import { useConfirmAction } from "./confirm/useConfirmAction";
import { useWorkspaceProblemCounts } from "./projectsTab/useWorkspaceProblemCounts";
import { useWorkspaceClasses } from "./projectsTab/useWorkspaceClasses";

type AdminProjectsTabProps = {
  ctx: Record<string, unknown>;
  isAdmin?: boolean;
};

type ReadJson = (url: string, init?: Record<string, unknown>) => Promise<unknown>;

// The list's own state: the create form, the last action's error and busy key, and the Workspace just created.
function useWorkspaceListState() {
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [showCreateDrawer, setShowCreateDrawer] = useState(false);
  const [projectActionError, setProjectActionError] = useState<string | null>(
    null,
  );
  const [projectActionLoading, setProjectActionLoading] = useState<
    string | null
  >(null);
  // After "Create workspace": a confirmation with a way into the new Workspace, and its row marked.
  const [created, setCreated] = useState<{ id: string; name: string } | null>(null);
  return {
    projectName, setProjectName, projectDescription, setProjectDescription, showCreateDrawer, setShowCreateDrawer,
    projectActionError, setProjectActionError, projectActionLoading, setProjectActionLoading, created, setCreated,
  };
}

type ListState = ReturnType<typeof useWorkspaceListState>;

// The open side panel, the list's Problems and Class columns, and a deep link to one Workspace's settings.
function useWorkspacePanel(adminProjects: unknown, handleOpenProjectQualityForm: unknown) {
  // A row opens the Workspace's essentials in a side panel; "Open settings" opens its full settings.
  const [panelId, setPanelId] = useState<string | null>(null);
  // The list's Problems column (one Admin › Problems call); refreshed when the list changes.
  const problemCounts = useWorkspaceProblemCounts(adminProjects);
  // The list's Class column: each Workspace's classification level (one call; platform admins).
  const workspaceClasses = useWorkspaceClasses(adminProjects);

  // A deep link (`…&workspace_id=<id>&section=<key>`) becomes a pending request before the list effect below takes it.
  useState(() => { takeUrlWorkspaceSection(); return null; });
  // A link from Work or Coding to one Workspace's settings section opens that Workspace's drawer.
  useEffect(() => {
    const requested = pendingWorkspaceSettings();
    const project = requested && Array.isArray(adminProjects)
      ? (adminProjects as AdminProjectQuality[]).find((entry) => entry.id === requested)
      : null;
    if (project && typeof handleOpenProjectQualityForm === "function") {
      // A link to one settings section keeps opening the settings at that section.
      handleOpenProjectQualityForm(project);
    }
  }, [adminProjects, handleOpenProjectQualityForm]);
  return { panelId, setPanelId, problemCounts, workspaceClasses };
}

// Reloading the list after an action, and running an action with its busy key and error.
function workspaceActionRunners(ctx: Record<string, any>, list: ListState) {
  const { readJson, setAdminProjects } = ctx;
  const { setProjectActionLoading, setProjectActionError } = list;
  const reloadProjects = async () => {
    if (
      typeof readJson !== "function" ||
      typeof setAdminProjects !== "function"
    ) {
      return;
    }
    const refreshed = (await readJson(
      "/admin/chat/api/panel/projects",
    )) as AdminProjectQuality[];
    setAdminProjects(refreshed);
  };

  const runProjectAction = async (
    actionKey: string,
    action: () => Promise<unknown>,
  ) => {
    setProjectActionLoading(actionKey);
    setProjectActionError(null);
    try {
      await action();
      await reloadProjects();
    } catch (error) {
      setProjectActionError(
        error instanceof Error ? error.message : "Workspace action failed.",
      );
    } finally {
      setProjectActionLoading(null);
    }
  };

  // Runs a confirmed action; a failure is thrown so the dialog shows it in place.
  const confirmedAction = async (action: () => Promise<unknown>) => {
    setProjectActionError(null);
    try {
      await action();
    } catch (error) {
      throw error instanceof Error ? error : new Error("Workspace action failed.");
    }
    await reloadProjects();
  };
  return { runProjectAction, confirmedAction };
}

type Runners = ReturnType<typeof workspaceActionRunners>;

function createProjectHandler(readJson: ReadJson, list: ListState, runProjectAction: Runners["runProjectAction"]) {
  const { projectName, projectDescription, setProjectActionError, setCreated, setProjectName, setProjectDescription,
    setShowCreateDrawer } = list;
  return async (event: FormEvent) => {
    event.preventDefault();
    const name = projectName.trim();
    if (!name) {
      setProjectActionError("Workspace name is required.");
      return;
    }
    setCreated(null);
    let createdId: string | null = null;
    // The drawer stays open and busy ("Creating…") until the list shows the new Workspace, so nobody clicks twice.
    await runProjectAction("create", async () => {
      const response = (await readJson("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: projectDescription.trim() || null,
          config: {},
        }),
      })) as { id?: unknown } | null;
      createdId = typeof response?.id === "string" ? response.id : null;
    });
    if (createdId) {
      setCreated({ id: createdId, name });
      setProjectName("");
      setProjectDescription("");
      setShowCreateDrawer(false);
    }
  };
}

type Ask = ReturnType<typeof useConfirmAction>["ask"];

// The row actions: archive and delete are confirmed in the app, default and restore run at once.
function workspaceRowActions(readJson: ReadJson, ask: Ask, { runProjectAction, confirmedAction }: Runners) {
  const handleArchiveProject = (project: AdminProjectQuality) =>
    ask({
      title: `Archive Workspace ${project.name}?`,
      // Reversible, so neutral; what differs from Delete is said in both dialogs.
      body: <p>Nobody can use it until it is restored. Its members, sources, workflows and history stay as they are,
        and Restore brings it back exactly as it was.</p>,
      confirmLabel: `Archive ${project.name}`,
      tone: "neutral",
      done: `Workspace ${project.name} archived.`,
      run: () => confirmedAction(() =>
        readJson(`/api/v1/projects/${encodeURIComponent(project.id)}/archive`, { method: "POST" })),
    });

  const handleMakeDefaultProject = (project: AdminProjectQuality) =>
    runProjectAction(`default:${project.id}`, () =>
      readJson(`/api/v1/projects/${encodeURIComponent(project.id)}/make-default`, {
        method: "POST",
      }),
    );

  const handleRestoreProject = (project: AdminProjectQuality) =>
    runProjectAction(`restore:${project.id}`, () =>
      readJson(`/api/v1/projects/${encodeURIComponent(project.id)}/restore`, {
        method: "POST",
      }),
    );

  const handleDeleteProject = (project: AdminProjectQuality) =>
    ask({
      title: `Delete Workspace ${project.name}?`,
      body: (
        <>
          <p>Nobody can use it any more. In addition to archiving, its Knowledge sources are paused with their automatic
            sync switched off, and its workflow definitions are archived.</p>
          <p>Its history stays for the audit. Restore brings the Workspace back, but not its sources' sync or its
            workflows: they have to be switched on again one by one. To keep everything as it is, archive instead.</p>
        </>
      ),
      confirmLabel: `Delete ${project.name}`,
      done: `Workspace ${project.name} deleted.`,
      run: () => confirmedAction(() =>
        readJson(`/api/v1/projects/${encodeURIComponent(project.id)}`, { method: "DELETE" })),
    });
  return { handleArchiveProject, handleMakeDefaultProject, handleRestoreProject, handleDeleteProject };
}

function WorkspaceCreatedNotice({ created, onOpen }: { created: { id: string; name: string }; onOpen: () => void }) {
  return (
    <div className="admin-panel__success admin-projects__created" role="status" data-testid="workspace-created">
      <span>Workspace <strong>{created.name}</strong> created.</span>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onOpen}>
        Open the workspace
      </button>
    </div>
  );
}

function WorkspaceCreate({ list, onSubmit }: { list: ListState; onSubmit: (event: FormEvent) => void }) {
  return (
    <WorkspaceCreateDrawer
      name={list.projectName}
      description={list.projectDescription}
      error={list.projectActionError}
      creating={list.projectActionLoading === "create"}
      setName={list.setProjectName}
      setDescription={list.setProjectDescription}
      onSubmit={onSubmit}
      onClose={() => list.setShowCreateDrawer(false)}
    />
  );
}

export function AdminProjectsTab({ ctx, isAdmin = false }: AdminProjectsTabProps) {
  const { adminProjects, handleOpenProjectQualityForm, readJson, configuringProjectQuality, closeProjectQualityForm } = ctx as Record<string, any>;
  const list = useWorkspaceListState();
  const { projectActionError, showCreateDrawer, created } = list;
  // Archive and delete are confirmed in the app, naming the Workspace, with a message afterwards.
  const { ask, dialog, notice } = useConfirmAction();
  const { panelId, setPanelId, problemCounts, workspaceClasses } = useWorkspacePanel(adminProjects, handleOpenProjectQualityForm);
  const runners = workspaceActionRunners(ctx as Record<string, any>, list);
  const handleCreateProject = createProjectHandler(readJson, list, runners.runProjectAction);
  const rowActions = workspaceRowActions(readJson, ask, runners);

  if (configuringProjectQuality) {
    const project = configuringProjectQuality as AdminProjectQuality;
    return <WorkspaceSettingsPage ctx={ctx} project={project} isAdmin={isAdmin} onBack={() => closeProjectQualityForm?.()} />;
  }

  const panelProject = panelId ? (adminProjects as AdminProjectQuality[] | undefined)?.find((entry) => entry.id === panelId) ?? null : null;
  const openSettings = (project: AdminProjectQuality) => {
    setPanelId(null);
    handleOpenProjectQualityForm?.(project);
  };

  return (
    <div className="admin-projects">
      {projectActionError && !showCreateDrawer ? (
        <div className="admin-panel__error">{projectActionError}</div>
      ) : null}
      {notice}
      {created ? <WorkspaceCreatedNotice created={created} onOpen={() => setPanelId(created.id)} /> : null}
      <AdminProjectsSummarySection
        adminProjects={adminProjects}
        handleOpenProjectQualityForm={(project) => setPanelId(project.id)}
        projectActionLoading={list.projectActionLoading}
        onCreateWorkspace={() => {
          list.setProjectActionError(null);
          list.setShowCreateDrawer(true);
        }}
        onArchiveProject={rowActions.handleArchiveProject}
        onRestoreProject={rowActions.handleRestoreProject}
        onMakeDefaultProject={rowActions.handleMakeDefaultProject}
        onDeleteProject={rowActions.handleDeleteProject}
        highlightedProjectId={panelId ?? created?.id ?? null}
        problemCounts={problemCounts}
        workspaceClasses={workspaceClasses}
        onOpenClassification={(project) => {
          // Rules, with the classification card on top, where the Workspace's level is set.
          requestWorkspaceSettings(project.id, "rules", "classification");
          openSettings(project);
        }}
      />
      {panelProject ? (
        <WorkspaceSidePanel project={panelProject} problems={problemCounts ? problemCounts[panelProject.id] ?? { total: 0, problem: 0 } : null}
          onClose={() => setPanelId(null)} onOpenSettings={() => openSettings(panelProject)} />
      ) : null}
      {dialog}
      {showCreateDrawer ? <WorkspaceCreate list={list} onSubmit={handleCreateProject} /> : null}
    </div>
  );
}
