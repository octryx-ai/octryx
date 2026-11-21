// Project design trace sync workflows: run a workflow, schedule it as a task, update it; task actions are composed in.
import type { AdminDesignTraceSyncWorkflow, AdminDesignTraceSyncWorkflowCollection, AdminDesignTraceability } from "../types/projectQualityTypes.design";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type {
  PanelScheduler,
  PanelTaskRow,
} from "../components/taskTypes";
import type { UseAdminProjectDesignTraceArgs } from "./useAdminProjectDesignTrace.types";
import { createProjectDesignTraceSyncTaskActions } from "./projectDesignTraceSyncTaskActions";

type Args = UseAdminProjectDesignTraceArgs;
type CreatedSyncTask = { task: PanelTaskRow; scheduler: PanelScheduler };

async function runSyncWorkflow(args: Args, workflowId: string) {
  const {
    readJson,
    configuringProjectQuality,
    setAdminProjects,
    setConfiguringProjectQuality,
    setProjectQualityLoading,
    setProjectQualityError,
  } = args;
  if (!configuringProjectQuality) return;
  setProjectQualityLoading(true);
  setProjectQualityError(null);
  try {
    await readJson(
      `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-trace-sync-workflows/${workflowId}/run`,
      {
        method: "POST",
        body: JSON.stringify({ limit_per_repository: 30 }),
      },
    );
    const traceability = await readJson<AdminDesignTraceability>(
      `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-traceability`,
    );
    const applyToProject = (
      project: AdminProjectQuality,
    ): AdminProjectQuality =>
      project.id === configuringProjectQuality.id
        ? { ...project, design_traceability: traceability }
        : project;
    setAdminProjects((prev) => prev.map(applyToProject));
    setConfiguringProjectQuality((prev) =>
      prev ? applyToProject(prev) : prev,
    );
  } catch (error) {
    setProjectQualityError(
      error instanceof Error
        ? error.message
        : "Failed to run trace sync workflow",
    );
  } finally {
    setProjectQualityLoading(false);
  }
}

// The created task and scheduler replace any entry with the same id and go first.
function withCreatedSyncTask(project: AdminProjectQuality, created: CreatedSyncTask): AdminProjectQuality {
  return {
    ...project,
    design_trace_sync_tasks: [
      created.task,
      ...(project.design_trace_sync_tasks || []).filter(
        (item) => item.id !== created.task.id,
      ),
    ],
    design_trace_sync_schedulers: [
      created.scheduler,
      ...(project.design_trace_sync_schedulers || []).filter(
        (item) => item.id !== created.scheduler.id,
      ),
    ],
  };
}

async function createSyncWorkflowTask(args: Args, workflow: AdminDesignTraceSyncWorkflow) {
  const {
    readJson,
    configuringProjectQuality,
    setAdminProjects,
    setConfiguringProjectQuality,
    setProjectQualityLoading,
    setProjectQualityError,
  } = args;
  if (!configuringProjectQuality) return;
  const cronExpression = window.prompt(
    `Cron schedule for "${workflow.name}"`,
    "0 * * * *",
  );
  if (cronExpression === null) return;
  const trimmedCron = cronExpression.trim();
  if (!trimmedCron) {
    setProjectQualityError("Cron schedule is required");
    return;
  }
  setProjectQualityLoading(true);
  setProjectQualityError(null);
  try {
    const created = await readJson<CreatedSyncTask>(
      `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-trace-sync-workflows/${workflow.id}/create-task`,
      {
        method: "POST",
        body: JSON.stringify({
          task_name: `Trace Sync: ${workflow.name}`,
          task_description: workflow.description || "",
          cron_expression: trimmedCron,
          scheduler_name: `${workflow.name} Schedule`,
          scheduler_description: workflow.description || "",
          limit_per_repository: workflow.limit_per_repository,
          is_active: workflow.is_active,
        }),
      },
    );
    const applyToProject = (
      project: AdminProjectQuality,
    ): AdminProjectQuality =>
      project.id === configuringProjectQuality.id
        ? withCreatedSyncTask(project, created)
        : project;
    setAdminProjects((prev) => prev.map(applyToProject));
    setConfiguringProjectQuality((prev) =>
      prev ? applyToProject(prev) : prev,
    );
  } catch (error) {
    setProjectQualityError(
      error instanceof Error
        ? error.message
        : "Failed to create scheduled trace sync task",
    );
  } finally {
    setProjectQualityLoading(false);
  }
}

