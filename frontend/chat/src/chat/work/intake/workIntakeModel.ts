import { formatRelativeTime } from "../../../admin/utils/formatters";
import type { IntakeConnection, IntakeSchedule, IntakeSource, IntakeSummary } from "./workIntakeTypes";

// Pure presentation of the intake overview (no React): the words the page shows for each value.

const SCHEDULE_LABELS: Record<string, string> = {
  manual: "Manual only",
  every_15_min: "Every 15 min",
  hourly: "Hourly",
  every_4_hours: "Every 4 h",
  daily_0600: "Daily 06:00",
};

const AUTOMATION_LABELS: Record<string, string> = {
  needs_review: "Suggest only",
  direct: "Agent may start",
  human_only: "Humans only",
};

export function connectionLabel(connection: Pick<IntakeConnection, "name"> & Partial<IntakeConnection>): string {
  const name = connection.name === "default" ? "Default connection" : connection.name;
  return connection.scope === "global" ? `${name} (global)` : name;
}

export function scheduleLabel(schedule: IntakeSchedule): string {
  if (schedule.preset === "custom") return `Custom: ${schedule.cron ?? ""}`.trim();
  return SCHEDULE_LABELS[schedule.preset] ?? schedule.preset;
}

export function automationLabel(intake: Pick<IntakeSummary, "automation_mode" | "automation_labels">): string {
  const mode = intake.automation_mode || "needs_review";
  const label = AUTOMATION_LABELS[mode] ?? mode;
  if (mode !== "direct" || !intake.automation_labels.length) return label;
  return `${label} (label ${intake.automation_labels.join(", ")})`;
}

const list = (value: string[] | boolean | string | null | undefined) => (Array.isArray(value) ? value : []);

/** A scalar the overview sends as stored (Custom REST's `operation`, `role`; backend); "" when unset. */
const oneName = (value: string[] | boolean | string | null | undefined): string => (typeof value === "string" ? value.trim() : "");

const SOURCE_LABELS: Record<string, string> = { jira: "Jira", servicenow: "ServiceNow", custom_rest: "Custom REST" };

/** A source kind in words ("custom_rest" → "Custom REST"). */
export const sourceLabel = (kind: string): string => SOURCE_LABELS[kind] ?? kind;

export function whatLabel(intake: Pick<IntakeSummary, "source_type" | "what">): string {
  const what = intake.what;
  const parts: string[] = [];
  if (intake.source_type === "jira") {
    const projects = list(what.project_keys);
    parts.push(projects.length ? `Project ${projects.join(", ")}` : "All allowed projects");
    if (list(what.issue_types).length) parts.push(list(what.issue_types).join(", "));
    if (list(what.labels_include).length) parts.push(`label ${list(what.labels_include).join(", ")}`);
    if (list(what.labels_exclude).length) parts.push(`without ${list(what.labels_exclude).join(", ")}`);
  } else if (intake.source_type === "custom_rest") {
    const operation = oneName(what.operation);
    const role = oneName(what.role);
    parts.push(operation ? `Operation ${operation}` : "No operation");
    if (role) parts.push(`as ${role}`);
  } else {
    parts.push(list(what.tables).join(", ") || "incident");
    if (list(what.excluded_states).length) parts.push(`excluding ${list(what.excluded_states).join(", ")}`);
  }
  if (what.custom_query === true) parts.push("custom query");
  return parts.join(" · ");
}

export function workSourcesSummary(sources: IntakeSource[]): string {
  const capable = sources.filter((source) => source.work_capable);
  const done = capable.filter((source) => source.work_state === "set_up").length;
  return `${done} of ${capable.length} work sources set up`;
}

/** The first work source that is connected and synced into Knowledge but has no intake. */
export function gapSource(sources: IntakeSource[]): IntakeSource | null {
  return sources.find((source) => source.work_state === "no_intake" && source.knowledge !== null) ?? null;
}

export function knowledgeLabel(source: IntakeSource): string | null {
  if (!source.knowledge) return null;
  const when = formatRelativeTime(source.knowledge.last_synced_at);
  return when ? `synced ${when}` : "not synced yet";
}

export function workLabel(source: IntakeSource): string | null {
  if (!source.work) return null;
  const items = `${source.work.items} item${source.work.items === 1 ? "" : "s"}`;
  const when = formatRelativeTime(source.work.last_run_at);
  return when ? `${items} · last run ${when}` : items;
}
