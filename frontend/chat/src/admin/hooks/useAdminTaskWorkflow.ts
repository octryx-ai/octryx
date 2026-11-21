import type { UseAdminTaskWorkflowArgs } from "./useAdminTaskWorkflow.types";
import { useAdminTaskCoreActions } from "./useAdminTaskCoreActions";
import { useAdminTaskSchedulerActions } from "./useAdminTaskSchedulerActions";
import { useAdminTaskStepActions } from "./useAdminTaskStepActions";

export function useAdminTaskWorkflow(workflowArgs: UseAdminTaskWorkflowArgs) {
  const {
    loadTaskSteps,
    handleExpandSteps,
    handleOpenStepForm,
    handleSaveStep,
    handleDeleteStep,
    handleMoveStep,
  } = useAdminTaskStepActions(workflowArgs);
  const {
    closeSchedulerForm,
    handleCreateScheduler,
    handleDeleteScheduler,
    handleOpenSchedulerForm,
    handleSaveScheduler,
    handleToggleScheduler,
  } = useAdminTaskSchedulerActions(workflowArgs);
  const {
    closeTaskForm,
    handleAddTaskDependency,
    handleCancelRun,
    handleDeleteTask,
    handleDeleteTaskDependency,
    handleExpandTask,
    handleOpenTaskForm,
    handleSaveTask,
    handleToggleTask,
    handleTriggerTask,
    loadTaskRuns,
  } = useAdminTaskCoreActions({
    args: workflowArgs,
    loadTaskSteps,
  });

  return {
    closeSchedulerForm,
    closeTaskForm,
    handleAddTaskDependency,
    handleCancelRun,
    handleCreateScheduler,
    handleDeleteScheduler,
    handleDeleteStep,
    handleDeleteTask,
    handleDeleteTaskDependency,
    handleExpandSteps,
    handleExpandTask,
    handleMoveStep,
    handleOpenSchedulerForm,
    handleOpenStepForm,
    handleOpenTaskForm,
    handleSaveScheduler,
    handleSaveStep,
    handleSaveTask,
    handleToggleScheduler,
    handleToggleTask,
    handleTriggerTask,
    loadTaskRuns,
  };
}
