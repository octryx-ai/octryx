// Cedar policy engine model: decision log records, their one-sentence summary and links to them.
import { isRecord, num, optNum, str, strs } from "./policyEngineValues";

export type DecisionRecord = {
  id: string;
  time: string;
  point: string;
  mode: string;
  outcome: string;
  principal: string;
  action: string;
  resource: string;
  workspaceId: string;
  decision: string;
  determining: string[];
  errors: string[];
  legacyDecision: string;
  legacyReason: string;
  customVersion: number | null;
  latencyMs: number;
};

export function readDecision(raw: unknown): DecisionRecord | null {
  if (!isRecord(raw) || !str(raw.id)) return null;
  const actor = isRecord(raw.actor) ? raw.actor : {};
  const legacy = isRecord(raw.legacy) ? raw.legacy : {};
  const policySet = isRecord(raw.policy_set) ? raw.policy_set : {};
  return {
    id: str(raw.id),
    time: str(raw.time),
    point: str(raw.point),
    mode: str(raw.mode),
    outcome: str(raw.outcome),
    principal: str(actor.principal),
    action: str(raw.action),
    resource: str(raw.resource),
    workspaceId: str(raw.workspace_id),
    decision: str(raw.decision),
    determining: strs(raw.determining_policies),
    errors: strs(raw.errors),
    legacyDecision: str(legacy.decision),
    legacyReason: str(legacy.reason),
    customVersion: optNum(policySet.custom_version),
    latencyMs: num(raw.latency_ms),
  };
}

export function readDecisions(raw: unknown): { items: DecisionRecord[]; total: number } {
  const items = isRecord(raw) && Array.isArray(raw.items) ? raw.items : [];
  return {
    items: items.map(readDecision).filter((item): item is DecisionRecord => item !== null),
    total: isRecord(raw) ? num(raw.total) : 0,
  };
}

/** One sentence for a log row: what Cedar said, what the existing check said, and why. */
export function decisionSentence(record: DecisionRecord, label: (id: string) => string = (id) => id): string {
  const why = record.determining.length ? ` by ${record.determining.map(label).join(", ")}` : record.errors.length ? " (evaluation error)" : "";
  const legacy = record.legacyDecision ? `; the existing check said ${record.legacyDecision}${record.legacyReason ? ` (${record.legacyReason})` : ""}` : "";
  return `Cedar: ${record.decision}${why}${legacy}.`;
}

/** The link a refusal carries (`decision_id`) to its record in Observability → Decisions. */
export const decisionHref = (id: string) =>
  `/chat?area=operations&tab=observabilityDecisions&decision=${encodeURIComponent(id)}`;

export function readUrlDecision(search: string): string | null {
  const value = new URLSearchParams(search).get("decision");
  return value && /^[A-Za-z0-9-]{1,64}$/.test(value) ? value : null;
}
