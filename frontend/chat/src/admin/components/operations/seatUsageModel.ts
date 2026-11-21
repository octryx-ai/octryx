// Operations › Costs › Seats by person (backend): per person, what their seat calls would cost
// via the API at list price, and apart from it their real API cost. Never a sum of the two, no subscription price, no
// ratio, no "savings". A model without a list price gets no estimate; its calls show as "no list price (seat only)".
// GET /api/v1/admin/operations/seat-usage?workspace_id=&days=; admins in the Problems scope. Pure reading and wording.
import { modelDisplayName } from "../../../chat/header/runDetailsFacts";
import { NO_SEAT, readSeat, readSeatLabels, type SeatFigures, type SeatLabels } from "../../../chat/cost/seatEquivalent";

export type SeatModel = { model: string; name: string; calls: number; seat: SeatFigures };
export type SeatAccount = { pseudonym: string; provider: string; label: string; calls: number; seat: SeatFigures; models: SeatModel[] };
export type SeatWorkspace = { id: string; name: string; equivalentUsd: number; apiCostUsd: number };
export type SeatAllowance = {
  client: string;
  label: string;
  fiveHourPct: number | null;
  fiveHourResetsAt: string | null;
  sevenDayPct: number | null;
  sevenDayResetsAt: string | null;
  status: string;
  updatedAt: string | null;
};
export type SeatPerson = {
  userId: string;
  name: string;
  // What the seat calls would cost via the API (list price), with the calls that have no list price.
  seat: SeatFigures;
  // The real API cost of the person's other calls, shown apart.
  apiCostUsd: number;
  seatCalls: number;
  accounts: SeatAccount[];
  workspaces: SeatWorkspace[];
  allowance: SeatAllowance[];
  limitHits: number;
};
export type SeatUsageReport = {
  days: number;
  from: string | null;
  to: string | null;
  labels: SeatLabels;
  totals: { seat: SeatFigures; apiCostUsd: number; seatCalls: number };
  people: SeatPerson[];
};

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const list = (value: unknown): Record<string, unknown>[] =>
  (Array.isArray(value) ? value.map(record).filter((item): item is Record<string, unknown> => item !== null) : []);
const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.round(value) : 0);
const usd = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0);
const pct = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const equivalent = (item: Record<string, unknown>) => readSeat(item, "api_equivalent_usd", "unpriced_calls");

const CLIENTS: Record<string, string> = { claude_code: "Claude Code", "claude-code": "Claude Code", codex: "Codex" };

