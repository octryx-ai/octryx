import { useState } from "react";
import type {
  PanelTaskDependencyStateRow,
  PanelTaskRow,
  PanelTaskRunRow,
} from "../components/taskTypes";

export function useAdminTaskState() {
  const [tasks, setTasks] = useState<PanelTaskRow[]>([]);
  const [taskDependencies, setTaskDependencies] = useState<
    Record<string, PanelTaskDependencyStateRow>
  >({});
  const [taskRuns, setTaskRuns] = useState<Record<string, PanelTaskRunRow[]>>({});
  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const [runsLoading, setRunsLoading] = useState<string | null>(null);
  // Why the last run-status refresh of an Action failed (its rows stay as last known).
  const [taskRunsErrors, setTaskRunsErrors] = useState<Record<string, string>>({});
  const [triggeringTask, setTriggeringTask] = useState<string | null>(null);
  const [cancellingRun, setCancellingRun] = useState<string | null>(null);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);

  const [showTaskForm, setShowTaskForm] = useState(false);
  const [editingTask, setEditingTask] = useState<PanelTaskRow | null>(null);
  const [taskFormName, setTaskFormName] = useState("");
  const [taskFormDesc, setTaskFormDesc] = useState("");
  const [taskFormConfig, setTaskFormConfig] = useState("{}");
  const [taskFormMaxIterations, setTaskFormMaxIterations] = useState<
    number | ""
  >(32);
  const [taskFormAgentDefId, setTaskFormAgentDefId] = useState("");
  // The workspace a new Action runs in: chosen explicitly, never preselected.
  const [taskFormProjectId, setTaskFormProjectId] = useState("");
  const [taskFormLoading, setTaskFormLoading] = useState(false);
  const [taskFormError, setTaskFormError] = useState<string | null>(null);
  const [taskDependencyTarget, setTaskDependencyTarget] = useState<
    Record<string, string>
  >({});
  const [taskDependencyCondition, setTaskDependencyCondition] = useState<
    Record<string, string>
  >({});

  return {
    cancellingRun,
    setCancellingRun,
    editingTask,
    setEditingTask,
    expandedRun,
    setExpandedRun,
    expandedTask,
    setExpandedTask,
    runsLoading,
    setRunsLoading,
    taskRunsErrors,
    setTaskRunsErrors,
    setShowTaskForm,
    showTaskForm,
    taskDependencies,
    setTaskDependencies,
    taskDependencyCondition,
    setTaskDependencyCondition,
    taskDependencyTarget,
    setTaskDependencyTarget,
    taskFormAgentDefId,
    setTaskFormAgentDefId,
    taskFormProjectId,
    setTaskFormProjectId,
    taskFormConfig,
    setTaskFormConfig,
    taskFormDesc,
    setTaskFormDesc,
    taskFormError,
    setTaskFormError,
    taskFormLoading,
    setTaskFormLoading,
    taskFormMaxIterations,
    setTaskFormMaxIterations,
    taskFormName,
    setTaskFormName,
    taskRuns,
    setTaskRuns,
    tasks,
    setTasks,
    triggeringTask,
    setTriggeringTask,
  };
}
