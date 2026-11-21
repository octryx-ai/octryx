// Task step form helpers: fill the form from a step, build the request body from the form, save
// (PUT for an edited step, POST for a new one) and reorder.
import type { FormEvent } from "react";
import type { PanelTaskStepRow } from "../components/taskTypes";
import type { UseAdminTaskWorkflowArgs } from "./useAdminTaskWorkflow.types";

type Args = UseAdminTaskWorkflowArgs;

export function fillStepForm(a: Args, taskId: string, step?: PanelTaskStepRow) {
  a.setEditingStep(step || null);
  a.setShowStepForm(taskId);
  a.setStepFormName(step?.name || "Step");
  a.setStepFormType(step?.step_type || "analysis");
  a.setStepFormConnector(step?.connector || "");
  a.setStepFormConnectorAction(step?.connector_action || "");
  a.setStepFormInstructions(step?.instructions || "");
  a.setStepFormMaxFix(step?.max_fix_attempts ?? 2);
  a.setStepFormTimeout(step?.agent_timeout_seconds ?? 300);
  const cp = step?.connector_params || {};
  if ("agent_definition_id" in cp) {
    a.setStepFormAgentId(
      cp.agent_definition_id === ""
        ? "__none__"
        : String(cp.agent_definition_id),
    );
  } else {
    a.setStepFormAgentId("");
  }
  a.setStepFormContextFields((step?.context_fields || []).join(", "));
  const cpCopy = { ...cp };
  delete cpCopy.agent_definition_id;
  a.setStepFormConnectorParams(
    Object.keys(cpCopy).length ? JSON.stringify(cpCopy, null, 2) : "",
  );
  a.setStepFormError(null);
}

// Malformed connector JSON is sent as an empty object; the agent choice is merged in.
function stepRequestBody(a: Args): Record<string, unknown> {
  let connectorParams: Record<string, unknown> = {};
  if (a.stepFormConnectorParams.trim()) {
    try {
      connectorParams = JSON.parse(a.stepFormConnectorParams);
    } catch {
      // Ignore malformed JSON and send empty object.
    }
  }
  if (a.stepFormAgentId === "__none__") {
    connectorParams.agent_definition_id = "";
  } else if (a.stepFormAgentId) {
    connectorParams.agent_definition_id = a.stepFormAgentId;
  }
  const contextFields = a.stepFormContextFields
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return {
    name: a.stepFormName,
    step_type: a.stepFormType,
    connector: a.stepFormConnector || null,
    connector_action: a.stepFormConnectorAction || null,
    connector_params: connectorParams,
    context_fields: contextFields,
    instructions: a.stepFormInstructions,
    max_fix_attempts: a.stepFormMaxFix,
    agent_timeout_seconds: a.stepFormTimeout,
  };
}

export async function saveStep(a: Args, event: FormEvent, taskId: string) {
  event.preventDefault();
  a.setStepFormLoading(true);
  a.setStepFormError(null);
  try {
    const body = stepRequestBody(a);
    if (a.editingStep) {
      const updated = await a.readJson<PanelTaskStepRow>(
        `/admin/chat/api/panel/tasks/${taskId}/steps/${a.editingStep.id}`,
        {
          method: "PUT",
          body: JSON.stringify(body),
        },
      );
      a.setTaskSteps((prev) => ({
        ...prev,
        [taskId]: (prev[taskId] || []).map((step) =>
          step.id === updated.id ? updated : step,
        ),
      }));
    } else {
      const created = await a.readJson<PanelTaskStepRow>(
        `/admin/chat/api/panel/tasks/${taskId}/steps`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      a.setTaskSteps((prev) => ({
        ...prev,
        [taskId]: [...(prev[taskId] || []), created],
      }));
    }
    a.setShowStepForm(null);
    a.setEditingStep(null);
  } catch (err) {
    a.setStepFormError(err instanceof Error ? err.message : "Failed");
  } finally {
    a.setStepFormLoading(false);
  }
}

export async function moveStep(a: Args, taskId: string, stepId: string, direction: "up" | "down") {
  const steps = [...(a.taskSteps[taskId] || [])].sort(
    (left, right) => left.position - right.position,
  );
  const idx = steps.findIndex((step) => step.id === stepId);
  if (direction === "up" && idx === 0) return;
  if (direction === "down" && idx === steps.length - 1) return;
  const swap = direction === "up" ? idx - 1 : idx + 1;
  [steps[idx], steps[swap]] = [steps[swap], steps[idx]];
  const order = steps.map((step) => step.id);
  const updated = await a.readJson<PanelTaskStepRow[]>(
    `/admin/chat/api/panel/tasks/${taskId}/steps/reorder`,
    {
      method: "POST",
      body: JSON.stringify({ order }),
    },
  );
  a.setTaskSteps((prev) => ({ ...prev, [taskId]: updated }));
}
