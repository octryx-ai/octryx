// Action form handlers: open the form for a new or stored Action, close it, and save it.
import type { FormEvent } from "react";
import { GUIDED_TASK_TYPE } from "../components/automation/actionGuidedPath";
import { reservedKeyConflict } from "../components/automation/actionGuidedConfig";
import { type GuidedSubmission } from "../components/automation/actionGuidedModel";
import type { PanelTaskRow } from "../components/taskTypes";
import type { UseAdminTaskWorkflowArgs } from "./useAdminTaskWorkflow.types";

type TaskFields = Record<string, unknown>;

// Parses the config JSON and adds the fields that have their own form controls.
function buildTaskConfig(
  taskFormConfig: string,
  taskFormMaxIterations: number,
  taskFormAgentDefId: string,
) {
  let config: Record<string, unknown> = {};
  try {
    config = JSON.parse(taskFormConfig || "{}") as Record<string, unknown>;
  } catch {
    throw new Error("Config must be valid JSON");
  }
  if (taskFormMaxIterations && Number(taskFormMaxIterations) > 0) {
    config.max_iterations = Number(taskFormMaxIterations);
  }
  if (taskFormAgentDefId) {
    config.agent_definition_id = taskFormAgentDefId;
  } else {
    delete config.agent_definition_id;
  }
  return config;
}

async function persistTask(
  { readJson, setTasks, editingTask }: UseAdminTaskWorkflowArgs,
  fields: TaskFields,
  guided?: GuidedSubmission,
) {
  if (editingTask) {
    // The form has no activation control, so an edit leaves the active/paused state as it is.
    // Schedules belong to the Scheduler API, never to the Action form.
    const updated = await readJson<PanelTaskRow>(
      `/admin/chat/api/panel/tasks/${editingTask.id}`,
      {
        method: "PUT",
        body: JSON.stringify(fields),
      },
    );
    setTasks((prev) =>
      prev.map((task) => (task.id === editingTask.id ? updated : task)),
    );
  } else {
    // A new Action starts active.
    const created = await readJson<PanelTaskRow>(
      "/admin/chat/api/panel/tasks",
      {
        method: "POST",
        body: JSON.stringify({
          ...fields,
          ...(guided?.projectId ? { project_id: guided.projectId } : {}),
          is_active: true,
        }),
      },
    );
    setTasks((prev) => [created, ...prev]);
  }
}

// Fills the form from a stored Action, or resets it for a new one, and opens it.
function fillTaskForm(args: UseAdminTaskWorkflowArgs, task?: PanelTaskRow) {
  args.setEditingTask(task || null);
  args.setTaskFormName(task?.name || "");
  args.setTaskFormDesc(task?.description || "");
  const cfg = task?.config || {};
  const { max_iterations, agent_definition_id, ...restCfg } = cfg as Record<
    string,
    unknown
  >;
  args.setTaskFormConfig(
    Object.keys(restCfg).length ? JSON.stringify(restCfg, null, 2) : "{}",
  );
  args.setTaskFormMaxIterations(
    typeof max_iterations === "number" ? max_iterations : 32,
  );
  args.setTaskFormAgentDefId(
    typeof agent_definition_id === "string" ? agent_definition_id : "",
  );
  // A new Action starts without a workspace; an edit shows the stored one, read-only.
  args.setTaskFormProjectId(
    typeof task?.project_id === "string" ? task.project_id : "",
  );
  args.setTaskFormError(null);
  args.setShowTaskForm(true);
}

function buildTaskFields(
  args: UseAdminTaskWorkflowArgs,
  guided?: GuidedSubmission,
): TaskFields {
  const config = buildTaskConfig(
    args.taskFormConfig,
    args.taskFormMaxIterations,
    args.taskFormAgentDefId,
  );
  return {
    name: args.taskFormName,
    description: args.taskFormDesc,
    // A guided Action submits the guided type and its agent's own permission-mode key (still validated). Any other
    // Action omits both, so its stored type and run mode are kept.
    ...(guided ? { task_type: GUIDED_TASK_TYPE, agent_type: guided.agentType } : {}),
    config,
    // Only a guided save may set the binding, and only when the form decided to send it
    // (new Action, or an explicit conversion). Otherwise the field is omitted and kept as stored.
    ...(guided?.dispatchBinding
      ? { dispatch_binding: guided.dispatchBinding }
      : {}),
  };
}

export function createAdminTaskFormActions(args: UseAdminTaskWorkflowArgs) {
  const {
    setShowTaskForm,
    setEditingTask,
    taskFormConfig,
    setTaskFormError,
    setTaskFormLoading,
  } = args;

  const handleOpenTaskForm = (task?: PanelTaskRow) => fillTaskForm(args, task);

  const closeTaskForm = () => {
    setShowTaskForm(false);
    setEditingTask(null);
  };

  // A guided save passes the form's gate and is refused here too when it is not runnable,
  // not only by the disabled button. Config keys owned by their own fields are refused in the JSON
  // instead of being silently replaced.
  const handleSaveTask = async (
    event: FormEvent,
    guided?: GuidedSubmission,
  ) => {
    event.preventDefault();
    setTaskFormError(null);
    if (guided && !guided.canSubmit) {
      setTaskFormError(guided.blocker);
      return;
    }
    const conflict = reservedKeyConflict(taskFormConfig);
    if (conflict) {
      setTaskFormError(conflict);
      return;
    }
    setTaskFormLoading(true);
    try {
      await persistTask(args, buildTaskFields(args, guided), guided);
      closeTaskForm();
    } catch (err) {
      setTaskFormError(err instanceof Error ? err.message : "Failed");
    } finally {
      setTaskFormLoading(false);
    }
  };

  return { closeTaskForm, handleOpenTaskForm, handleSaveTask };
}
