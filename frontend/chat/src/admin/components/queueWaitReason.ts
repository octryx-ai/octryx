import type { PanelTaskRunRow } from "./taskTypes";

// Plain text for the dispatcher's closed waiting-reason codes. An unknown code shows
// nothing rather than a guess; the server sends a code only while the run is still queued.
const QUEUE_WAIT_REASON_TEXT: Record<string, string> = {
  no_available_workers: "no worker is available to start it",
  required_worker_unavailable: "the worker it requires is not available",
  paused_due_to_rate_limit: "paused by a rate limit",
  routing_policy_missing: "no routing policy assigns it to a worker",
  no_configured_route: "no worker route is configured for it",
};

export function queueWaitReasonText(
  run: Pick<PanelTaskRunRow, "status" | "queue_wait_reason">,
): string | null {
  if (run.status !== "queued" || typeof run.queue_wait_reason !== "string") {
    return null;
  }
  return Object.prototype.hasOwnProperty.call(
    QUEUE_WAIT_REASON_TEXT,
    run.queue_wait_reason,
  )
    ? QUEUE_WAIT_REASON_TEXT[run.queue_wait_reason]
    : null;
}
