// Runtime → Execution → Limits & budgets. Pure: no requests, no React.
//
// Contract:
//   GET /admin/chat/api/panel/runtime-settings -> the platform values (keys below)
//   PUT /admin/chat/api/panel/runtime-settings {only this page's keys} -> settings (absent keys are unchanged)
//   GET /api/v1/admin/limits/overview -> {workspace_overrides: {key: [{workspace_id, name, value}]},
//       gateway_daily_baseline_usd, environment_limits: [{key, label, value}], budgets: [budget], workspaces, users}
//   POST /admin/chat/api/panel/budget-policies {id?, name, project_id | user_id, reset_period, <period>_cost_limit,
//       warn_at_percent, block_at_percent, is_active}

export type LimitUnit = "usd" | "tokens" | "seconds" | "chars" | "items";
export type LimitRow = {
  key: string; label: string; unit: LimitUnit; appliesTo: string; costCap?: boolean; technical?: boolean;
};

export const SESSION_CAP = "agent_session_cost_limit_usd";
export const REQUEST_CAP = "agent_request_cost_limit_usd";
export const GATEWAY_DAILY = "gateway_daily_usd_per_person";

export const LIMIT_ROWS: readonly LimitRow[] = [
  { key: SESSION_CAP, label: "Cost per session", unit: "usd", costCap: true,
    appliesTo: "Chat, workflows, Claude Code (company models)" },
  { key: REQUEST_CAP, label: "Cost per request", unit: "usd", costCap: true,
    appliesTo: "Chat, workflows, Claude Code (company models)" },
  { key: "max_output_tokens_default", label: "Longest answer (models without their own)", unit: "tokens",
    appliesTo: "Every model call" },
  { key: "runtime_request_timeout_seconds", label: "Model request timeout", unit: "seconds", appliesTo: "Every model call" },
  { key: "approx_chars_per_token", label: "Characters per token (estimate)", unit: "chars", technical: true,
    appliesTo: "Budget estimates before a call" },
  { key: "saved_script_max_output_chars", label: "Saved script output", unit: "chars", technical: true,
    appliesTo: "Saved scripts" },
  { key: "trace_max_string", label: "Trace text length", unit: "chars", technical: true, appliesTo: "Run traces" },
  { key: "trace_max_list_items", label: "Trace list items", unit: "items", technical: true, appliesTo: "Run traces" },
  { key: "trace_max_dict_items", label: "Trace object fields", unit: "items", technical: true, appliesTo: "Run traces" },
];

export const UNIT_SUFFIX: Record<LimitUnit, string> = { usd: "USD", tokens: "tokens", seconds: "s", chars: "characters", items: "items" };

export type Overrides = Record<string, { workspaceId: string; name: string; value: string }[]>;
export type Budget = {
  id: string; name: string; scope: string; scopeLabel: string; workspaceId: string; userId: string; period: string;
  amount: string; used: string; warnAt: number; stopAt: number; active: boolean;
};
export type Overview = {
  overrides: Overrides; gatewayBaseline: number; environment: { key: string; label: string; value: string }[];
  budgets: Budget[]; workspaces: { id: string; name: string }[]; users: { id: string; name: string }[];
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown) => (typeof value === "string" ? value : typeof value === "number" ? String(value) : "");
const list = (value: unknown) => (Array.isArray(value) ? value.filter(isRecord) : []);

export function readOverview(payload: unknown): Overview {
  const body = isRecord(payload) ? payload : {};
  const raw = isRecord(body.workspace_overrides) ? body.workspace_overrides : {};
  const overrides: Overrides = {};
  for (const [key, items] of Object.entries(raw)) {
    overrides[key] = list(items).map((item) => ({ workspaceId: str(item.workspace_id), name: str(item.name), value: str(item.value) }));
  }
  return {
    overrides,
    gatewayBaseline: typeof body.gateway_daily_baseline_usd === "number" ? body.gateway_daily_baseline_usd : 0,
    environment: list(body.environment_limits).map((item) => ({ key: str(item.key), label: str(item.label), value: str(item.value) })),
    budgets: list(body.budgets).map((item) => ({
      id: str(item.id), name: str(item.name), scope: str(item.scope), scopeLabel: str(item.scope_label),
      workspaceId: str(item.workspace_id), userId: str(item.user_id), period: str(item.period),
      amount: str(item.amount_usd), used: str(item.used_usd),
      warnAt: Number(item.warn_at_percent) || 80, stopAt: Number(item.block_at_percent) || 100, active: item.is_active !== false,
    })),
    workspaces: list(body.workspaces).map((item) => ({ id: str(item.id), name: str(item.name) })),
    users: list(body.users).map((item) => ({ id: str(item.id), name: str(item.name) })),
  };
}

