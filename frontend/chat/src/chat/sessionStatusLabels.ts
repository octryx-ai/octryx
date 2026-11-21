// Status labels for a chat session: run status, resume notice and thread lifecycle.
import type { SelectedSession } from "../chatThreadTypes";

export function getSessionStatusLabel(
  session: SelectedSession | null,
  isRunning: boolean,
) {
  const runStatus = String(session?.runStatus || "")
    .trim()
    .toLowerCase();
  const runReason = String(session?.runCompletionReason || "")
    .trim()
    .toLowerCase();
  const resumeState = String(session?.resumeState || "")
    .trim()
    .toLowerCase();
  if (!session) {
    return "Ready";
  }
  if (
    resumeState === "approval_approved" &&
    (isRunning || runStatus === "in_progress" || session.status === "running")
  ) {
    return "Resuming after approval";
  }
  if (
    resumeState === "approval_rejected" &&
    (isRunning || runStatus === "in_progress" || session.status === "running")
  ) {
    return "Resuming after rejection";
  }
  if (
    isRunning ||
    runStatus === "in_progress" ||
    session.status === "running"
  ) {
    return "Running";
  }
  if (
    runStatus === "awaiting_approval" ||
    session.status === "pending_approval"
  ) {
    return "Approval needed";
  }
  if (runReason === "human_input_required") {
    return "Needs input";
  }
  if (runStatus === "failed" && runReason === "interrupted_by_restart") {
    return "Interrupted by restart";
  }
  if (runStatus === "failed") {
    return "Failed";
  }
  if (runStatus === "stopped" || session.stopReason === "user_cancelled") {
    return "Stopped";
  }
  if (runStatus === "completed") {
    if (runReason === "no_changes_needed") {
      return "Done (no changes)";
    }
    return "Done";
  }
  return "Ready";
}

export function shouldShowResumeNotice(
  session: SelectedSession | null,
  isRunning: boolean,
) {
  const resumeState = String(session?.resumeState || "")
    .trim()
    .toLowerCase();
  if (!resumeState) {
    return false;
  }
  return Boolean(
    isRunning ||
    String(session?.runStatus || "")
      .trim()
      .toLowerCase() === "in_progress" ||
    String(session?.status || "")
      .trim()
      .toLowerCase() === "running",
  );
}

export function getThreadLifecycleLabel(session: SelectedSession | null) {
  const status = String(session?.status || "")
    .trim()
    .toLowerCase();
  if (!session) {
    return "Ready";
  }
  if (status === "running") {
    return "Running";
  }
  if (status === "pending_approval") {
    return "Approval needed";
  }
  if (status === "archived") {
    return "Archived";
  }
  if (status === "error") {
    return "Error";
  }
  if (status === "stopped" || session.stopReason === "user_cancelled") {
    return "Stopped";
  }
  if (status === "completed") {
    return "Completed";
  }
  return "Active";
}
