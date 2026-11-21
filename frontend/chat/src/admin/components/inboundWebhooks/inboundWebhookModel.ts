// Webhooks → Inbound: what the server returns and how it reads, in words. Pure: no React.

export type InboundEvent = {
  id: string;
  webhook_id: string;
  webhook_name?: string | null;
  source_type?: string | null;
  received_at: string | null;
  outcome: string;
  title: string;
  message: string;
  error: string;
  is_test: boolean;
  task_run_id: string | null;
  session_id: string | null;
};

export type InboundWebhook = {
  id: string;
  name: string;
  project_id: string;
  workspace_name: string;
  source_type: string;
  source_label: string;
  polled: boolean;
  is_active: boolean;
  has_secret: boolean;
  trigger_path: string;
  task_id: string | null;
  action: { id: string; name: string; workflow: string } | null;
  result_to: { kind: string; label: string; plugin_id?: string };
  state: "active" | "needs_setup" | "paused";
  setup_gap: string | null;
  setup_message: string;
  alert_filter: string;
  group_window_minutes: number;
  rate_limit_per_hour: number;
  week: { alerts: number; grouped: number; started: number };
  last_event: InboundEvent | null;
  /** Polled sources (Jira/ServiceNow change) select their items with this query. */
  poll_query?: string;
  last_polled_at?: string | null;
  /** Review fix: calls without a signed timestamp are accepted only when this is set explicitly. */
  accept_untimestamped?: boolean;
  secret?: string;
};

export type InboundSource = {
  key: string;
  label: string;
  polled: boolean;
  samples: { key: string; label: string }[];
};

export type ActionOption = { id: string; name: string; project_id: string | null; config?: Record<string, unknown> };

export const OUTCOME_LABELS: Record<string, string> = {
  started: "Started",
  completed: "Analysis finished",
  failed: "Failed",
  grouped: "Grouped",
  skipped_resolved: "Skipped",
  skipped_filtered: "Skipped",
  skipped_rate_limit: "Skipped",
  needs_setup: "Waiting",
  rejected_signature: "Rejected",
  // backend inbound_alerts/call_guard.py: the same call again inside the replay window; nothing started.
  rejected_replay: "Duplicate",
};

/** An outcome in words; an outcome this page does not know yet reads as words, never as its code. */
export function outcomeLabel(outcome: string): string {
  const known = OUTCOME_LABELS[outcome];
  if (known) return known;
  const words = outcome.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Call";
}

export type Tone = "ok" | "warn" | "error" | "muted";

export function outcomeTone(outcome: string): Tone {
  if (outcome === "completed" || outcome === "started") return "ok";
  if (outcome === "failed" || outcome === "rejected_signature") return "error";
  if (outcome === "needs_setup") return "warn";
  return "muted";
}

export const FILTER_LABELS: Record<string, string> = {
  critical_warning: "Firing alerts with severity critical or warning",
  all_firing: "All firing alerts",
  all: "All calls, resolved ones too",
};

export const WORKFLOW_LABELS: Record<string, string> = {
  read_only: "read only",
  change: "may change things",
  deliver: "may deliver changes",
};

export function stateLine(webhook: InboundWebhook): { text: string; tone: Tone } {
  if (webhook.state === "paused") return { text: "Paused · alerts are not accepted", tone: "muted" };
  if (webhook.state === "needs_setup") return { text: `Needs setup · ${webhook.setup_message}`, tone: "warn" };
  if (!webhook.last_event) return { text: "Active · waiting for the first alert", tone: "ok" };
  return { text: "Active", tone: "ok" };
}

export function weekLine(webhook: InboundWebhook): string {
  const { alerts, grouped } = webhook.week;
  if (!alerts) return "No alerts this week";
  const base = `${alerts} alert${alerts === 1 ? "" : "s"} this week`;
  return grouped ? `${base} · ${grouped} grouped as repeats` : base;
}

export function triggerUrl(path: string, origin: string): string {
  return `${origin.replace(/\/$/, "")}${path}`;
}

export function groupLabel(minutes: number): string {
  if (!minutes) return "Start every time";
  if (minutes % 60 === 0) return `Group the same alert within ${minutes / 60} h`;
  return `Group the same alert within ${minutes} min`;
}

export function limitLabel(perHour: number): string {
  return `At most ${perHour} analyses per hour`;
}

/** Actions of this Workspace that can be started (agent turns); the server still checks the workflow. */
export function actionsForWorkspace(actions: ActionOption[], projectId: string): ActionOption[] {
  return actions.filter((action) => action.project_id === projectId);
}

/** The label of the query field of a polled source. */
export function pollQueryLabel(source: string): string {
  return source === "servicenow_change" ? "Which incidents (encoded query)" : "Which issues (JQL)";
}

export const NEW_ACTION = "__new_action__";

/** Tools that send a bearer token or sign only the body; their webhooks start with the explicit setting on. */
const CANNOT_SIGN_TIMESTAMP = new Set(["alertmanager", "grafana", "datadog", "pagerduty", "sentry", "scm_pull_request",
  "ci_build"]);
/** Sources the server always accepts without a timestamp: GitHub, GitLab and Bitbucket send no timestamp header. */
const NEVER_SIGN_TIMESTAMP = new Set(["scm_pull_request", "ci_build"]);

export function cannotSignTimestamp(source: string): boolean {
  return CANNOT_SIGN_TIMESTAMP.has(source);
}

/** Why the setting cannot be turned off for this source, or "" when the person chooses. */
export function timestampFixedReason(source: string): string {
  return NEVER_SIGN_TIMESTAMP.has(source)
    ? "GitHub, GitLab and Bitbucket send no timestamp header, so this stays on for this source." : "";
}