/** The editable drafts from the stored settings; a cost cap of 0 is the explicit "No limit". */
export function draftsFromSettings(settings: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(LIMIT_ROWS.map((row) => {
    const value = settings[row.key];
    return [row.key, typeof value === "number" || typeof value === "string" ? String(value) : ""];
  }));
}

export const isNoLimit = (row: LimitRow, draft: string) => Boolean(row.costCap) && draft.trim() === "0";

/** Only the changed limits, or the first problem. An empty field is never sent (it would mean "no limit"). */
export function limitsPayload(
  drafts: Record<string, string>, stored: Record<string, string>,
): { payload: Record<string, number> } | { error: string } {
  const payload: Record<string, number> = {};
  for (const row of LIMIT_ROWS) {
    const text = (drafts[row.key] ?? "").trim();
    if (text === (stored[row.key] ?? "").trim()) continue;
    if (!text) return { error: `${row.label}: enter a value${row.costCap ? " or choose No limit" : ""}.` };
    const value = Number(text);
    if (!Number.isFinite(value) || value < 0 || (row.unit !== "usd" && !Number.isInteger(value))) {
      return { error: `${row.label}: enter ${row.unit === "usd" ? "an amount" : "a whole number"}.` };
    }
    payload[row.key] = value;
  }
  return { payload };
}

export const overrideCount = (overview: Overview | null, key: string) => overview?.overrides[key]?.length ?? 0;

export const usd = (value: string) => (value === "" ? "—" : `$${Number(value).toFixed(2)}`);

export function usedText(budget: Budget): string {
  if (!budget.amount || budget.used === "") return "—";
  const amount = Number(budget.amount);
  const percent = amount > 0 ? Math.round((Number(budget.used) / amount) * 100) : 0;
  return `${usd(budget.used)} (${percent}%)`;
}

export const PERIODS: readonly { value: string; label: string; field: string }[] = [
  { value: "daily", label: "Day", field: "daily_cost_limit" },
  { value: "weekly", label: "Week", field: "weekly_cost_limit" },
  { value: "monthly", label: "Month", field: "monthly_cost_limit" },
];
export const periodLabel = (period: string) => PERIODS.find((item) => item.value === period)?.label ?? period;

export type BudgetDraft = {
  id: string; scope: "workspace" | "person"; targetId: string; period: string; amount: string; warnAt: string; stopAt: string;
  active: boolean;
};

export const emptyBudget = (): BudgetDraft => ({
  id: "", scope: "workspace", targetId: "", period: "monthly", amount: "", warnAt: "80", stopAt: "100", active: true,
});

export const draftFromBudget = (budget: Budget): BudgetDraft => ({
  id: budget.id, scope: budget.userId ? "person" : "workspace", targetId: budget.userId || budget.workspaceId,
  period: budget.period, amount: budget.amount, warnAt: String(budget.warnAt), stopAt: String(budget.stopAt),
  active: budget.active,
});

/** The budget policy body, or the problem. Only a cost amount is offered here (requests/tokens stay API-only). */
export function budgetPayload(
  draft: BudgetDraft, names: { workspaces: Overview["workspaces"]; users: Overview["users"] },
): { payload: Record<string, unknown> } | { error: string } {
  if (!draft.targetId) return { error: `Choose the ${draft.scope === "person" ? "person" : "Workspace"}.` };
  const amount = Number(draft.amount.trim());
  if (!draft.amount.trim() || !Number.isFinite(amount) || amount <= 0) return { error: "Enter an amount above zero." };
  const warnAt = Number(draft.warnAt);
  const stopAt = Number(draft.stopAt);
  if (!Number.isInteger(warnAt) || warnAt < 1 || !Number.isInteger(stopAt) || stopAt < warnAt || stopAt > 1000) {
    return { error: "Warn at and stop at are whole percentages; stop at is at least warn at and at most 1000." };
  }
  const period = PERIODS.find((item) => item.value === draft.period) ?? PERIODS[2];
  const scopeName = (draft.scope === "person" ? names.users : names.workspaces).find((item) => item.id === draft.targetId)?.name
    ?? draft.targetId;
  return {
    payload: {
      ...(draft.id ? { id: draft.id } : {}),
      name: `${scopeName} · ${period.label}`,
      ...(draft.scope === "person" ? { user_id: draft.targetId } : { project_id: draft.targetId }),
      reset_period: period.value,
      [period.field]: amount,
      warn_at_percent: warnAt,
      block_at_percent: stopAt,
      is_active: draft.active,
    },
  };
}

export const atLimitText = (budget: Budget) => (budget.stopAt <= 100 ? "Stop" : `Warn (stops at ${budget.stopAt}%)`);
