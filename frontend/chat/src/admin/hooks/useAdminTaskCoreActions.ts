// Action actions: runs, dependencies, trigger, cancel, toggle and delete; form handlers come from their own module.
import {
  addDependency,
  cancelRun,
  deleteDependency,
  deleteTask,
  loadDependencies,
  loadRuns,
  toggleTask,
  triggerTask,
} from "./adminTaskRunActions";
import type { UseAdminTaskWorkflowArgs } from "./useAdminTaskWorkflow.types";
import { createAdminTaskFormActions } from "./adminTaskFormActions";

export function useAdminTaskCoreActions({
  args,
  loadTaskSteps,
}: {
  args: UseAdminTaskWorkflowArgs;
  loadTaskSteps: (taskId: string) => Promise<void>;
}) {
  const { closeTaskForm, handleOpenTaskForm, handleSaveTask } = createAdminTaskFormActions(args);

  const loadTaskRuns = (
    taskId: string,
    { refresh = false }: { refresh?: boolean } = {},
  ) => loadRuns(args, taskId, refresh);

  const handleExpandTask = (taskId: string) => {
    if (args.expandedTask === taskId) {
      args.setExpandedTask(null);
      return;
    }
    args.setExpandedTask(taskId);
    if (!args.taskSteps[taskId]) void loadTaskSteps(taskId);
    if (!args.taskDependencies[taskId]) void loadDependencies(args, taskId);
    void loadTaskRuns(taskId);
  };

  return {
    closeTaskForm,
    handleAddTaskDependency: (taskId: string) => addDependency(args, taskId),
    handleCancelRun: (taskId: string, runId: string) => cancelRun(args, taskId, runId),
    handleDeleteTask: (taskId: string, name: string) => deleteTask(args, taskId, name),
    handleDeleteTaskDependency: (taskId: string, dependencyId: string) => deleteDependency(args, taskId, dependencyId),
    handleExpandTask,
    handleOpenTaskForm,
    handleSaveTask,
    handleToggleTask: (taskId: string, current: boolean) => toggleTask(args, taskId, current),
    handleTriggerTask: (taskId: string) => triggerTask(args, taskId),
    loadTaskRuns,
  };
}
