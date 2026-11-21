import { pendingText, runAutomationText } from "../workIntakeRunsModel";
import type { IntakeSchedule } from "./workIntakeTypes";
import { REST_SOURCE, emptyRestForm, restFormOf } from "./restIntakeForm";
import { restBodyParts, restStepProblem } from "./restIntakeModel";
import type { RestDiscovery, RestSourceForm } from "./restIntakeForm";

// The draft the setup drawer edits, as `…/intake` stores it, and the
// pure rules of its steps. No React.

export type FieldRole = { role: string; label: string; field: { id: string; name: string } | null };
export type DiscoveredStatus = { name: string; category?: string | null; state: string | null };

export type IntakeDiscovery = {
  source_type: string;
  work_states: Array<{ key: string; label: string }>;
  projects?: Array<{ key: string; name: string }>;
  issue_types?: string[];
  statuses?: DiscoveredStatus[];
  // Jira: the discovered field roles. Custom REST: the Work item fields a record maps to (see `RestDiscovery`).
  fields?: FieldRole[] | { required: string[]; optional: string[] };
  tables?: string[];
  excluded_states?: string[];
  assignment_groups?: string[];
  services?: string[];
  reason?: string | null;
} & Omit<RestDiscovery, "fields">;

export type IntakeDraft = {
  id?: string;
  source_type: string;
  name: string;
  connection_id: string;
  is_active?: boolean;
  what: Record<string, string[] | string>;
  schedule: IntakeSchedule;
  how: {
    automation_mode: string;
    automation_labels: string[];
    automation_exclude_labels: string[];
    status_mapping: Record<string, string>;
    field_mapping: Record<string, string>;
    /** The source's own write-back mode; null follows the Workspace workflow. Sent exactly as the draft holds it: a
     * loaded draft always has the key (the server returns it), a new one only once the select was touched, and a
     * missing key keeps the stored mode on the server (backend). */
    sync_mode?: string | null;
  };
  /** Custom REST only: the form its steps edit; the request body is built from it (`restBodyParts`). */
  rest?: RestSourceForm;
};

export const STEPS = ["Source", "What", "When", "How", "Preview"] as const;

export const SCHEDULE_CHOICES: Array<{ preset: string; label: string; hint: string }> = [
  { preset: "manual", label: "Manual only", hint: "Run from this page" },
  { preset: "every_15_min", label: "Every 15 min", hint: "Recommended for active projects" },
  { preset: "hourly", label: "Hourly", hint: "" },
  { preset: "every_4_hours", label: "Every 4 h", hint: "" },
  { preset: "daily_0600", label: "Daily 06:00", hint: "Workspace time zone" },
];

export const AUTOMATION_CHOICES: Array<{ mode: string; label: string; hint: string }> = [
  { mode: "needs_review", label: "Suggest only", hint: "Item lands in Intake; a person starts the work." },
  { mode: "direct", label: "Agent may start", hint: "Items with the automation label get a plan automatically." },
  { mode: "human_only", label: "Humans only", hint: "Track the item; the agent never acts on it." },
];

const list = (value: string[] | string | undefined): string[] => (Array.isArray(value) ? value : []);
const text = (value: string[] | string | undefined): string => (typeof value === "string" ? value : "");

export function newDraft(sourceType: string, connectionId: string, name = ""): IntakeDraft {
  if (sourceType === REST_SOURCE) {
    return { source_type: sourceType, name, connection_id: connectionId, what: {}, schedule: { preset: "manual", cron: null },
      how: { automation_mode: "needs_review", automation_labels: [], automation_exclude_labels: [], status_mapping: {}, field_mapping: {} },
      rest: emptyRestForm() };
  }
  return {
    source_type: sourceType,
    name,
    connection_id: connectionId,
    what: sourceType === "servicenow" ? { tables: ["incident"], excluded_states: [] } : { project_keys: [] },
    schedule: { preset: "every_15_min", cron: null },
    how: { automation_mode: "needs_review", automation_labels: ["octryx"], automation_exclude_labels: [],
      status_mapping: {}, field_mapping: {} },
  };
}

