// Settings → Security → Command safety. Pure: reads the
// `/api/v1/admin/command-safety` answer and builds the one save payload (backend services/command_safety/settings.py).

export type Check = { key: string; label: string; description: string; outcomes: string[]; enabled: boolean };
export type LlmRisk = { timeout_seconds: number; review_threshold: number; deny_threshold: number; review_model: string };
export type Lists = { always_deny_patterns: string[]; commands: string[]; git: string[]; kubectl: string[]; operators: string[] };
export type GuardRule = { id: string; label: string; description: string; enabled: boolean; locked: boolean };
export type WorkspaceRow = { id: string; name: string; mode: "inherit" | "override"; differences: string[] };
/** Per allow list: the platform's current defaults and the ones an admin removed (the rest were added by an admin). */
export type ListOrigin = { defaults: string[]; removed_defaults: string[] };
export type GateSettings = { checks: Check[]; llm: LlmRisk; lists: Lists; origins?: Partial<Record<keyof Lists, ListOrigin>> };
export type CommandSafety = GateSettings & { guardRules: GuardRule[]; customGuardRules: GuardRule[]; workspaces: WorkspaceRow[] };

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : "");
const strings = (value: unknown) => (Array.isArray(value) ? value.map((item) => String(item)) : []);
const num = (value: unknown, fallback: number) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);
const LIST_KEYS: (keyof Lists)[] = ["always_deny_patterns", "commands", "git", "kubectl", "operators"];

export function readGate(payload: unknown): GateSettings | null {
  if (!isRecord(payload) || !Array.isArray(payload.checks)) return null;
  const llm = isRecord(payload.llm_risk) ? payload.llm_risk : {};
  const lists = isRecord(payload.lists) ? payload.lists : {};
  return {
    checks: payload.checks.filter(isRecord).map((item) => ({
      key: text(item.key), label: text(item.label), description: text(item.description), outcomes: strings(item.outcomes),
      enabled: item.enabled === true,
    })),
    llm: {
      timeout_seconds: num(llm.timeout_seconds, 8), review_threshold: num(llm.review_threshold, 40),
      deny_threshold: num(llm.deny_threshold, 80), review_model: text(llm.review_model),
    },
    lists: Object.fromEntries(LIST_KEYS.map((key) => [key, strings(lists[key])])) as Lists,
    origins: readOrigins(payload.list_origins),
  };
}

function readOrigins(value: unknown): Partial<Record<keyof Lists, ListOrigin>> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(LIST_KEYS.filter((key) => isRecord(value[key])).map((key) => {
    const origin = value[key] as Record<string, unknown>;
    return [key, { defaults: strings(origin.defaults), removed_defaults: strings(origin.removed_defaults) }];
  }));
}

const readRules = (value: unknown): GuardRule[] => (Array.isArray(value) ? value.filter(isRecord).map((item) => ({
  id: text(item.id), label: text(item.label) || text(item.id), description: text(item.description), enabled: item.enabled !== false,
  locked: item.locked === true,
})) : []);

export function readCommandSafety(payload: unknown): CommandSafety | null {
  const gate = readGate(payload);
  if (!gate || !isRecord(payload)) return null;
  return {
    ...gate,
    guardRules: readRules(payload.guard_rules),
    customGuardRules: readRules(payload.custom_guard_rules),
    workspaces: Array.isArray(payload.workspaces) ? payload.workspaces.filter(isRecord).map((item) => ({
      id: text(item.id), name: text(item.name), mode: item.mode === "override" ? "override" : "inherit", differences: strings(item.differences),
    })) : [],
  };
}

/** The one save payload; `guardRules` only on the platform page. */
export function gatePayload(settings: GateSettings, guardRules?: GuardRule[], customGuardRules?: GuardRule[]) {
  return {
    checks: Object.fromEntries(settings.checks.map((check) => [check.key, check.enabled])),
    llm_risk: {
      timeout_seconds: settings.llm.timeout_seconds, review_threshold: settings.llm.review_threshold,
      deny_threshold: settings.llm.deny_threshold,
    },
    lists: settings.lists,
    ...(guardRules ? { guard_rules: Object.fromEntries(guardRules.filter((rule) => !rule.locked).map((rule) => [rule.id, rule.enabled])) } : {}),
    ...(customGuardRules ? { custom_guard_rules: Object.fromEntries(customGuardRules.map((rule) => [rule.id, rule.enabled])) } : {}),
  };
}

export const OUTCOME_TEXT: Record<string, { text: string; tone: string }> = {
  block: { text: "Block", tone: "refuse" },
  ask: { text: "Ask a person", tone: "report" },
};

/** Why the gate cannot be saved, one line each; empty when it can. */
export function gateProblems(settings: GateSettings): string[] {
  const problems: string[] = [];
  if (!settings.checks.some((check) => check.enabled)) problems.push("Keep at least one check on.");
  const { timeout_seconds: timeout, review_threshold: review, deny_threshold: deny } = settings.llm;
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 60) problems.push("The timeout is a whole number of seconds from 1 to 60.");
  if (![review, deny].every((value) => Number.isInteger(value) && value >= 0 && value <= 100)) problems.push("Scores are whole numbers from 0 to 100.");
  if (deny < review) problems.push("“Block from score” cannot be below “Ask a person from score”.");
  return problems;
}

const CODE_TEXT: Record<string, string> = {
  command_safety_no_check: "keep at least one check on",
  command_safety_deny_below_review: "the block score cannot be below the ask score",
  command_safety_invalid: "a value is out of range",
};

export function saveErrorText(error: unknown): string {
  const record = isRecord(error) ? error : {};
  if (record.status === 403) return "Not saved: only platform admins change command safety.";
  const code = text(record.code);
  return `Not saved: ${CODE_TEXT[code] ?? (text(record.message) || "the request was refused")}.`;
}
