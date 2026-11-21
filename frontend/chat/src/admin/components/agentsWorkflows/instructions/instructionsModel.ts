// Agents & workflows → Instructions (backend `services/instructions`, `/api/v1/instructions`): guidance the agent
// reads, bound explicitly. Pure parsing, filtering and labels; the page and the drawer render them.

export const INSTRUCTIONS_PATH = "/api/v1/instructions";

export type InstructionScope = "global" | "workspace" | "agent";
export type InstructionBinding = "always" | "workflow" | "on_request";

export type InstructionFinding = {
  code: string;
  names: string[];
  tokens?: number;
  budget?: number;
  // tool_forbidden_by_policy: the forbidding policy ("Tool policy deny list", "Cedar policy <id>") and its rule text.
  policy?: string;
  detail?: string;
};

export type InstructionVersion = {
  id: string;
  version: number;
  state: string;
  tokenEstimate: number;
  body: string;
  findings: InstructionFinding[];
  findingsAccepted: boolean;
};

export type InstructionRow = {
  id: string;
  key: string;
  title: string;
  scopeType: InstructionScope;
  scopeId: string | null;
  scopeName: string;
  binding: InstructionBinding;
  workflowKey: string | null;
  layer: string;
  layerBudget: number;
  status: string;
  published: InstructionVersion | null;
  latest: InstructionVersion | null;
  versions: InstructionVersion[];
};

type Json = Record<string, unknown>;
const record = (value: unknown): Json => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));
const SCOPES: InstructionScope[] = ["global", "workspace", "agent"];
const BINDINGS: InstructionBinding[] = ["always", "workflow", "on_request"];

export function readFinding(raw: unknown): InstructionFinding {
  const item = record(raw);
  return {
    code: text(item.code),
    names: list(item.names).map(text),
    tokens: typeof item.tokens === "number" ? item.tokens : undefined,
    budget: typeof item.budget === "number" ? item.budget : undefined,
    policy: text(item.policy) || undefined,
    detail: text(item.detail) || undefined,
  };
}

export function readVersion(raw: unknown): InstructionVersion | null {
  const item = record(raw);
  if (!item.id) return null;
  return {
    id: text(item.id),
    version: Number(item.version) || 0,
    state: text(item.state),
    tokenEstimate: Number(item.token_estimate) || 0,
    body: text(item.body),
    findings: list(item.findings).map(readFinding),
    findingsAccepted: item.findings_accepted === true,
  };
}

export function readInstruction(raw: unknown): InstructionRow {
  const item = record(raw);
  const scope = text(item.scope_type) as InstructionScope;
  const binding = text(item.binding) as InstructionBinding;
  return {
    id: text(item.id),
    key: text(item.key),
    title: text(item.title),
    scopeType: SCOPES.includes(scope) ? scope : "global",
    scopeId: text(item.scope_id) || null,
    scopeName: text(item.scope_name),
    binding: BINDINGS.includes(binding) ? binding : "always",
    workflowKey: text(item.workflow_key) || null,
    layer: text(item.layer),
    layerBudget: Number(item.layer_budget) || 0,
    status: text(item.status),
    published: readVersion(item.published),
    latest: readVersion(item.latest),
    versions: list(item.versions).map(readVersion).filter((value): value is InstructionVersion => value !== null),
  };
}

export function readInstructions(raw: unknown): InstructionRow[] {
  return list(record(raw).items).map(readInstruction);
}

export function scopeLabel(row: Pick<InstructionRow, "scopeType" | "scopeName" | "binding">): string {
  if (row.scopeType === "workspace") return row.scopeName ? `Workspace · ${row.scopeName}` : "Workspace";
  if (row.scopeType === "agent") return row.scopeName ? `Agent · ${row.scopeName}` : "Agent";
  return row.binding === "workflow" ? "Workflow" : "Global";
}

export function boundLabel(row: Pick<InstructionRow, "binding" | "workflowKey" | "scopeName" | "scopeType">): string {
  if (row.binding === "workflow") return `workflow ${row.workflowKey ?? ""}`.trim();
  if (row.binding === "on_request") return "on request (by key)";
  return row.scopeType === "global" ? "always" : `always in ${row.scopeName || row.scopeType}`;
}

export function statusLabel(row: InstructionRow): { label: string; kind: "active" | "attention" | "danger" | "neutral" } {
  if (row.status === "retired") return { label: "Retired", kind: "neutral" };
  const latest = row.latest;
  if (latest && latest.state === "in_review") return { label: `In review v${latest.version}`, kind: "attention" };
  if (latest && latest.state === "draft") return { label: `Draft v${latest.version}`, kind: "attention" };
  if (row.published) return { label: `Published v${row.published.version}`, kind: "active" };
  return { label: "Draft", kind: "attention" };
}

const FINDING_TEXT: Record<string, (finding: InstructionFinding) => string> = {
  unknown_workflow: (item) => `The bound workflow ${item.names.join(", ")} has no published definition.`,
  tool_not_in_workflow: (item) => `Names tools the bound workflow does not offer: ${item.names.join(", ")}.`,
  tool_against_capability: (item) => `Names changing tools in a read-only workflow or agent: ${item.names.join(", ")}.`,
  duplicates_skill: (item) => `Duplicates a published skill: ${item.names.join(", ")}.`,
  tool_forbidden_by_policy: (item) =>
    `Names ${item.names.join(", ")}, which this scope's policy forbids: ${item.policy ?? "a forbid policy"}.`,
  over_budget: (item) => `The ${item.names.join(", ")} layer would hold ${item.tokens ?? "?"} of ${item.budget ?? "?"} tokens.`,
};

export function findingText(finding: InstructionFinding): string {
  return (FINDING_TEXT[finding.code] ?? ((item: InstructionFinding) => `${item.code}: ${item.names.join(", ")}`))(finding);
}

export const tokenEstimate = (body: string): number => Math.ceil(body.length / 4);

export type InstructionScopeFilter = "" | InstructionScope | "workflow";

export function filterInstructions(rows: InstructionRow[], query: string, scope: InstructionScopeFilter): InstructionRow[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (scope === "workflow" && row.binding !== "workflow") return false;
    if (scope && scope !== "workflow" && row.scopeType !== scope) return false;
    if (!needle) return true;
    return [row.key, row.title, row.workflowKey ?? "", row.scopeName].some((value) => value.toLowerCase().includes(needle));
  });
}
