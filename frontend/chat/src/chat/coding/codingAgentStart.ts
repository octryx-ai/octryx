// Starting (or restarting) the coding agent for the selected session from its latest approved plan.
import { startCodingAgentExecution } from "./codingApi";
import { blockedExecutionMessage } from "./codingExecutionNoticeModel";
import { latestByVersion } from "./codingSessionValues";
import type { CodingSessionSummary } from "./codingTypes";
import type { CodingAreaState } from "./useCodingAreaSessions";

export const RESTART_REASON =
  "Operator declined the previous coding result and requested a fresh run from the approved plan.";

// A started run opens its chat; a run that did not start shows why on the Blocked sessions page.
export async function startCodingAgent(
  state: CodingAreaState,
  selectedSession: CodingSessionSummary | null,
  { restartFromScratch, restartReason }: { restartFromScratch: boolean; restartReason?: string },
) {
  const { detail, setError, setAgentStartBusy, setExecutionNotice } = state;
  if (!selectedSession || !detail) {
    return;
  }
  const approvedPlan = latestByVersion(detail.changePlans.filter((plan) => plan.status === "approved"));
  if (!approvedPlan) {
    setError("Approved Work Plan required before the coding agent can start.");
    return;
  }
  setAgentStartBusy(true);
  setError(null);
  setExecutionNotice(null);
  try {
    const result = await startCodingAgentExecution(selectedSession.id, {
      change_plan_id: approvedPlan.id,
      change_unit_ids: detail.changeUnits.map((unit) => unit.id),
      restart_from_scratch: restartFromScratch,
      restart_reason: restartReason,
    });
    await state.refresh(selectedSession.id);
    if (result.status === "started" && result.session?.chat_url) {
      window.location.href = result.session.chat_url;
      return;
    }
    state.setActiveNav("sessions");
    state.setSessionQueue("blocked");
    state.setActiveTab("process");
    setExecutionNotice({
      title: "Coding agent was not started",
      message: blockedExecutionMessage(result),
      workUrl: result.work_url,
      codingUrl: result.coding_url,
    });
  } catch (err) {
    setError(err instanceof Error ? err.message : "Failed to start coding agent execution");
  } finally {
    setAgentStartBusy(false);
  }
}
