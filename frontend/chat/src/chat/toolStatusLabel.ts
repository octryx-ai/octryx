// One wording for a tool call's status wherever a status is shown (trace, inline tool cards, the
// decision timeline). "awaiting_approval" is a call that waits for the person (e.g. propose_write_plan), not a failure.
const LABELS: Record<string, string> = {
  success: "OK",
  completed: "OK",
  ok: "OK",
  error: "Error",
  failed: "Error",
  running: "Running",
  pending: "Pending",
  mixed: "Partial",
  awaiting_approval: "Waiting for approval",
  waiting_approval: "Waiting for approval",
  cancelled: "Cancelled",
  canceled: "Cancelled",
  skipped: "Skipped",
  denied: "Denied",
  rejected: "Denied",
};

export function toolStatusLabel(value: unknown): string {
  const raw = String(value ?? "").trim();
  const known = LABELS[raw.toLowerCase()];
  if (known) return known;
  return raw.replace(/_/g, " ");
}
