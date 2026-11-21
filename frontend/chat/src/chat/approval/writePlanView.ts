// A chat's write plan waiting for the person: one confirmation per
// request. The gate's change preview (kind "write_plan") names the request, the scope the plan works in and every
// intended write with its fields. This turns it into what the card shows on desktop and phone: the scope as labelled
// chips grouped by system, one row per write (the action in words, the connection, the why, every field in full),
// and the result line once decided. Pure, so both cards and their tests share it.
import type { StatusTone } from "../../layout/StatusLabel";
import { isRestTool, restRequestLines, restRequestView } from "./restRequestView";

export type WritePlanScopeChip = { kind: string; value: string; text: string };
export type WritePlanScopeGroup = { key: string; label: string; chips: WritePlanScopeChip[] };
export type WritePlanField = { key: string; label: string; value: string };

export type WritePlanWrite = {
  key: string;
  // "Create Jira ticket": the tool in words, or the tool's own preview title ("Create Epic Kitchen helper v1 in MM").
  action: string;
  // What the write is about when the action is only the tool in words ("Kitchen helper v1", "feature/kitchen-helper").
  subject: string;
  connection: string;
  why: string;
  fields: WritePlanField[];
  // The tool's own preview, when it has one: its summary, its lines, and before/after as written.
  summary: string;
  details: string[];
  before: string;
  after: string;
};

export type WritePlanView = {
  planId: string;
  amendment: boolean;
  heading: string;
  request: string;
  count: number;
  countLabel: string;
  scope: WritePlanScopeGroup[];
  writes: WritePlanWrite[];
  // Amendment only: what the person already confirmed, shown collapsed.
  confirmed: WritePlanWrite[];
  // From COLLAPSE_FROM writes on, rows start as one line each and the card offers "Expand all".
  many: boolean;
};

// From this many writes on, rows start collapsed so Approve stays reachable without long scrolling.
export const COLLAPSE_FROM = 4;

// The refusal codes the gate returns to the model before a plan exists or when a write is outside it (contract §4).
// They belong to the model's own loop and are never an error for the person.
export const WRITE_PLAN_REFUSAL_CODES = new Set(["write_plan_required", "write_plan_amendment_required"]);

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

const PROPER: Record<string, string> = {
  jira: "Jira",
  confluence: "Confluence",
  bitbucket: "Bitbucket",
  github: "GitHub",
  gitlab: "GitLab",
  teams: "Teams",
  slack: "Slack",
  pr: "PR",
  mr: "MR",
  url: "URL",
  id: "ID",
};

/** "create_jira_ticket" -> "Create Jira ticket"; product names keep their spelling. */
export function toolWords(tool: string): string {
  const parts = String(tool || "")
    .replace(/^mcp__.+?__/, "")
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => PROPER[part.toLowerCase()] ?? part.toLowerCase());
  if (!parts.length) return "";
  const [first, ...rest] = parts;
  return [first[0].toUpperCase() + first.slice(1), ...rest].join(" ");
}

function fieldLabel(key: string): string {
  return toolWords(key);
}

// A field's value in full: text as written, a list of plain values as "a, b", anything else as indented JSON.
function fieldValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value) && value.every((item) => ["string", "number", "boolean"].includes(typeof item))) {
    return value.join(", ");
  }
  return JSON.stringify(value, null, 2);
}

const SUBJECT_KEYS = ["summary", "title", "branch_name", "name", "page_title", "issue_key", "key", "subject"];

const SCOPE_KINDS: Record<string, { group: string; label: string }> = {
  repository: { group: "code", label: "Repository" },
  branch: { group: "code", label: "Branch" },
  pull_request: { group: "code", label: "Pull request" },
  jira_project: { group: "jira", label: "Jira project" },
  jira_issue: { group: "jira", label: "Issue" },
  confluence_space: { group: "confluence", label: "Confluence space" },
  confluence_page: { group: "confluence", label: "Confluence page" },
  work_item: { group: "work", label: "Work item" },
  recipient: { group: "people", label: "Recipient" },
  run: { group: "runs", label: "Run" },
  target: { group: "other", label: "Target" },
};

