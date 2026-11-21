// The Action form's sources (permission modes, the agent's execution source, the conversion opt-in)
// and what the form shows and sends, derived from them.
import { useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { bindingToSend } from "./automation/actionDispatchBinding";
import { actionPath, compatibleAgents, type WorkspaceOption } from "./automation/actionGuidedPath";
import { executionView, instructionCheck } from "./automation/actionGuidedExecution";
import { guidedConfigView, withConfigKey } from "./automation/actionGuidedConfig";
import { guidedSubmission, type GuidedSubmission } from "./automation/actionGuidedModel";
import { permissionModeChoice } from "./automation/permissionModeCatalog";
import { useAgentExecutionSource } from "./automation/useAgentExecutionSource";
import { usePermissionModeCatalog } from "./automation/usePermissionModeCatalog";
import type { PanelAgentRow, PanelTaskRow } from "./taskTypes";

export type AdminTaskFormProps = {
  showTaskForm: boolean;
  editingTask: PanelTaskRow | null;
  taskFormName: string;
  setTaskFormName: Dispatch<SetStateAction<string>>;
  taskFormDesc: string;
  setTaskFormDesc: Dispatch<SetStateAction<string>>;
  taskFormAgentDefId: string;
  setTaskFormAgentDefId: Dispatch<SetStateAction<string>>;
  taskFormProjectId?: string;
  setTaskFormProjectId?: Dispatch<SetStateAction<string>>;
  projects?: WorkspaceOption[];
  panelAgents: PanelAgentRow[];
  taskFormMaxIterations: number | "";
  setTaskFormMaxIterations: Dispatch<SetStateAction<number | "">>;
  taskFormConfig: string;
  setTaskFormConfig: Dispatch<SetStateAction<string>>;
  taskFormError: string | null;
  taskFormLoading: boolean;
  onSaveTask: (event: FormEvent, guided?: GuidedSubmission) => void | Promise<void>;
  onCloseTaskForm: () => void;
};

export function workspaceLabel(projects: WorkspaceOption[], projectId: string | null | undefined): string {
  if (!projectId) return "Not reported by this server";
  return projects.find((project) => project.id === projectId)?.name ?? "A workspace you cannot see";
}

export function useTaskFormSources({ showTaskForm, editingTask, taskFormAgentDefId }: AdminTaskFormProps) {
  const { catalog, retry } = usePermissionModeCatalog(showTaskForm);
  // New Actions are one guided "Run an agent" path; existing ones the guided form cannot
  // represent keep their type, run mode and agent (only name, description and configuration change).
  const path = actionPath(editingTask);
  const guided = path.kind === "guided";
  const { lookup, retry: retryExecution } = useAgentExecutionSource(
    showTaskForm && guided ? taskFormAgentDefId : "",
  );
  // The explicit conversion opt-in belongs to one opening of the form for one Action; closing,
  // reopening or switching the Action resets it, so it never carries over to another save.
  const [conversion, setConversion] = useState({ task: editingTask, shown: showTaskForm, convert: false });
  if (conversion.task !== editingTask || conversion.shown !== showTaskForm) {
    setConversion({ task: editingTask, shown: showTaskForm, convert: false });
  }
  const convertBinding =
    conversion.convert && conversion.task === editingTask && conversion.shown === showTaskForm;
  const setConvertBinding = (convert: boolean) => setConversion({ task: editingTask, shown: showTaskForm, convert });
  return { catalog, retry, path, guided, lookup, retryExecution, convertBinding, setConvertBinding };
}

export type TaskFormSources = ReturnType<typeof useTaskFormSources>;

export function taskFormView(props: AdminTaskFormProps, sources: TaskFormSources) {
  const { editingTask, taskFormProjectId = "", projects = [], panelAgents, taskFormAgentDefId, taskFormConfig } = props;
  const { catalog, lookup } = sources;
  const isNew = !editingTask;
  // Defensive: the loaded list holds active workspaces; one explicitly marked inactive is never offered.
  const activeWorkspaces = projects.filter((project) => project.is_active !== false);
  const workspaceId = isNew ? taskFormProjectId : editingTask?.project_id || "";
  const agents = compatibleAgents(panelAgents, workspaceId);
  const agent = panelAgents.find((row) => row.id === taskFormAgentDefId) ?? null;
  const agentAvailable = Boolean(agent && agents.some((row) => row.id === agent.id));
  const agentMode = agent?.agentType?.trim() || "";
  const execution = executionView(lookup, taskFormAgentDefId);
  const instruction =
    agent && execution.runnable ? instructionCheck(execution, lookup, agent) : null;
  const config = guidedConfigView(taskFormConfig);
  const submission = guidedSubmission({
    isNew,
    workspaceId,
    agent,
    agentAvailable,
    modeChoice: permissionModeChoice(catalog, agentMode),
    execution,
    config,
    instruction,
  });
  const guidedSave: GuidedSubmission = {
    ...submission,
    dispatchBinding: bindingToSend({ task: editingTask, convert: sources.convertBinding }),
  };
  return {
    isNew, activeWorkspaces, workspaceId, agents, agent, agentAvailable, agentMode, execution, instruction, config,
    submission, guidedSave,
  };
}

export type TaskFormView = ReturnType<typeof taskFormView>;

/** Sets one key of the Config (JSON) text; an unreadable text is left as it is. */
export function setTaskConfigKey(props: AdminTaskFormProps, key: string, value: unknown) {
  const next = withConfigKey(props.taskFormConfig, key, value);
  if (next !== null) props.setTaskFormConfig(next);
}

/** Chooses the workspace of a new Action; an agent that cannot run there is cleared visibly, never kept silently. */
export function chooseTaskWorkspace(props: AdminTaskFormProps, agent: PanelAgentRow | null, nextWorkspace: string) {
  const { setTaskFormProjectId = () => {}, panelAgents, setTaskFormAgentDefId } = props;
  setTaskFormProjectId(nextWorkspace);
  if (agent && !compatibleAgents(panelAgents, nextWorkspace).some((row) => row.id === agent.id)) {
    setTaskFormAgentDefId("");
  }
}
