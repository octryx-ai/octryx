import type { FormEvent } from "react";
import type { PanelTaskStepRow } from "../components/taskTypes";
import type { UseAdminTaskWorkflowArgs } from "./useAdminTaskWorkflow.types";
import { fillStepForm, moveStep, saveStep } from "./adminTaskStepForm";

export function useAdminTaskStepActions(args: UseAdminTaskWorkflowArgs) {
  const { readJson, taskSteps, setTaskSteps, setExpandedSteps } = args;
  const loadTaskSteps = async (taskId: string) => {
    const steps = await readJson<PanelTaskStepRow[]>(
      `/admin/chat/api/panel/tasks/${taskId}/steps`,
    );
    setTaskSteps((prev) => ({ ...prev, [taskId]: steps }));
  };

  const handleExpandSteps = async (taskId: string) => {
    setExpandedSteps(taskId);
    if (!taskSteps[taskId]) await loadTaskSteps(taskId);
  };

  const handleOpenStepForm = (taskId: string, step?: PanelTaskStepRow) => fillStepForm(args, taskId, step);

  const handleSaveStep = (event: FormEvent, taskId: string) => saveStep(args, event, taskId);

  const handleDeleteStep = async (taskId: string, stepId: string) => {
    if (!confirm("Delete this step?")) return;
    await readJson(`/admin/chat/api/panel/tasks/${taskId}/steps/${stepId}`, {
      method: "DELETE",
    });
    setTaskSteps((prev) => ({
      ...prev,
      [taskId]: (prev[taskId] || []).filter((step) => step.id !== stepId),
    }));
  };

  const handleMoveStep = (taskId: string, stepId: string, direction: "up" | "down") =>
    moveStep(args, taskId, stepId, direction);

  return {
    loadTaskSteps,
    handleExpandSteps,
    handleOpenStepForm,
    handleSaveStep,
    handleDeleteStep,
    handleMoveStep,
  };
}