const SCOPE_GROUPS: Array<[string, string]> = [
  ["code", "Code"],
  ["jira", "Jira"],
  ["confluence", "Confluence"],
  ["work", "Work items"],
  ["people", "Recipients"],
  ["runs", "Runs"],
  ["other", "Other"],
];

/** The scope as chips ("Jira project MM", "Branch feature/kitchen-helper"), grouped by system, each value once. */
export function writePlanScope(raw: unknown): WritePlanScopeGroup[] {
  const seen = new Set<string>();
  const byGroup = new Map<string, WritePlanScopeChip[]>();
  for (const entry of Array.isArray(raw) ? raw : []) {
    const item = record(entry);
    const kind = text(item?.kind).toLowerCase();
    const value = text(item?.value);
    if (!value) continue;
    const id = `${kind}\u0000${value.toLowerCase()}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const known = SCOPE_KINDS[kind];
    const label = known?.label ?? (toolWords(kind) || "Target");
    const group = known?.group ?? "other";
    const chips = byGroup.get(group) ?? [];
    chips.push({ kind, value, text: `${label} ${value}` });
    byGroup.set(group, chips);
  }
  return SCOPE_GROUPS.filter(([key]) => byGroup.has(key)).map(([key, label]) => ({
    key,
    label,
    chips: byGroup.get(key) ?? [],
  }));
}

/**
 * A custom REST write (backend): the request as the server previewed it. Its raw fields (as the model wrote
 * them) are never shown; the fields are the server's masked body, the lines say where it goes and the scope.
 */
function readRestWrite(item: Record<string, unknown>, position: number): WritePlanWrite | null {
  const view = restRequestView(item);
  if (!view) return null;
  return {
    key: `${typeof item.index === "number" ? item.index : position}-${text(item.tool)}`,
    action: [view.method, view.path].filter(Boolean).join(" ") || "Write",
    subject: view.target,
    connection: view.connection,
    why: text(item.why),
    fields: view.fields.map((field) => ({ key: field.key, label: field.label, value: field.value })),
    summary: "",
    details: restRequestLines(view),
    before: "",
    after: "",
  };
}

function readWrite(entry: unknown, position: number): WritePlanWrite | null {
  const item = record(entry);
  if (!item) return null;
  if (isRestTool(item.tool)) return readRestWrite(item, position);
  const tool = text(item.tool);
  const fieldsRecord = record(item.fields) ?? {};
  const fields: WritePlanField[] = Object.entries(fieldsRecord)
    .filter(([key, value]) => key !== "connection" && value !== null && value !== undefined && value !== "")
    .map(([key, value]) => ({ key, label: fieldLabel(key), value: fieldValue(value) }));
  const own = text(item.title);
  const ownTitle = own && !/^execute tool\b/i.test(own) ? own : "";
  const subjectKey = SUBJECT_KEYS.find((key) => typeof fieldsRecord[key] === "string" && text(fieldsRecord[key]));
  const connector = text(item.connector);
  const connection = text(item.connection) || text(fieldsRecord.connection) || (connector ? toolWords(connector) : "");
  const before = item.before === null || item.before === undefined ? "" : fieldValue(item.before);
  const after = item.after === null || item.after === undefined ? "" : fieldValue(item.after);
  return {
    key: `${typeof item.index === "number" ? item.index : position}-${tool}`,
    action: ownTitle || toolWords(tool) || "Write",
    subject: ownTitle || !subjectKey ? "" : text(fieldsRecord[subjectKey]),
    connection,
    why: text(item.why),
    fields,
    summary: text(item.summary),
    details: Array.isArray(item.details) ? item.details.map((line) => String(line ?? "")).filter((line) => line.trim()) : [],
    before,
    after,
  };
}

function readWrites(raw: unknown): WritePlanWrite[] {
  return (Array.isArray(raw) ? raw : []).flatMap((entry, index) => {
    const write = readWrite(entry, index);
    return write ? [write] : [];
  });
}

export function countLabel(count: number): string {
  return `${count} ${count === 1 ? "write" : "writes"}`;
}

/** The card's view of a write plan, or null for every other approval (they keep their own card). */
export function writePlanView(preview: Record<string, unknown> | null | undefined): WritePlanView | null {
  if (!preview || typeof preview !== "object" || preview.kind !== "write_plan") return null;
  const writes = readWrites(preview.writes);
  const amends = text(preview.amends);
  const amendment = Boolean(amends);
  return {
    planId: text(preview.plan_id),
    amendment,
    heading: amendment ? "Confirm a change to the plan" : "Confirm the write plan",
    request: text(preview.request).replace(/\s+/g, " "),
    count: writes.length,
    countLabel: countLabel(writes.length),
    scope: writePlanScope(preview.scope),
    writes,
    confirmed: amendment ? readWrites(preview.confirmed_writes) : [],
    many: writes.length >= COLLAPSE_FROM,
  };
}

export const WRITE_PLAN_NOTE =
  "After you confirm, these writes run without asking again. Anything outside this scope asks again.";

// Who decided: the approval's decider (`approvedBy`, a user id, set for approve and reject) against the viewer.
export type WritePlanDecider = {
  approvedBy?: string | null;
  // The decider's name when the payload carries one (not served yet; see the PR).
  approvedByName?: string | null;
  currentUserId?: string | null;
};

/** "you" when the viewer decided, the decider's name when known, "another person" otherwise, "" when unknown. */
export function deciderLabel(decider: WritePlanDecider = {}): string {
  const by = text(decider.approvedBy);
  const viewer = text(decider.currentUserId);
  if (by && viewer && by === viewer) return "you";
  const name = text(decider.approvedByName);
  if (name) return name;
  return by ? "another person" : "";
}

/** The decided card's one calm line, or null while the plan still waits for the person. */
export function writePlanResult(
  status: string | null | undefined,
  view: Pick<WritePlanView, "amendment" | "count">,
  decider: WritePlanDecider = {},
): { label: string; tone: StatusTone } | null {
  const key = String(status || "pending").trim().toLowerCase();
  const who = deciderLabel(decider);
  const by = who ? ` by ${who}` : "";
  const what = view.amendment ? "Change confirmed" : "Plan confirmed";
  if (key === "approved") return { label: `${what}${by} · ${countLabel(view.count)}`, tone: "neutral" };
  if (key === "rejected" || key === "denied") return { label: `Rejected${by}`, tone: "neutral" };
  if (key === "expired") return { label: "Expired · nothing was written", tone: "neutral" };
  return null;
}

/** The session's active plan (contract §5) as the composer's quiet notice, or null when none is active. */
export function writePlanNotice(writePlan: unknown): string | null {
  const plan = record(writePlan);
  if (!plan) return null;
  const writes = Array.isArray(plan.writes) ? plan.writes.length : 0;
  const chips = writePlanScope(plan.scope).flatMap((group) => group.chips.map((chip) => chip.text));
  const shown = chips.slice(0, 3).join(", ");
  const more = chips.length > 3 ? ` +${chips.length - 3}` : "";
  return ["Write plan confirmed", countLabel(writes), shown ? `scope ${shown}${more}` : ""].filter(Boolean).join(" · ");
}

/** True for a tool result that only asks the model to propose (or amend) the plan first (contract §4). */
export function isWritePlanRefusal(result: unknown): boolean {
  const top = record(result);
  if (!top) return false;
  const candidates = [top, record(top.detail), record(top.preview), record(top.error)];
  return candidates.some((item) => WRITE_PLAN_REFUSAL_CODES.has(text(item?.code)));
}
