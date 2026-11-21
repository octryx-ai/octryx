import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { GuidedSubmission } from "./automation/actionGuidedModel";
import type { WorkspaceOption } from "./automation/actionGuidedPath";
import type {
  AgentModeOptionRow,
  PanelAgentRow,
  PanelTaskDependencyStateRow,
  PanelTaskRow,
  PanelTaskRunRow,
  PanelTaskStepRow,
} from "./taskTypes";

export type AdminTasksTabCtx = {
  tasks: PanelTaskRow[];
  showTaskForm: boolean;
  setShowTaskForm: Dispatch<SetStateAction<boolean>>;
  editingTask: PanelTaskRow | null;
  setEditingTask: Dispatch<SetStateAction<PanelTaskRow | null>>;
  taskFormName: string;
  setTaskFormName: Dispatch<SetStateAction<string>>;
  taskFormDesc: string;
  setTaskFormDesc: Dispatch<SetStateAction<string>>;
  availableAgentModes: AgentModeOptionRow[];
  taskFormAgentDefId: string;
  setTaskFormAgentDefId: Dispatch<SetStateAction<string>>;
  taskFormProjectId: string;
  setTaskFormProjectId: Dispatch<SetStateAction<string>>;
  /** The user's visible, active workspaces (already loaded by the panel). */
  projects: WorkspaceOption[];
  panelAgents: PanelAgentRow[];
  taskFormMaxIterations: number | "";
  setTaskFormMaxIterations: Dispatch<SetStateAction<number | "">>;
  taskFormConfig: string;
  setTaskFormConfig: Dispatch<SetStateAction<string>>;
  taskFormError: string | null;
  taskFormLoading: boolean;
  onSaveTask: (event: FormEvent, guided?: GuidedSubmission) => Promise<void>;
  onCloseTaskForm: () => void;
  expandedTask: string | null;
  taskRuns: Record<string, PanelTaskRunRow[]>;
  triggeringTask: string | null;
  onExpandTask: (taskId: string) => void;
  agentModeNameByKey: Map<string, string>;
  onTriggerTask: (taskId: string) => Promise<void>;
  onOpenTaskForm: (task?: PanelTaskRow) => void;
  onToggleTask: (taskId: string, current: boolean) => Promise<void>;
  onDeleteTask: (taskId: string, name: string) => Promise<void>;
  taskDependencies: Record<string, PanelTaskDependencyStateRow>;
  onDeleteTaskDependency: (
    taskId: string,
    dependencyId: string,
  ) => Promise<void>;
  taskDependencyTarget: Record<string, string>;
  setTaskDependencyTarget: Dispatch<SetStateAction<Record<string, string>>>;
  taskDependencyCondition: Record<string, string>;
  setTaskDependencyCondition: Dispatch<SetStateAction<Record<string, string>>>;
  onAddTaskDependency: (taskId: string) => Promise<void>;
  taskSteps: Record<string, PanelTaskStepRow[]>;
  onExpandSteps: (taskId: string) => Promise<void>;
  onOpenStepForm: (taskId: string, step?: PanelTaskStepRow) => void;
  showStepForm: string | null;
  setShowStepForm: Dispatch<SetStateAction<string | null>>;
  editingStep: PanelTaskStepRow | null;
  setEditingStep: Dispatch<SetStateAction<PanelTaskStepRow | null>>;
  stepFormName: string;
  setStepFormName: Dispatch<SetStateAction<string>>;
  stepFormType: string;
  setStepFormType: Dispatch<SetStateAction<string>>;
  stepFormConnector: string;
  setStepFormConnector: Dispatch<SetStateAction<string>>;
  stepFormConnectorAction: string;
  setStepFormConnectorAction: Dispatch<SetStateAction<string>>;
  stepFormInstructions: string;
  setStepFormInstructions: Dispatch<SetStateAction<string>>;
  stepFormAgentId: string;
  setStepFormAgentId: Dispatch<SetStateAction<string>>;
  stepFormContextFields: string;
  setStepFormContextFields: Dispatch<SetStateAction<string>>;
  stepFormConnectorParams: string;
  setStepFormConnectorParams: Dispatch<SetStateAction<string>>;
  stepFormMaxFix: number;
  setStepFormMaxFix: Dispatch<SetStateAction<number>>;
  stepFormTimeout: number;
  setStepFormTimeout: Dispatch<SetStateAction<number>>;
  stepFormError: string | null;
  stepFormLoading: boolean;
  onSaveStep: (event: FormEvent, taskId: string) => Promise<void>;
  onMoveStep: (
    taskId: string,
    stepId: string,
    direction: "up" | "down",
  ) => Promise<void>;
  onDeleteStep: (taskId: string, stepId: string) => Promise<void>;
  runsLoading: string | null;
  /** The last failed run-status refresh per Action. */
  taskRunsErrors?: Record<string, string>;
  expandedRun: string | null;
  setExpandedRun: Dispatch<SetStateAction<string | null>>;
  setTaskRuns: Dispatch<SetStateAction<Record<string, PanelTaskRunRow[]>>>;
  loadTaskRuns: (taskId: string, options?: { refresh?: boolean }) => Promise<void>;
  cancellingRun: string | null;
  onCancelRun: (taskId: string, runId: string) => Promise<void>;
};

export type AdminTasksTabProps = {
  ctx: Record<string, unknown>;
};