/** Defaults the discovery suggests, without overwriting what the draft already holds. */
export function withDiscovery(draft: IntakeDraft, found: IntakeDiscovery): IntakeDraft {
  if (draft.source_type === REST_SOURCE) return draft;
  const status = { ...draft.how.status_mapping };
  for (const entry of found.statuses ?? []) if (!(entry.name in status) && entry.state) status[entry.name] = entry.state;
  const fields = { ...draft.how.field_mapping };
  if (!draft.id) for (const role of Array.isArray(found.fields) ? found.fields : []) if (role.field && !fields[role.role]) fields[role.role] = role.field.id;
  const what = { ...draft.what };
  if (draft.source_type === "servicenow" && !draft.id && !list(what.excluded_states).length) {
    what.excluded_states = found.excluded_states ?? [];
  }
  return { ...draft, what, how: { ...draft.how, status_mapping: status, field_mapping: fields } };
}

export function toggled(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((entry) => entry !== value) : [...values, value];
}

/** The JQL a run sends: the connection's projects always wrap the custom JQL. */
export function jqlPreview(what: IntakeDraft["what"]): string {
  const projects = list(what.project_keys);
  const custom = text(what.jql).trim();
  const clause = projects.length ? `project in (${projects.join(", ")})` : "project in (the connection's projects)";
  return custom ? `${clause} AND (${custom})` : clause;
}

/** A stored draft as the drawer edits it: a Custom REST draft gets its form from `what` and `how`. */
export function editableDraft(draft: IntakeDraft): IntakeDraft {
  return draft.source_type === REST_SOURCE ? { ...draft, rest: restFormOf(draft.what, draft.how) } : draft;
}

/** Why the drawer cannot leave a step yet; null when it can. */
export function stepProblem(step: number, draft: IntakeDraft, found: IntakeDiscovery | null = null): string | null {
  if (step === 0 && !draft.connection_id) return "Pick one of this Workspace's connections.";
  if (draft.source_type === REST_SOURCE && (step === 1 || step === 3)) {
    const form = draft.rest ?? emptyRestForm();
    return restStepProblem(step, form, found?.list_operations?.find((operation) => operation.op_key === form.operation));
  }
  if (step === 1) {
    if (draft.source_type === "jira" && !list(draft.what.project_keys).length) return "Pick at least one project.";
    if (draft.source_type === "servicenow" && !list(draft.what.tables).length) return "Pick at least one table.";
  }
  if (step === 2 && draft.schedule.preset === "custom" && !(draft.schedule.cron ?? "").trim()) {
    return "Enter the cron expression or pick a preset.";
  }
  return null;
}

/** The intake's name: kept when it has one, else named after its source and selection. */
export function intakeName(draft: IntakeDraft): string {
  if (draft.name.trim()) return draft.name.trim();
  if (draft.source_type === "servicenow") return `ServiceNow ${list(draft.what.tables).join(", ") || "incident"}`;
  if (draft.source_type === REST_SOURCE) return `REST ${draft.connection_id}${draft.rest?.operation ? ` · ${draft.rest.operation}` : ""}`;
  return `Jira ${list(draft.what.project_keys).join(", ")}`.trim();
}

/** The request body (the draft without its read-only fields). */
export function draftPayload(draft: IntakeDraft): Record<string, unknown> {
  const { id: _id, is_active: _active, rest, ...payload } = draft;
  if (draft.source_type === REST_SOURCE) {
    return { source_type: draft.source_type, name: intakeName(draft), connection_id: draft.connection_id, schedule: draft.schedule,
      ...restBodyParts(rest ?? emptyRestForm(), draft.how) };
  }
  return { ...payload, name: intakeName(draft) };
}

export type PreviewFacts = {
  wouldImport: number | null;
  already: number | null;
  skipped: number | null;
  pending: string;
  automation: string;
  outside: string;
};

const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** The preview's facts from a Jira or ServiceNow dry-run summary. A Jira preview never "skips by label": the
 * automation label only marks which items the agent may start, and the per-run limit leaves items pending. */
export function previewFacts(summary: Record<string, unknown>): PreviewFacts {
  const jira = "would_import" in summary;
  return {
    wouldImport: jira ? num(summary.would_import) : num(summary.imported),
    already: jira ? num(summary.already_in_work) : num(summary.updated),
    skipped: jira ? null : num(summary.skipped_closed),
    pending: pendingText(summary) || "0",
    automation: runAutomationText(summary),
    outside: summary.filtered_outside_allowlist === true ? "some, left out" : String(num(summary.dropped_out_of_scope) ?? 0),
  };
}
