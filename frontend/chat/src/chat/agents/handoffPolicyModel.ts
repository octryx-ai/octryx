// A PUT resets missing fields to their defaults, so every field the server sent goes back on save.

export type HandoffMode = "confirm" | "auto";
export type AllowedRequesters = "members" | "admins_and_owners";
export type PushMode = "branch" | "bundle_only" | "off";

export type HandoffPolicy = {
  mode: HandoffMode;
  autoThresholdPct: number;
  requireSparePct: number;
  allowedRequesters: AllowedRequesters;
  // null when the server does not send them; then they are not sent back either.
  push: PushMode | null;
  autoTriggerPct: number | null;
  offerTimeoutMinutes: number | null;
};

export type HandoffPolicyAnswer = { policy: HandoffPolicy; source: "workspace" | "default"; canEdit: boolean };

export const DEFAULT_HANDOFF_POLICY: HandoffPolicy = {
  mode: "confirm", autoThresholdPct: 90, requireSparePct: 50, allowedRequesters: "members", push: "branch", autoTriggerPct: 99,
  offerTimeoutMinutes: 10,
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const percent = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

export function readHandoffPolicy(payload: unknown): HandoffPolicyAnswer | null {
  if (!isRecord(payload) || !isRecord(payload.handoff)) return null;
  const raw = payload.handoff;
  const mode = raw.mode === "auto" || raw.mode === "confirm" ? raw.mode : null;
  const allowed = raw.allowed_requesters === "members" || raw.allowed_requesters === "admins_and_owners" ? raw.allowed_requesters : null;
  const threshold = percent(raw.auto_threshold_pct);
  const spare = percent(raw.require_spare_pct);
  if (!mode || !allowed || threshold === null || spare === null) return null;
  const push = raw.push === "branch" || raw.push === "bundle_only" || raw.push === "off" ? raw.push : null;
  if (raw.push !== undefined && push === null) return null;
  const trigger = raw.auto_trigger_pct === undefined ? null : percent(raw.auto_trigger_pct);
  if (raw.auto_trigger_pct !== undefined && trigger === null) return null;
  const offerTimeout = raw.offer_timeout_minutes === undefined ? null : percent(raw.offer_timeout_minutes);
  if (raw.offer_timeout_minutes !== undefined && offerTimeout === null) return null;
  return {
    policy: { mode, autoThresholdPct: threshold, requireSparePct: spare, allowedRequesters: allowed, push, autoTriggerPct: trigger,
      offerTimeoutMinutes: offerTimeout },
    source: payload.source === "workspace" ? "workspace" : "default",
    canEdit: payload.can_edit === true,
  };
}

export function policyBody(policy: HandoffPolicy): Record<string, unknown> {
  return {
    mode: policy.mode,
    auto_threshold_pct: policy.autoThresholdPct,
    require_spare_pct: policy.requireSparePct,
    allowed_requesters: policy.allowedRequesters,
    ...(policy.push !== null ? { push: policy.push } : {}),
    ...(policy.autoTriggerPct !== null ? { auto_trigger_pct: policy.autoTriggerPct } : {}),
    ...(policy.offerTimeoutMinutes !== null ? { offer_timeout_minutes: policy.offerTimeoutMinutes } : {}),
  };
}

export function policyProblems(policy: HandoffPolicy): string[] {
  const problems: string[] = [];
  if (!Number.isFinite(policy.autoThresholdPct) || policy.autoThresholdPct < 1 || policy.autoThresholdPct > 100) {
    problems.push("The allowance threshold must be a number from 1 to 100.");
  }
  if (!Number.isFinite(policy.requireSparePct) || policy.requireSparePct < 0 || policy.requireSparePct > 99) {
    problems.push("The required spare allowance must be a number from 0 to 99.");
  }
  if (policy.autoTriggerPct !== null && (!Number.isFinite(policy.autoTriggerPct) || policy.autoTriggerPct < 1 || policy.autoTriggerPct > 100)) {
    problems.push("The automatic handoff trigger must be a number from 1 to 100.");
  }
  if (policy.offerTimeoutMinutes !== null
    && (!Number.isFinite(policy.offerTimeoutMinutes) || policy.offerTimeoutMinutes < 1 || policy.offerTimeoutMinutes > 1440)) {
    problems.push("The offer time must be from 1 to 1440 minutes.");
  }
  return problems;
}

const FIELD_LABEL: Record<string, string> = {
  mode: "Mode",
  auto_threshold_pct: "Holder threshold",
  require_spare_pct: "Required spare allowance",
  allowed_requesters: "Who may receive automatically",
  push: "Work in progress travels as",
  auto_trigger_pct: "Hand over by itself at",
  offer_timeout_minutes: "Offer moves on after",
};
const fieldLabel = (path: string) => {
  const name = path.replace(/^agent_gateway_policy\.handoff\./, "");
  return FIELD_LABEL[name] ?? name;
};

const CODE_TEXT: Record<string, string> = {
  invalid_handoff_mode: "the mode must be Confirm each handoff or Hand over automatically",
  invalid_percentage: "a percentage is out of range (threshold 1 to 100, spare 0 to 99)",
  invalid_allowed_requesters: "the allowed requesters must be members, or admins and owners",
  invalid_push_mode: "work in progress must travel as a branch, only as a bundle, or not at all",
  invalid_minutes: "the offer time must be from 1 to 1440 minutes",
  unknown_field: "the server does not know one of the fields",
  agent_gateway_policy_invalid: "the Workspace's stored agent gateway policy is broken; an admin has to repair it",
};

export function policySaveErrorText(status: number, body: unknown): string {
  const detail = isRecord(body) ? body.detail : null;
  if (status === 422 && isRecord(detail) && Array.isArray(detail.errors)) {
    const parts = detail.errors.filter(isRecord).map((error) => {
      const code = typeof error.code === "string" ? error.code : "";
      const field = typeof error.field === "string" && error.field ? ` (${fieldLabel(error.field)})` : "";
      return `${CODE_TEXT[code] ?? "a value was refused"}${field}`;
    });
    if (parts.length) return `Not saved: ${parts.join("; ")}.`;
  }
  if (status === 403) return "Not saved: only Workspace admins and owners can change the handoff policy.";
  if (status === 404) return "Not saved: this Workspace was not found, or you are not a member.";
  const message = isRecord(detail) && typeof detail.message === "string" ? detail.message
    : typeof detail === "string" ? detail : "the request failed";
  return `Not saved: ${message}.`;
}

export function policyExplanation(policy: HandoffPolicy): string[] {
  if (policy.mode === "confirm") {
    return [
      "Every takeover waits until the receiving person (or a Workspace admin) confirms it in Agents → Claims and handoffs.",
      "Agents can ask, but they never confirm on their own.",
    ];
  }
  const who = policy.allowedRequesters === "members" ? "any Workspace member's agent" : "an agent of a Workspace admin or owner";
  return [
    `A takeover requested by ${who} is confirmed by Octryx without a person, but only when all of these hold:`,
    `the current holder is at its limit, at ${policy.autoThresholdPct} % or more of its weekly allowance, stopped, or silent for more than 10 minutes;`,
    `the requesting agent has used at most ${100 - policy.requireSparePct} % of its own allowance;`,
    "a handoff has been written for the item.",
    "Otherwise the takeover waits for a person's confirmation, as in the confirm mode.",
    "Octryx never hands an item to an agent that did not ask for it. When a holder needs a handoff, the item is "
      + "offered to the agent with the most spare allowance"
      + (policy.offerTimeoutMinutes !== null
        ? `; if that agent does not ask within ${policy.offerTimeoutMinutes} minutes, the offer moves to the next one.`
        : ".")
      + " It changes hands only when an agent requests the takeover.",
  ];
}

export function workStateExplanation(policy: HandoffPolicy): string[] {
  const lines: string[] = [];
  if (policy.autoTriggerPct !== null) {
    lines.push(`At ${policy.autoTriggerPct} % of a seat's five-hour or weekly allowance (the daily budget for governed sessions), the agent's launcher saves its work state and handoff and posts a takeover request by itself, once per crossing; the item is offered, never assigned, until an agent asks for it.`);
  }
  if (policy.push === "branch") lines.push("Uncommitted work travels as a WIP branch pushed to the Workspace's registered repository, or as a bundle on Octryx when the push is not possible.");
  if (policy.push === "bundle_only") lines.push("Uncommitted work travels as a git bundle on Octryx; nothing is pushed to the repository.");
  if (policy.push === "off") lines.push("Uncommitted work is committed to a local WIP branch only; it does not leave the machine.");
  return lines;
}
