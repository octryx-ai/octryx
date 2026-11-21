// Content policy notices of `turn_execution_summary.v1`: typed parse and pure presentation.
//
// Backend `services/content_routing/notices.py` owns the closed record: what a content policy did with a model
// request or a tool result of this turn (kind, reason, detector × count, masked count, policies, decision, model
// change). Only names, counts and ids arrive here; this module never sees or renders the data itself. An
// unknown kind or reason renders nothing.

import { decisionHref } from "../../admin/components/policyEngine/policyEngineDecisions";

export const CONTENT_OBLIGATION_KINDS = ["mask", "reroute", "mask_reroute", "block"] as const;
export const CONTENT_OBLIGATION_REASONS = [
  "content_obligation_applied",
  "content_policy_denied",
  "content_policy_unavailable",
  "content_route_unavailable",
  "content_obligation_insufficient",
  "content_obligation_conflict",
] as const;

export type ContentObligationKind = (typeof CONTENT_OBLIGATION_KINDS)[number];
export type ContentObligationReason = (typeof CONTENT_OBLIGATION_REASONS)[number];

export type TurnContentObligation = {
  source: "model" | "tool_result";
  kind: ContentObligationKind;
  reason: ContentObligationReason;
  applied: boolean;
  found: [string, number][];
  masked: number;
  policies: string[];
  decisionId: string | null;
  modelFrom: string | null;
  modelTo: string | null;
  tool: string | null;
};

const MAX_NOTICES = 10;
const NAME = /^[A-Za-z][A-Za-z0-9_.:/@+-]{0,127}$/;
const DECISION = /^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$/;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const name = (value: unknown): string | null => (typeof value === "string" && NAME.test(value) ? value : null);
const count = (value: unknown): number =>
  typeof value === "number" && Number.isInteger(value) && value > 0 ? value : 0;
const decision = (value: unknown): string | null =>
  typeof value === "string" && DECISION.test(value) && !/^\d+$/.test(value) ? value : null;

function parseOne(value: unknown): TurnContentObligation | null {
  if (!isRecord(value)) return null;
  const kind = CONTENT_OBLIGATION_KINDS.find((entry) => entry === value.kind);
  const reason = CONTENT_OBLIGATION_REASONS.find((entry) => entry === value.reason);
  if (!kind || !reason) return null;
  const found = isRecord(value.found)
    ? Object.entries(value.found).flatMap(([key, n]): [string, number][] => (name(key) && count(n) ? [[key, count(n)]] : []))
    : [];
  return {
    source: value.source === "tool_result" ? "tool_result" : "model",
    kind,
    reason,
    applied: reason === "content_obligation_applied",
    found,
    masked: count(value.masked),
    policies: Array.isArray(value.policies) ? value.policies.map(name).filter((entry): entry is string => !!entry) : [],
    decisionId: decision(value.decision_id),
    modelFrom: name(value.model_from),
    modelTo: name(value.model_to),
    tool: name(value.tool),
  };
}

export function parseTurnContentObligations(value: unknown): TurnContentObligation[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, MAX_NOTICES).map(parseOne).filter((entry): entry is TurnContentObligation => entry !== null);
}

// What a detector finds, in words; a custom or unknown detector is "sensitive data".
const DATA_LABEL: Record<string, string> = {
  iban: "bank account data",
  email: "personal data",
  phone: "personal data",
  secrets: "a credential",
};

export function dataLabel(found: [string, number][]): string {
  const labels = [...new Set(found.map(([detector]) => DATA_LABEL[detector] ?? "sensitive data"))];
  return labels.length ? labels.join(" and ") : "sensitive data";
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const policyList = (policies: string[]) => policies.join(", ") || "a content policy";
export const foundText = (found: [string, number][]) =>
  found.map(([detector, n]) => `${detector} ×${n}`).join(" · ") || "—";

export type ContentObligationField = { label: string; value: string };

export type ContentObligationPresentation = {
  tone: "attention" | "error";
  head: string;
  code: string;
  text: string;
  fields: ContentObligationField[];
  whyHref: string | null;
};

function headOf(notice: TurnContentObligation, data: string): string {
  const routed = Boolean(notice.modelTo);
  if (notice.applied) {
    if (notice.source === "tool_result") return `${capitalize(data)} masked in the ${notice.tool ?? "tool"} result`;
    if (routed && notice.masked) return `Sent to the approved model, ${data} masked`;
    if (routed) return `Sent to the approved model because of ${data}`;
    return `${capitalize(data)} masked before the model saw it`;
  }
  if (notice.source === "tool_result") return `Tool result kept from the model: it contains ${data}`;
  if (notice.reason === "content_route_unavailable") return `Not sent: the approved model for ${data} is not available`;
  if (notice.reason === "content_policy_denied") return `Not sent: the message contains ${data}`;
  return "Not sent: the content policy could not be applied";
}

function textOf(notice: TurnContentObligation, data: string): string {
  const policies = policyList(notice.policies);
  const masked = `${notice.masked} ${notice.masked === 1 ? "value was" : "values were"} masked`;
  if (notice.applied && notice.source === "tool_result") {
    return `The ${notice.tool ?? "tool"} result contained ${data}. Following the policy ${policies}, ${masked} before the model saw it.`;
  }
  if (notice.applied) {
    const route = notice.modelTo ? ` and this conversation now runs on ${notice.modelTo}` : "";
    const change = notice.masked ? `${masked}${route}` : `this conversation now runs on ${notice.modelTo}`;
    return `Your message contained ${data}. Following the policy ${policies}, ${change}.${notice.masked ? " The model only sees the masked values." : ""}`;
  }
  if (notice.reason === "content_route_unavailable") {
    return `The policy ${policies} requires ${notice.modelTo ?? "an approved model"} for ${data}, which cannot take this request. Nothing was sent to a model. Ask a Workspace admin, or remove the data from the message.`;
  }
  if (notice.reason === "content_policy_denied") {
    return notice.source === "tool_result"
      ? `The policy ${policies} does not allow ${data} from this tool into the conversation. Use a governed tool that returns masked data.`
      : `The policy ${policies} blocks ${data} here. Nothing was sent to a model. Remove the data from the message.`;
  }
  return `The policy ${policies} could not be applied to this request (${notice.reason}), so nothing was sent to a model.`;
}

export function presentContentObligation(notice: TurnContentObligation): ContentObligationPresentation {
  const data = dataLabel(notice.found);
  const fields: ContentObligationField[] = [{ label: "Found", value: foundText(notice.found) }];
  if (notice.tool) fields.push({ label: "Tool", value: notice.tool });
  if (notice.modelTo && notice.applied) {
    fields.push({ label: "Model", value: `${notice.modelFrom ? `${notice.modelFrom} → ` : ""}${notice.modelTo} (until you start a new chat)` });
  }
  if (notice.decisionId) fields.push({ label: "Decision", value: notice.decisionId });
  return {
    tone: notice.applied ? "attention" : "error",
    head: headOf(notice, data),
    code: notice.reason,
    text: textOf(notice, data),
    fields,
    whyHref: notice.decisionId ? decisionHref(notice.decisionId) : null,
  };
}