/** "claude_code" → "Claude Code"; an unknown client in words, never the raw key. */
export function clientLabel(client: string): string {
  if (CLIENTS[client]) return CLIENTS[client];
  const words = client.replace(/[-_]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Seat";
}

function modelOf(item: Record<string, unknown>): SeatModel {
  const model = text(item.model);
  return { model, name: model ? modelDisplayName(model) : "Unknown model", calls: count(item.calls), seat: equivalent(item) };
}

function accountOf(item: Record<string, unknown>): SeatAccount {
  const provider = text(item.provider);
  return {
    pseudonym: text(item.seat),
    provider,
    label: text(item.label) || (provider === "openai_codex_seat" ? "ChatGPT" : "Claude"),
    calls: count(item.calls),
    seat: equivalent(item),
    models: list(item.models).map(modelOf),
  };
}

function allowanceOf(item: Record<string, unknown>): SeatAllowance {
  const client = text(item.client);
  return {
    client,
    label: clientLabel(client),
    fiveHourPct: pct(item.five_hour_pct),
    fiveHourResetsAt: text(item.five_hour_resets_at) || null,
    sevenDayPct: pct(item.seven_day_pct),
    sevenDayResetsAt: text(item.seven_day_resets_at) || null,
    status: text(item.status),
    updatedAt: text(item.updated_at) || null,
  };
}

function personOf(item: Record<string, unknown>): SeatPerson | null {
  const userId = text(item.user_id);
  if (!userId) return null;
  return {
    userId,
    // display_name (the display name, else the username), username for servers without it.
    name: text(item.display_name) || text(item.username) || "Unknown person",
    seat: equivalent(item),
    apiCostUsd: usd(item.api_cost_usd),
    seatCalls: count(item.seat_calls),
    accounts: list(item.seats).map(accountOf),
    workspaces: list(item.workspaces).map((entry) => ({
      id: text(entry.workspace_id),
      name: text(entry.name) && text(entry.name) !== "(none)" ? text(entry.name) : "No Workspace",
      equivalentUsd: usd(entry.api_equivalent_usd),
      apiCostUsd: usd(entry.api_cost_usd),
    })),
    allowance: list(item.allowance).map(allowanceOf),
    limitHits: count(item.limit_hits),
  };
}

/** The report, people by seat equivalent (the server's order, kept stable on ties). */
export function readSeatUsage(payload: unknown): SeatUsageReport {
  const body = record(payload);
  const window = record(body?.window);
  const totals = record(body?.totals) ?? {};
  const people = list(body?.people).map(personOf).filter((person): person is SeatPerson => person !== null)
    .sort((a, b) => b.seat.equivalentUsd - a.seat.equivalentUsd);
  return {
    days: count(window?.days),
    from: text(window?.from) || null,
    to: text(window?.to) || null,
    labels: readSeatLabels(body?.labels),
    totals: { seat: equivalent(totals), apiCostUsd: usd(totals.api_cost_usd), seatCalls: count(totals.seat_calls) },
    people,
  };
}

export const EMPTY_SEAT_USAGE: SeatUsageReport = {
  days: 0, from: null, to: null, labels: readSeatLabels(null),
  totals: { seat: NO_SEAT, apiCostUsd: 0, seatCalls: 0 }, people: [],
};

/** "Claude · seat-3f9a": the account's provider label with its pseudonym. */
export function accountTitle(account: Pick<SeatAccount, "label" | "pseudonym">): string {
  return account.pseudonym ? `${account.label} · ${account.pseudonym}` : account.label;
}

/** "5 hours 71 % · 7 days 22 %"; the parts that are known. */
export function allowanceText(allowance: Pick<SeatAllowance, "fiveHourPct" | "sevenDayPct">): string {
  const part = (label: string, value: number | null) => (value === null ? "" : `${label} ${Math.round(value)} %`);
  return [part("5 hours", allowance.fiveHourPct), part("7 days", allowance.sevenDayPct)].filter(Boolean).join(" · ")
    || "No allowance reported";
}

/** "1 limit hit", "3 limit hits", "No limit hit". */
export function limitHitsText(hits: number): string {
  if (!hits) return "No limit hit";
  return `${hits} limit hit${hits === 1 ? "" : "s"}`;
}

/** "Last 30 days" under the person's name. */
export function windowText(report: Pick<SeatUsageReport, "days">): string {
  return report.days ? `Last ${report.days} days` : "";
}

/** The sentence under the table: what the figures are, and what they are not. */
export function seatNote(report: Pick<SeatUsageReport, "days">): string {
  return `Calls in the last ${report.days} days. A seat call costs the platform nothing; its figure is what the same call `
    + "would cost via the API at list price. The API cost is the person's other calls and is never added to it.";
}

export type SeatRefusal = { status: number; code: string; message: string };

/** A 404 without a reason: this server has no seat-usage route yet, so the sub-view is hidden. */
export function isMissingRoute(error: Pick<SeatRefusal, "status" | "code" | "message">): boolean {
  return error.status === 404 && !error.code && (!error.message || /^not found$/i.test(error.message));
}

/** A refusal in words: 403 and a Workspace 404 in plain sentences, else the server's own message. */
export function refusalText(error: Pick<SeatRefusal, "status" | "code" | "message">): string {
  if (error.status === 403) return "Only platform and Workspace admins can see seat usage.";
  if (error.status === 404) return "This Workspace does not exist, or you are not a member of it.";
  return error.message || "Seat usage could not be loaded.";
}

/** The allowance status in words ("allowed_warning" → "Near the limit"); colour only for an exception. */
export function allowanceStatus(status: string): { label: string; tone: "neutral" | "attention" } {
  if (status === "rejected") return { label: "Limit reached", tone: "attention" };
  if (status === "allowed_warning") return { label: "Near the limit", tone: "attention" };
  if (status === "allowed") return { label: "Within the limit", tone: "neutral" };
  const words = status.replace(/[-_]+/g, " ").trim();
  return { label: words ? words.charAt(0).toUpperCase() + words.slice(1) : "", tone: "neutral" };
}
