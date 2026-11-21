// Usage limits, time formatting, context fill and compactions of a Mac session.
import { num, str } from "./mobilePayloadValues";

export type Usage = {
  seat: {
    percent: number;
    window: "5h" | "7d";
    resetsAt: string | null;
  } | null;
  budget: { spent: number; limit: number } | null;
  warn: boolean;
};

/** The usage line: the tighter of the seat's 5-hour and 7-day windows, and the Workspace's API budget today. */
export function readUsage(raw: unknown): Usage {
  const item =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const seatRaw =
    item.seat_allowance && typeof item.seat_allowance === "object"
      ? (item.seat_allowance as Record<string, unknown>)
      : null;
  let seat: Usage["seat"] = null;
  if (seatRaw) {
    const five = num(seatRaw.five_hour_pct);
    const seven = num(seatRaw.seven_day_pct);
    if (five !== null || seven !== null) {
      const useSeven = seven !== null && (five === null || seven > five);
      seat = {
        percent: Math.round((useSeven ? seven : five) ?? 0),
        window: useSeven ? "7d" : "5h",
        resetsAt: str(
          useSeven ? seatRaw.seven_day_resets_at : seatRaw.five_hour_resets_at,
        ),
      };
    }
  }
  const spent = num(item.spent_usd);
  const limit = num(item.limit_usd);
  const budget =
    spent !== null && limit !== null && limit > 0 ? { spent, limit } : null;
  const warn =
    (seat?.percent ?? 0) >= 80 ||
    (budget ? budget.spent / budget.limit >= 0.8 : false);
  return { seat, budget, warn };
}

export function usageText(usage: Usage): string {
  const parts: string[] = [];
  if (usage.seat)
    parts.push(`Seat ${usage.seat.percent} % (${usage.seat.window})`);
  if (usage.budget)
    parts.push(
      `API ${usage.budget.spent.toFixed(0)} of ${usage.budget.limit.toFixed(0)} $ today`,
    );
  return parts.join(" · ");
}

export function shortTime(
  iso: string | null | undefined,
  now: number = Date.now(),
): string {
  const at = Date.parse(iso || "");
  if (Number.isNaN(at)) return "";
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h` : `${Math.round(hours / 24)} d`;
}

export function untilDate(iso: string | null | undefined): string {
  const at = Date.parse(iso || "");
  return Number.isNaN(at)
    ? ""
    : new Date(at).toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
}

// How full the Mac session's context is: the Mac reports it after each step of a turn.
export type ContextUsage = {
  tokens: number;
  window: number;
  percent: number | null;
};

export function contextUsage(
  jobs: { events: { seq: number; body: Record<string, unknown> }[] }[],
): ContextUsage | null {
  let tokens = 0;
  let window = 0;
  for (const job of jobs) {
    for (const event of job.events) {
      const body = event.body ?? {};
      if (body.kind !== "context" || typeof body.tokens !== "number") continue;
      tokens = body.tokens;
      if (typeof body.window === "number" && body.window > 0)
        window = body.window;
    }
  }
  if (!tokens) return null;
  return {
    tokens,
    window,
    percent: window ? Math.min(100, Math.round((tokens / window) * 100)) : null,
  };
}

const compact = (value: number) =>
  value >= 1_000_000
    ? `${+(value / 1_000_000).toFixed(1)}M`
    : value >= 1000
      ? `${Math.round(value / 1000)}k`
      : `${value}`;

/** "Context 48k / 1M · 5%", or "Context 48k" while the window is not known yet. */
export function contextLabel(usage: ContextUsage): string {
  if (!usage.window) return `Context ${compact(usage.tokens)}`;
  return `Context ${compact(usage.tokens)} / ${compact(usage.window)} · ${usage.percent}%`;
}

export function compactions(
  jobs: { events: { seq: number; body: Record<string, unknown> }[] }[],
): { count: number; freed: number } {
  let count = 0;
  let freed = 0;
  for (const job of jobs)
    for (const event of job.events) {
      const body = event.body ?? {};
      if (body.kind !== "compaction") continue;
      count += 1;
      const pre = typeof body.pre_tokens === "number" ? body.pre_tokens : 0;
      const post = typeof body.post_tokens === "number" ? body.post_tokens : 0;
      freed += Math.max(0, pre - post);
    }
  return { count, freed };
}
