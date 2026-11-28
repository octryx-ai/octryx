import { SYNC_MODE_EXECUTE, syncModeOf } from "../syncNames";
import type { WorkWorkflowDefinition } from "../workSyncWorkflowTypes";
import {
  FIELD_LABELS, REQUIRED_FIELDS, type Pair, type RestOperationInfo, type RestSourceForm,
} from "./restIntakeForm";
import type { Refusal } from "./restIntakeRefusals";

// The server's rule (custom_rest/config.PATH_RE).
const DOT_PATH = /^[A-Za-z0-9_$@:-]+(\.[A-Za-z0-9_$@:-]+)*$/;

export type RoleRule = { required: boolean; roles: string[]; problem: string | null };

// A scoped grant is enforced as the named role, so a sync without a role would read unscoped data.
export function roleRule(operation: RestOperationInfo | undefined, role: string): RoleRule {
  if (!operation) return { required: false, roles: [], problem: null };
  const roles = operation.roles ?? [];
  const named = role.trim();
  let problem: string | null = null;
  if (named && !roles.some((entry) => entry.toLowerCase() === named.toLowerCase())) {
    problem = `The role ${named} has no grant on this operation. Pick one of the granted roles.`;
  } else if (!named && operation.role_required) {
    problem = "Pick the role to read as: this operation's grants have a scope, and the scope is enforced as that role.";
  } else if (!named && !roles.length) {
    problem = "No role is granted this operation, so nothing can be read. Grant it in Connections › REST APIs.";
  }
  return { required: operation.role_required, roles, problem };
}

export function pathProblem(path: string): string | null {
  const value = path.trim();
  if (!value) return null;
  if (/\s/.test(value)) return "A dot path has no spaces.";
  if (value.startsWith(".") || value.endsWith(".") || value.includes("..")) return "A dot path has no empty step.";
  return DOT_PATH.test(value) ? null : "Use letters, digits and _ $ @ : - between the dots.";
}

export function mappingProblems(fields: Record<string, string>): Record<string, string> {
  const problems: Record<string, string> = {};
  for (const name of REQUIRED_FIELDS) {
    if (!(fields[name] ?? "").trim()) problems[name] = `${FIELD_LABELS[name]} is required: an item needs a key, a title and a status.`;
  }
  for (const [name, path] of Object.entries(fields)) {
    const problem = pathProblem(path);
    if (problem) problems[name] = problem;
  }
  return problems;
}

export function statusRowProblems(rows: RestSourceForm["statusRows"]): Record<number, string> {
  const problems: Record<number, string> = {};
  const seen = new Set<string>();
  rows.forEach((row, index) => {
    const key = row.status.trim().replace(/\s+/g, " ").toLowerCase();
    if (!key) { if (row.state) problems[index] = "Name the status in the source."; return; }
    if (!row.state) problems[index] = "Pick the Octryx state.";
    else if (seen.has(key)) problems[index] = "This status is mapped twice.";
    seen.add(key);
  });
  return problems;
}

export function parseBodyTemplate(text: string): { body: Record<string, unknown> | null; problem: string | null } {
  if (!text.trim()) return { body: null, problem: null };
  try {
    const value = JSON.parse(text) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) return { body: null, problem: "The body is a JSON object, like {\"status\": \"{target_status}\"}." };
    return { body: value as Record<string, unknown>, problem: null };
  } catch {
    return { body: null, problem: "The body is not valid JSON." };
  }
}

export function restStepRefusal(step: number, form: RestSourceForm, operation: RestOperationInfo | undefined): Refusal | null {
  if (step === 1) {
    if (!form.operation) return { field: "what.operation", text: "Pick the list operation." };
    const problem = roleRule(operation, form.role).problem;
    return problem ? { field: "what.role", text: problem } : null;
  }
  if (step === 3) {
    const fields = mappingProblems(form.fields);
    const first = Object.keys(fields)[0];
    if (first) return { field: `how.field_mapping.${first}`, text: fields[first] };
    if (Object.keys(statusRowProblems(form.statusRows)).length) return { field: "how.status_mapping", text: "Check the status mapping." };
    const body = form.writeOperation ? parseBodyTemplate(form.writeBody).problem : null;
    if (body) return { field: "how.write_back.body", text: body };
  }
  return null;
}

export function restStepProblem(step: number, form: RestSourceForm, operation: RestOperationInfo | undefined): string | null {
  const refusal = restStepRefusal(step, form, operation);
  return refusal ? (refusal.field.startsWith("how.field_mapping.") ? `${FIELD_LABELS[refusal.field.slice(18)]}: ${refusal.text}` : refusal.text) : null;
}

const pairObject = (entries: Pair[]) =>
  Object.fromEntries(entries.filter((entry) => entry.name.trim()).map((entry) => [entry.name.trim(), entry.value]));

export function restBodyParts(form: RestSourceForm, base: { automation_mode: string; automation_labels: string[]; automation_exclude_labels: string[];
  sync_mode?: string | null }) {
  const fieldMapping = Object.fromEntries(Object.entries(form.fields).map(([name, path]) => [name, path.trim()]).filter(([, path]) => path));
  const statusMapping = Object.fromEntries(form.statusRows.filter((row) => row.status.trim() && row.state)
    .map((row) => [row.status.trim(), row.state]));
  const body = parseBodyTemplate(form.writeBody).body;
  const writeBack = form.writeOperation
    ? { operation: form.writeOperation, arguments: pairObject(form.writeArguments), ...(body ? { body } : {}) }
    : null;
  return {
    what: { operation: form.operation, role: form.role.trim() || null, arguments: pairObject(form.arguments) },
    how: {
      automation_mode: base.automation_mode,
      automation_labels: base.automation_labels,
      automation_exclude_labels: base.automation_exclude_labels,
      field_mapping: fieldMapping,
      status_mapping: statusMapping,
      closed_statuses: form.closedStatuses.map((entry) => entry.trim()).filter(Boolean),
      auto_analyze_new: form.autoAnalyze,
      write_back: writeBack,
      // A missing key keeps the stored mode.
      ...("sync_mode" in base ? { sync_mode: base.sync_mode ?? null } : {}),
    },
  };
}

export type SyncSummary = { mode: "execute" | "dry_run" | "none"; label: string; text: string };

export function writeBackSync(workflows: Array<Pick<WorkWorkflowDefinition, "project_id" | "is_active" | "sync_policy">>, workspaceId: string): SyncSummary {
  const active = workflows.filter((workflow) => workflow.is_active && (!workflow.project_id || workflow.project_id === workspaceId));
  if (!active.length) return { mode: "none", label: "Off", text: "No active workflow in this Workspace, so nothing is written back." };
  if (active.some((workflow) => syncModeOf(workflow.sync_policy) === SYNC_MODE_EXECUTE)) {
    return { mode: "execute", label: "Executes in the source",
      text: "A person's transition writes the mapped status after they confirm its preview. Transitions without a person are only proposed." };
  }
  return { mode: "dry_run", label: "Dry-run only",
    text: "The Workspace's workflow writes nothing until its Sync is switched to execute (Admin › Connections › Jira write-back)." };
}
