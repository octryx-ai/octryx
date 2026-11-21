// Props of the Action card: the task row, its dependencies, step form state and run history.
import type { Dispatch, FormEvent, SetStateAction } from "react";
import type {
  PanelAgentRow,
  PanelTaskDependencyStateRow,
  PanelTaskRow,
  PanelTaskRunRow,
  PanelTaskStepRow,
} from "./taskTypes";

export type AdminTaskCardProps = {
  // The Action's detail inside its side panel (AdminTasksList): no expand toggle or chevron, and
  // Delete sits in the ⋯ menu.
  inPanel?: boolean;
  task: PanelTaskRow;
  isExpanded: boolean;
  runs: PanelTaskRunRow[];
  triggeringTask: string | null;
  onExpandTask: (taskId: string) => void;
  onTriggerTask: (taskId: string) => Promise<void>;
  onOpenTaskForm: (task?: PanelTaskRow) => void;
  setShowTaskForm: Dispatch<SetStateAction<boolean>>;
  onToggleTask: (taskId: string, current: boolean) => Promise<void>;
  onDeleteTask: (taskId: string, name: string) => Promise<void>;
  agentModeNameByKey: Map<string, string>;
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
  panelAgents: PanelAgentRow[];
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
  runsError?: string | null;
  expandedRun: string | null;
  setExpandedRun: Dispatch<SetStateAction<string | null>>;
  setTaskRuns: Dispatch<SetStateAction<Record<string, PanelTaskRunRow[]>>>;
  loadTaskRuns: (
    taskId: string,
    options?: { refresh?: boolean },
  ) => Promise<void>;
  cancellingRun: string | null;
  onCancelRun: (taskId: string, runId: string) => Promise<void>;
};
