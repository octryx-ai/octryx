import type { AdminDesignTraceSyncWorkflow } from "../types/projectQualityTypes.design";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type { UseAdminProjectDesignTraceArgs } from "./useAdminProjectDesignTrace.types";

type CustomWorkflowAnswers = { workflowId: string; name: string; sourceKind: string; targetType: string };

// Asks for the new workflow's id, name, source kind and target type; null when any prompt is cancelled or the id is empty.
function promptCustomWorkflow(setProjectQualityError: (error: string | null) => void): CustomWorkflowAnswers | null {
  const id = window.prompt("Workflow id", "custom_release_scan");
  if (id === null) return null;
  const workflowId = id.trim();
  if (!workflowId) {
    setProjectQualityError("Workflow id is required");
    return null;
  }
  const name = window.prompt("Workflow name", "Custom Release Scan");
  if (name === null) return null;
  const sourceKind = window.prompt(
    "Source kind (release, checkpoint)",
    "release",
  );
  if (sourceKind === null) return null;
  const targetType = window.prompt(
    "Target type (release, checkpoint)",
    sourceKind.trim() || "release",
  );
  if (targetType === null) return null;
  return { workflowId, name, sourceKind, targetType };
}

function customWorkflowBody({ workflowId, name, sourceKind, targetType }: CustomWorkflowAnswers) {
  return JSON.stringify({
    id: workflowId,
    name: name.trim() || workflowId,
    description: "",
    source_kind: sourceKind.trim() || "release",
    target_type: targetType.trim() || sourceKind.trim() || "release",
    mode: "suggest",
    is_active: true,
    providers: ["github", "bitbucket", "gitlab"],
    match_rules: ["artifact_tokens", "task_titles"],
    limit_per_repository: 30,
  });
}

function withCreatedWorkflow(
  project: AdminProjectQuality,
  projectId: string,
  created: AdminDesignTraceSyncWorkflow,
): AdminProjectQuality {
  return project.id === projectId
    ? {
        ...project,
        design_trace_sync_custom_templates: [
          created,
          ...(project.design_trace_sync_custom_templates || []).filter(
            (item) => item.id !== created.id,
          ),
        ],
        design_trace_sync_workflows: [
          created,
          ...(project.design_trace_sync_workflows || []).filter(
            (item) => item.id !== created.id,
          ),
        ],
      }
    : project;
}

function withoutWorkflow(
  project: AdminProjectQuality,
  projectId: string,
  workflow: AdminDesignTraceSyncWorkflow,
): AdminProjectQuality {
  return project.id === projectId
    ? {
        ...project,
        design_trace_sync_custom_templates: (
          project.design_trace_sync_custom_templates || []
        ).filter((item) => item.id !== workflow.id),
        design_trace_sync_workflows: (
          project.design_trace_sync_workflows || []
        ).filter((item) => item.id !== workflow.id),
      }
    : project;
}

async function createCustomWorkflow(args: UseAdminProjectDesignTraceArgs) {
  const {
    readJson,
    configuringProjectQuality,
    setAdminProjects,
    setConfiguringProjectQuality,
    setProjectQualityLoading,
    setProjectQualityError,
  } = args;
  if (!configuringProjectQuality) return;
  const answers = promptCustomWorkflow(setProjectQualityError);
  if (!answers) return;
  setProjectQualityLoading(true);
  setProjectQualityError(null);
  try {
    const created = await readJson<AdminDesignTraceSyncWorkflow>(
      `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-trace-sync-templates`,
      { method: "POST", body: customWorkflowBody(answers) },
    );
    const applyToProject = (project: AdminProjectQuality) =>
      withCreatedWorkflow(project, configuringProjectQuality.id, created);
    setAdminProjects((prev) => prev.map(applyToProject));
    setConfiguringProjectQuality((prev) =>
      prev ? applyToProject(prev) : prev,
    );
  } catch (error) {
    setProjectQualityError(
      error instanceof Error
        ? error.message
        : "Failed to create custom trace sync workflow",
    );
  } finally {
    setProjectQualityLoading(false);
  }
}

async function deleteCustomWorkflow(
  args: UseAdminProjectDesignTraceArgs,
  workflow: AdminDesignTraceSyncWorkflow,
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
  if (!window.confirm(`Delete custom workflow "${workflow.name}"?`)) return;
  setProjectQualityLoading(true);
  setProjectQualityError(null);
  try {
    await readJson(
      `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-trace-sync-templates/${workflow.id}`,
      { method: "DELETE" },
    );
    const applyToProject = (project: AdminProjectQuality) =>
      withoutWorkflow(project, configuringProjectQuality.id, workflow);
    setAdminProjects((prev) => prev.map(applyToProject));
    setConfiguringProjectQuality((prev) =>
      prev ? applyToProject(prev) : prev,
    );
  } catch (error) {
    setProjectQualityError(
      error instanceof Error
        ? error.message
        : "Failed to delete custom trace sync workflow",
    );
  } finally {
    setProjectQualityLoading(false);
  }
}

export function createProjectDesignTraceCustomWorkflowActions(
  args: UseAdminProjectDesignTraceArgs,
) {
  const handleCreateCustomProjectDesignTraceSyncWorkflow = () =>
    createCustomWorkflow(args);

  const handleDeleteCustomProjectDesignTraceSyncWorkflow = (
    workflow: AdminDesignTraceSyncWorkflow,
  ) => deleteCustomWorkflow(args, workflow);

  return {
    handleCreateCustomProjectDesignTraceSyncWorkflow,
    handleDeleteCustomProjectDesignTraceSyncWorkflow,
  };
}
