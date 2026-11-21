import type { CoordinatorControlAction, CoordinatorControlResponse, CoordinatorStateContract } from "../chatCoordinatorTypes";
import { readJson } from "./chatApiClient";

const COORDINATOR_CONTINUE_MODES = new Set([
  "sub_agent_group",
  "worker_delegation",
  "deterministic_workflow",
]);

const COORDINATOR_STOP_MODES = new Set(["deterministic_workflow"]);

export async function loadSessionCoordinatorStatus(
  sessionId: string,
): Promise<CoordinatorStateContract> {
  return readJson<CoordinatorStateContract>(
    `/api/v1/sessions/${sessionId}/coordinator-status`,
  );
}

async function applySessionCoordinatorControl(
  sessionId: string,
  action: CoordinatorControlAction,
): Promise<CoordinatorControlResponse> {
  return readJson<CoordinatorControlResponse>(
    `/api/v1/sessions/${sessionId}/coordinator-control`,
    {
      method: "POST",
      body: JSON.stringify({ action }),
    },
  );
}

export async function applySessionCoordinatorContinue(
  sessionId: string,
): Promise<CoordinatorControlResponse> {
  return applySessionCoordinatorControl(sessionId, "continue");
}

export async function applySessionCoordinatorStop(
  sessionId: string,
): Promise<CoordinatorControlResponse> {
  return applySessionCoordinatorControl(sessionId, "stop");
}

export function shouldUseCoordinatorContinue(
  contract: CoordinatorStateContract,
): boolean {
  return COORDINATOR_CONTINUE_MODES.has(contract.coordinator_mode);
}

export function shouldUseCoordinatorStop(
  contract: CoordinatorStateContract,
  sessionId: string,
): boolean {
  if (contract.root_session_id !== sessionId) {
    return true;
  }
  return COORDINATOR_STOP_MODES.has(contract.coordinator_mode);
}

export function describeCoordinatorContinueBlockedState(
  contract: CoordinatorStateContract,
): string {
  const aggregateStatus = String(contract.aggregate_status || "")
    .trim()
    .replace(/_/g, " ");
  if (contract.coordinator_mode === "sub_agent_group") {
    return aggregateStatus
      ? `Coordinator session is still ${aggregateStatus}. Continue becomes available after child runs finish.`
      : "Coordinator session is still waiting for child runs to finish.";
  }
  if (contract.coordinator_mode === "worker_delegation") {
    return aggregateStatus
      ? `Coordinator session is still ${aggregateStatus}. Continue becomes available after delegated work reaches a terminal state.`
      : "Coordinator session is still waiting for delegated work to finish.";
  }
  if (contract.coordinator_mode === "deterministic_workflow") {
    return aggregateStatus
      ? `Deterministic workflow is still ${aggregateStatus}. Continue is not available yet.`
      : "Deterministic workflow cannot continue yet.";
  }
  return "Coordinator session cannot continue in its current state.";
}

export function describeCoordinatorStopBlockedState(
  contract: CoordinatorStateContract,
): string {
  const aggregateStatus = String(contract.aggregate_status || "")
    .trim()
    .replace(/_/g, " ");
  if (contract.coordinator_mode === "deterministic_workflow") {
    return aggregateStatus
      ? `Deterministic workflow is already ${aggregateStatus}. Stop is not available right now.`
      : "Deterministic workflow cannot stop in its current state.";
  }
  if (contract.root_session_id && contract.root_session_id !== "") {
    return aggregateStatus
      ? `Coordinator root run is already ${aggregateStatus}. Stop is not available right now.`
      : "Coordinator root run cannot stop in its current state.";
  }
  return "Coordinator session cannot stop in its current state.";
}
