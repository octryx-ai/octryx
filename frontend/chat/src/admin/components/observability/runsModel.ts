// Observability → Runs: one row per run of every source, read from turn_traces + tool_calls.
import type { BadgeTone } from "./obUi";

export type RunOutcome = "completed" | "failed" | "blocked" | "needs_approval" | "needs_clarification";
export type RunSource = "chat" | "gateway" | "device" | "workflow";
export type CostState = "priced" | "unpriced" | "not_billed" | null;

export type RunRow = {
  run_key: string;
  session_id: string;
  time: string | null;
  started_at: string | null;
  duration_ms: number | null;
  workspace_id: string | null;
  workspace_name: string | null;
  user_id: string | null;
  user_name: string | null;
  agent_label: string | null;
  source: RunSource;
  outcome: RunOutcome | null;
  steps: number;
  tool_count: number | null;
  tool_failed: number | null;
  cost: number | null;
  cost_state: CostState;
};

export type RunPage = {
  window_hours: number;
  page: number;
  page_size: number;
  total: number;
  total_in_window: number;
  items: RunRow[];
};

export type RunStep = {
  time: string | null;
  kind: "model" | "gate";
  provider: string;
  model: string;
  tokens_in: number;
  tokens_out: number;
  outcome: RunOutcome | null;
  gate: { gate: string; label: string; status: string; reason: string } | null;
};

export type RunDetail = {
  run_key: string;
  session_id: string;
  source: RunSource;
  workspace_id: string | null;
  workspace_name: string | null;
  user_id: string | null;
  user_name: string | null;
  /** Whether the signed-in admin owns the run's session: chat state is owner-only. */
  viewer_is_owner: boolean;
  agent_label: string | null;
  outcome: RunOutcome | null;
  started_at: string | null;
  ended_at: string | null;
  steps: RunStep[];
  steps_truncated: boolean;
  tools: Array<{ tool: string; status: string; duration_ms: number | null; time: string | null }>;
  cost: {
    total: number | null;
    state: CostState;
    by_model: Array<{ model: string; state: Exclude<CostState, null>; calls: number; cost: number }>;
  };
  effective_setup: Record<string, unknown> | null;
};

/** The chat link of a run: only its owner can open the session, everyone else sees "Owner only". */
export function sessionLink(detail: Pick<RunDetail, "session_id" | "viewer_is_owner"> | null): string | null {
  if (!detail?.session_id || !detail.viewer_is_owner) return null;
  return `/chat?session_id=${encodeURIComponent(detail.session_id)}`;
}

export const RUN_SOURCES: RunSource[] = ["chat", "gateway", "device", "workflow"];
export const RUN_OUTCOMES: RunOutcome[] = ["completed", "failed", "blocked", "needs_approval", "needs_clarification"];
export const RUN_WINDOWS = [
  { value: 1, label: "1 h" },
  { value: 24, label: "24 h" },
  { value: 168, label: "7 d" },
];

export function outcomeLabel(outcome: RunOutcome | null): string {
  return outcome ? outcome.replace("_", " ") : "unknown";
}

export function outcomeTone(outcome: RunOutcome | null): BadgeTone {
  switch (outcome) {
    case "completed":
      return "active";
    case "failed":
    case "blocked":
      return "danger";
    case "needs_approval":
    case "needs_clarification":
      return "attention";
    default:
      return "neutral";
  }
}

export function toolsLabel(row: Pick<RunRow, "tool_count" | "tool_failed">): string {
  if (row.tool_count === null) return "–";
  if (!row.tool_count) return "0";
  return `${row.tool_count} / ${row.tool_failed ?? 0} failed`;
}

export function windowLabel(hours: number): string {
  return hours === 1 ? "the last hour" : hours === 168 ? "the last 7 days" : `the last ${hours} h`;
}

export function runsQuery(params: {
  windowHours: number;
  workspaceId: string;
  source: string;
  outcome: string;
  query: string;
  page: number;
}): string {
  const search = new URLSearchParams({ window_hours: String(params.windowHours), page: String(params.page) });
  if (params.workspaceId) search.set("workspace_id", params.workspaceId);
  if (params.source) search.set("source", params.source);
  if (params.outcome) search.set("outcome", params.outcome);
  if (params.query.trim()) search.set("q", params.query.trim());
  return `/api/v1/observability/runs?${search.toString()}`;
}
