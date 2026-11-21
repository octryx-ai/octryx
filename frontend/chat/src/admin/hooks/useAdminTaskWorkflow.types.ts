import type { Dispatch, SetStateAction } from "react";

import type {
  PanelScheduler,
  PanelTaskRow,
  PanelTaskDependencyStateRow,
  PanelTaskRunRow,
  PanelTaskStepRow,
} from "../components/taskTypes";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type UseAdminTaskWorkflowArgs = {
  readJson: ReadJsonFn;
  tasks: PanelTaskRow[];
  setTasks: Dispatch<SetStateAction<PanelTaskRow[]>>;
  taskRuns: Record<string, PanelTaskRunRow[]>;
  setTaskRuns: Dispatch<SetStateAction<Record<string, PanelTaskRunRow[]>>>;
  setRunsLoading: Dispatch<SetStateAction<string | null>>;
  setTaskRunsErrors: Dispatch<SetStateAction<Record<string, string>>>;
  taskDependencies: Record<string, PanelTaskDependencyStateRow>;
  setTaskDependencies: Dispatch<
    SetStateAction<Record<string, PanelTaskDependencyStateRow>>
  >;
  taskDependencyTarget: Record<string, string>;
  setTaskDependencyTarget: Dispatch<SetStateAction<Record<string, string>>>;
  taskDependencyCondition: Record<string, string>;
  setTaskDependencyCondition: Dispatch<SetStateAction<Record<string, string>>>;
  expandedTask: string | null;
  setExpandedTask: Dispatch<SetStateAction<string | null>>;
  taskSteps: Record<string, PanelTaskStepRow[]>;
  setTaskSteps: Dispatch<SetStateAction<Record<string, PanelTaskStepRow[]>>>;
  setTriggeringTask: Dispatch<SetStateAction<string | null>>;
  setCancellingRun: Dispatch<SetStateAction<string | null>>;
  setShowTaskForm: Dispatch<SetStateAction<boolean>>;
  editingTask: PanelTaskRow | null;
  setEditingTask: Dispatch<SetStateAction<PanelTaskRow | null>>;
  taskFormName: string;
  setTaskFormName: Dispatch<SetStateAction<string>>;
  taskFormDesc: string;
  setTaskFormDesc: Dispatch<SetStateAction<string>>;
  taskFormConfig: string;
  setTaskFormConfig: Dispatch<SetStateAction<string>>;
  taskFormMaxIterations: number;
  setTaskFormMaxIterations: Dispatch<SetStateAction<number>>;
  taskFormAgentDefId: string;
  setTaskFormAgentDefId: Dispatch<SetStateAction<string>>;
  taskFormProjectId: string;
  setTaskFormProjectId: Dispatch<SetStateAction<string>>;
  setTaskFormError: Dispatch<SetStateAction<string | null>>;
  setTaskFormLoading: Dispatch<SetStateAction<boolean>>;
  setShowSchedulerForm: Dispatch<SetStateAction<boolean>>;
  setEditingScheduler: Dispatch<SetStateAction<PanelScheduler | null>>;
  editingScheduler: PanelScheduler | null;
  schedulerFormName: string;
  setSchedulerFormName: Dispatch<SetStateAction<string>>;
  schedulerFormDesc: string;
  setSchedulerFormDesc: Dispatch<SetStateAction<string>>;
  schedulerFormCron: string;
  setSchedulerFormCron: Dispatch<SetStateAction<string>>;
  schedulerFormTaskId: string;
  setSchedulerFormTaskId: Dispatch<SetStateAction<string>>;
  setSchedulerFormError: Dispatch<SetStateAction<string | null>>;
  setSchedulerFormLoading: Dispatch<SetStateAction<boolean>>;
  setSchedulers: Dispatch<SetStateAction<PanelScheduler[]>>;
  loadTab: (tab: string) => Promise<void>;
  setExpandedSteps: Dispatch<SetStateAction<string | null>>;
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
  stepFormMaxFix: number;
  setStepFormMaxFix: Dispatch<SetStateAction<number>>;
  stepFormTimeout: number;
  setStepFormTimeout: Dispatch<SetStateAction<number>>;
  stepFormAgentId: string;
  setStepFormAgentId: Dispatch<SetStateAction<string>>;
  stepFormContextFields: string;
  setStepFormContextFields: Dispatch<SetStateAction<string>>;
  stepFormConnectorParams: string;
  setStepFormConnectorParams: Dispatch<SetStateAction<string>>;
  setStepFormError: Dispatch<SetStateAction<string | null>>;
  setStepFormLoading: Dispatch<SetStateAction<boolean>>;
};
