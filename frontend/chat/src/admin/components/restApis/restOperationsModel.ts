// REST API model: shared texts, operation state and kind, server warnings and list rows.
import type { StatusTone } from "../../../layout/StatusLabel";
import type { RestDefinition, RestDefinitionListEntry, RestOperation, WriteCapability } from "./restApisApi";
import { BATCH_HINT, BATCH_LABEL, isBatch } from "./restOdataModel";

// ---- texts -------------------------------------------------------------------------------------------------------

export const WRITES_NEED_APPROVAL =
  "Writes are offered like reads, but every write waits for an approval: the chat's write plan or the workflow's approval. Runs without a person always ask.";
export const TEST_WRITE_NOTE =
  "Test calls run reads only. A write would change data in the API, so it runs from a chat (write plan) or a workflow (approval), never from here.";
export const OFFERED_TO_NOBODY = "Offered to nobody: no role is granted this operation.";
export const IMPORTED_OFF =
  "Imported operations stay off. Agents get one only after you enable it and grant it to a role.";
export const WORKSPACE_WINS = "A Workspace's own connection wins over the platform connection for calls in that Workspace.";
export const TEST_NOTE = "The test call runs with your own roles, through the same grants and scope as an agent, and is audited.";

export function scopeWithoutFilterText(params: string[]): string {
  const named = params.length ? params.join(", ") : "the scope";
  return `Scope without a result filter: ${named} is only enforced if the API honours the fixed value. Add a result filter so records outside the scope are dropped here.`;
}

// ---- operations --------------------------------------------------------------------------------------------------

export const toolNameFor = (definitionKey: string, op: Pick<RestOperation, "op_key" | "llm_name">) =>
  `rest__${definitionKey}__${(op.llm_name || "").trim() || op.op_key}`;

export type OperationState = { label: string; tone: StatusTone; hint?: string };

/** What a row of the operations list says: on, off, or enabled without grants (the exception). Reads and writes alike. */
export function operationState(op: { enabled: boolean; grants: ArrayLike<unknown>; unsupported?: string }): OperationState {
  if (isBatch(op)) return { label: BATCH_LABEL, tone: "neutral", hint: BATCH_HINT };
  if (!op.enabled) return { label: "Off", tone: "neutral" };
  if (!op.grants.length) return { label: "Offered to nobody", tone: "attention", hint: OFFERED_TO_NOBODY };
  return { label: "On", tone: "neutral" };
}

// ---- writes: run class and retries (backend) ---------------------------------------------------------------

/**
 * The run class a write needs. Deliver (the default) is the class of runs that may write to other systems; Change is
 * one step lower, so runs that may only change things inside Octryx can call it too. Either way a person approves.
 */
export const WRITE_CAPABILITIES: ReadonlyArray<{ value: WriteCapability; label: string; hint: string }> = [
  { value: "deliver", label: "Deliver", hint: "Only runs allowed to write to other systems may call it. The default." },
  { value: "change", label: "Change", hint: "Runs that may change things may call it too. For low-impact writes." },
];

export const CAPABILITY_NOTE =
  "Deliver: only runs allowed to write to other systems call it. Change: runs that may change things call it too. Both need an approval.";

export const capabilityLabel = (capability: string | null | undefined) =>
  WRITE_CAPABILITIES.find((entry) => entry.value === capability)?.label ?? "Deliver";

/** The Kind column: "Read", or "Write · Deliver" / "Write · Change" (the server's effective class). */
export function operationKind(op: Pick<RestOperation, "is_read" | "capability">): { label: string; write: boolean; hint: string } {
  if (op.is_read) return { label: "Read", write: false, hint: "" };
  const entry = WRITE_CAPABILITIES.find((item) => item.value === op.capability) ?? WRITE_CAPABILITIES[0];
  return { label: `Write · ${entry.label}`, write: true, hint: `${entry.hint} Every write waits for an approval.` };
}

/** Only a PUT or DELETE may be marked idempotent (a POST or PATCH is never sent twice). */
export const idempotentAllowed = (method: string) => ["PUT", "DELETE"].includes(method.toUpperCase());

export const grantCountText = (count: number) => (count === 0 ? "No grants" : count === 1 ? "1 grant" : `${count} grants`);

export type ServerWarning = { text: string; opId: string | null };

/**
 * The server's warnings of an API (backend: across operations, then per operation as "'<op>': …"), each with the
 * operation it names, so the panel can point to it. The label is the operation's model-facing name or its key.
 */
export function serverWarnings(definition: Pick<RestDefinition, "warnings" | "operations">): ServerWarning[] {
  const operations = definition.operations ?? [];
  return (definition.warnings ?? []).map((text) => {
    const label = /^'([^']+)': /.exec(text)?.[1];
    const op = label ? operations.find((entry) => (entry.llm_name || entry.op_key) === label) : undefined;
    return { text, opId: op?.id ?? null };
  });
}

export type DefinitionRow = {
  id: string;
  key: string;
  name: string;
  source: string;
  enabled: number;
  total: number;
  connections: number;
  warnings: number;
};

/** One row of the list, straight from the list endpoint's counts (no detail or connections loaded per API). */
export function definitionRow(entry: RestDefinitionListEntry): DefinitionRow {
  return {
    id: entry.id,
    key: entry.key,
    name: entry.name,
    source: entry.source_kind === "openapi" ? "OpenAPI import" : "Entered by hand",
    enabled: entry.enabled_operations ?? 0,
    total: entry.operations ?? 0,
    connections: entry.connections ?? 0,
    warnings: entry.warnings ?? 0,
  };
}
