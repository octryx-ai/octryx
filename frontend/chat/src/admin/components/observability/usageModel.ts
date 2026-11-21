// Observability → Usage & costs: one cost source (usage_events), a window, priced coverage, budgets read-only.

export type UsageWindow = "7d" | "30d" | "month";

export type UsageModelRow = {
  provider: string;
  model: string;
  tokens: number;
  unpriced_tokens: number;
  cost: number;
  pricing: "priced" | "unpriced" | "not_billed";
};

export type UsageBudget = { name: string; limit: number; used: number; percent: number | null } | null;

export type UsagePayload = {
  window: UsageWindow;
  since: string;
  until: string;
  tiles: {
    spend: number;
    priced_coverage: number | null;
    unpriced_tokens: number;
    platform_billed_tokens: number;
    tokens: number;
    cache_tokens: number;
    active_users: number;
  };
  unpriced_policy: "block" | "warn";
  daily: Array<{ day: string; spend: number }>;
  by_model: UsageModelRow[];
  by_workspace: Array<{ workspace_id: string | null; workspace_name: string | null; runs: number; cost: number; budget: UsageBudget }>;
  by_user: Array<{ user_id: string; user_name: string; runs: number; cost: number }>;
  budgets: Array<{ limit: string; scope: string; cap: number | null; used: number; percent: number | null }>;
};

export const USAGE_WINDOWS: Array<{ value: UsageWindow; label: string }> = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "month", label: "This month" },
];

export function rangeLabel(since: string, until: string): string {
  const options: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", timeZone: "UTC" };
  return `${new Date(since).toLocaleDateString("en-GB", options)} – ${new Date(until).toLocaleDateString("en-GB", options)} · UTC`;
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value * 100)} %`;
}

export function unpricedShare(tiles: UsagePayload["tiles"]): number {
  return tiles.platform_billed_tokens ? tiles.unpriced_tokens / tiles.platform_billed_tokens : 0;
}

export function unpricedModels(rows: UsageModelRow[]): UsageModelRow[] {
  return rows.filter((row) => row.pricing === "unpriced");
}

/** Axis top for a bar chart: the next multiple of a round step above the maximum (never 0). */
export function axisTop(values: number[]): number {
  const max = Math.max(0, ...values);
  if (max <= 0) return 1;
  const step = max <= 1 ? 0.25 : max <= 10 ? 2.5 : max <= 100 ? 25 : 50;
  return Math.ceil(max / step) * step;
}