// The fields the workflow collection PUT accepts.
function syncWorkflowRequestItem(workflow: AdminDesignTraceSyncWorkflow) {
  return {
    id: workflow.id,
    name: workflow.name,
    description: workflow.description,
    source_kind: workflow.source_kind,
    target_type: workflow.target_type,
    mode: workflow.mode,
    is_active: workflow.is_active,
    providers: workflow.providers,
    match_rules: workflow.match_rules,
    limit_per_repository: workflow.limit_per_repository,
  };
}

async function updateSyncWorkflow(
  args: Args,
  workflowId: string,
  patch: Partial<AdminDesignTraceSyncWorkflow>,
) {
  const {
    readJson,
    configuringProjectQuality,
    setAdminProjects,
    setConfiguringProjectQuality,
    setProjectQualityLoading,
    setProjectQualityError,
  } = args;
  if (!configuringProjectQuality) return;
  setProjectQualityLoading(true);
  setProjectQualityError(null);
  try {
    const workflows = (
      configuringProjectQuality.design_trace_sync_workflows || []
    ).map((workflow) =>
      workflow.id === workflowId ? { ...workflow, ...patch } : workflow,
    );
    const workflowPayload =
      await readJson<AdminDesignTraceSyncWorkflowCollection>(
        `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-trace-sync-workflows`,
        {
          method: "PUT",
          body: JSON.stringify({ workflows: workflows.map(syncWorkflowRequestItem) }),
        },
      );
    const applyToProject = (
      project: AdminProjectQuality,
    ): AdminProjectQuality =>
      project.id === configuringProjectQuality.id
        ? {
            ...project,
            design_trace_sync_workflows: workflowPayload.items,
            design_trace_sync_templates: workflowPayload.templates,
          }
        : project;
    setAdminProjects((prev) => prev.map(applyToProject));
    setConfiguringProjectQuality((prev) =>
      prev ? applyToProject(prev) : prev,
    );
  } catch (error) {
    setProjectQualityError(
      error instanceof Error
        ? error.message
        : "Failed to update trace sync workflow",
    );
  } finally {
    setProjectQualityLoading(false);
  }
}

export function createProjectDesignTraceWorkflowActions(
  args: UseAdminProjectDesignTraceArgs,
) {
  const {
    handleRunProjectDesignTraceSyncTask,
    handleToggleProjectDesignTraceSyncScheduler,
    handleDeleteProjectDesignTraceSyncTask,
  } = createProjectDesignTraceSyncTaskActions(args);

  const handleRunProjectDesignTraceSyncWorkflow = (workflowId: string) =>
    runSyncWorkflow(args, workflowId);

  const handleCreateProjectDesignTraceSyncWorkflowTask = (
    workflow: AdminDesignTraceSyncWorkflow,
  ) => createSyncWorkflowTask(args, workflow);

  const handleUpdateProjectDesignTraceSyncWorkflow = (
    workflowId: string,
    patch: Partial<AdminDesignTraceSyncWorkflow>,
  ) => updateSyncWorkflow(args, workflowId, patch);

  return {
    handleRunProjectDesignTraceSyncWorkflow,
    handleCreateProjectDesignTraceSyncWorkflowTask,
    handleRunProjectDesignTraceSyncTask,
    handleToggleProjectDesignTraceSyncScheduler,
    handleDeleteProjectDesignTraceSyncTask,
    handleUpdateProjectDesignTraceSyncWorkflow,
  };
}
