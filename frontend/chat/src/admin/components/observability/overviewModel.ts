// Observability → Overview: what needs attention, at a glance. Nothing is decided here.
import type { HealthLink, HealthStatus } from "./healthModel";

export type AttentionItem = {
  severity: "danger" | "attention";
  label: string;
  title: string;
  cause: string;
  age: string;
  action: string;
  link: NonNullable<HealthLink>;
};
export type StripEntry = { key: string; label: string; status: HealthStatus; counts: Partial<Record<HealthStatus, number>>; detail: string };
export type OverviewPayload = {
  checked_at: string;
  attention: AttentionItem[];
  health: { summary: Record<HealthStatus, number>; strip: StripEntry[] };
  spend: { month_spend: number; priced_coverage: number | null; since: string };
  decisions_today: { by_outcome: Record<string, number>; total: number; allowed: number };
};

export function attentionBreakdown(items: AttentionItem[]): string {
  const failing = items.filter((item) => item.label.includes("failing")).length;
  const waiting = items.filter((item) => item.label.includes("waiting")).length;
  const cost = items.filter((item) => item.label.includes("cost")).length;
  const parts = [failing ? `${failing} failing` : "", waiting ? `${waiting} waiting` : "", cost ? `${cost} cost` : ""];
  return parts.filter(Boolean).join(" · ") || "nothing needs attention";
}

export function decisionsBreakdown(byOutcome: Record<string, number>): string {
  const order = ["denied", "needs_approval", "approved", "rejected", "expired", "remedied"];
  const parts = order.filter((key) => byOutcome[key]).map((key) => `${byOutcome[key]} ${key.replace(/_/g, " ")}`);
  return parts.join(" · ") || "no decisions recorded today";
}
