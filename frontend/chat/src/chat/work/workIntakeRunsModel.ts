export type IntakeRun = {
  id: string;
  at: string | null;
  trigger: string;
  mode: string;
  status: string;
  summary: Record<string, unknown>;
  error: string | null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

const TRIGGER_TEXT: Record<string, string> = { manual: "manual", scheduled: "scheduled" };

export function readRun(value: unknown, sessionTrigger: string | null = null): IntakeRun | null {
  if (!isRecord(value) || !text(value.id) || !text(value.status)) return null;
  const trigger = TRIGGER_TEXT[text(value.trigger)] ?? sessionTrigger ?? "trigger not reported";
  return {
    id: text(value.id),
    at: text(value.completed_at) || text(value.started_at) || text(value.created_at) || null,
    trigger,
    mode: text(value.mode) === "dry_run" ? "preview" : text(value.mode) === "sync" ? "sync" : text(value.mode) || "run",
    status: text(value.status),
    summary: isRecord(value.summary) ? value.summary : {},
    error: text(value.error) || null,
  };
}

const count = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

const AUTOMATION_TEXT: Record<string, string> = {
  direct: "agent may start",
  needs_review: "agent may suggest",
  human_only: "humans only",
};

export function pendingText(summary: Record<string, unknown>): string {
  const pending = count(summary.pending_next_run);
  if (pending !== null && pending > 0) return `${pending} pending next run`;
  return summary.more_pending === true ? "more pending next run" : "";
}

// Items the limit or paging left for the next run are pending, never "filtered out".
export function runCountsText(summary: Record<string, unknown>): string {
  const source = isRecord(summary.source) ? summary.source : {};
  const returned = count(source.returned);
  const after = count(summary.total_after_filter);
  const parts = [
    count(summary.imported) !== null ? `${summary.imported} imported` : "",
    count(summary.updated) !== null ? `${summary.updated} updated` : "",
    count(summary.unchanged) !== null ? `${summary.unchanged} unchanged` : "",
    pendingText(summary),
    returned !== null && after !== null && returned > after ? `${returned - after} left out by the intake's filters` : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

export function runAutomationText(summary: Record<string, unknown>): string {
  const automation = isRecord(summary.automation) ? summary.automation : {};
  const matching = count(automation.matching);
  const labels = Array.isArray(automation.labels) ? automation.labels.map(String).filter(Boolean) : [];
  if (matching === null || !labels.length) return "";
  const mode = AUTOMATION_TEXT[text(automation.mode)] ?? AUTOMATION_TEXT.needs_review;
  return `${matching} with label ${labels.join(", ")} – ${mode}`;
}

export type RunOutcome = { label: string; tone: "active" | "attention" | "danger" | "neutral"; detail: string | null };

const BLOCK_TEXT: Record<string, string> = {
  jql_unbalanced: "the intake's custom JQL has unbalanced parentheses or quotes, so it was not sent to Jira",
};

export function runOutcome(run: IntakeRun): RunOutcome {
  const summary = run.summary;
  const code = text(summary.code) || text(summary.reason) || run.error || "";
  if (run.status === "failed" || code) {
    if (code === "scope_not_allowed") {
      const projects = Array.isArray(summary.projects) ? summary.projects.map(String).filter(Boolean) : [];
      return {
        label: "refused",
        tone: "danger",
        detail: `The intake's Jira projects${projects.length ? ` (${projects.join(", ")})` : ""} are outside this Workspace's allowed Jira projects, so nothing was fetched. Narrow the intake's projects, or extend the allowlist under Workspace settings → Connectors → Jira.`,
      };
    }
    const message = text(summary.message);
    return {
      label: "failed",
      tone: "danger",
      detail: `${code || "failed"}${message ? `: ${message}` : ""}`,
    };
  }
  if (run.status === "blocked" || summary.blocked === true) {
    const reason = text(summary.block_reason) || text((isRecord(summary.source) ? summary.source : {}).reason);
    return { label: "blocked", tone: "attention", detail: BLOCK_TEXT[reason] ?? (reason || "the run was blocked") };
  }
  if (run.status === "completed") {
    return {
      label: "completed",
      tone: "active",
      detail: summary.filtered_outside_allowlist === true
        ? "Issues outside the Workspace's allowed Jira projects were left out."
        : null,
    };
  }
  return { label: run.status, tone: "neutral", detail: null };
}
