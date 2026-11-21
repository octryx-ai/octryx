import { serverTimeOf } from "../../admin/utils/serverTime";
import { formatClock, formatDateTime } from "../../admin/utils/dateTime";

// Connected clients of the "Agents" area. Pure: no requests, no React.
//
// Contract (backend agent-gateway presence endpoint):
//   GET /api/v1/agent-gateway/presence?project_id=<id>
//   -> {items: [{id, session_key_hash, sessions, user: {id, display_name}, device: {id, name} | null, client, profile, state,
//                work_item: {id, key, title} | null, branch, model, last_seen_at,
//                allowance: {five_hour_pct, five_hour_resets_at, seven_day_pct, seven_day_resets_at, status} | null}]}
// Membership is required. `allowance` is null unless the caller is a Workspace admin/owner or a platform admin;
// the UI shows allowance bars only when the server returned them and never derives or estimates them.

export type PresenceState = "active" | "idle" | "stopped" | "limit_reached" | "unknown";

export type Allowance = {
  fiveHourPct: number | null;
  fiveHourResetsAt: string | null;
  sevenDayPct: number | null;
  sevenDayResetsAt: string | null;
  status: string | null;
};

// The sticky content state of the client's current conversation (names, counts, ids; never the data).
export type ClientSensitivity = {
  categories: string[];
  detectors: [string, number][];
  since: string | null;
  policyId: string | null;
  routeTo: string | null;
};

export type ConnectedClient = {
  // One entry per person and device, with its own id (DELETE …/presence/{id}) and the number of running sessions it
  // folds.
  id: string;
  sessions: number;
  device: string;
  user: string;
  userId: string;
  client: string;
  profile: string;
  state: PresenceState;
  workItem: { id: string; key: string; title: string } | null;
  branch: string;
  model: string;
  lastSeenAt: string | null;
  allowance: Allowance | null;
  sensitive: ClientSensitivity | null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const percent = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const STATES: PresenceState[] = ["active", "idle", "stopped", "limit_reached"];

function readAllowance(value: unknown): Allowance | null {
  if (!isRecord(value)) return null;
  return {
    fiveHourPct: percent(value.five_hour_pct),
    fiveHourResetsAt: text(value.five_hour_resets_at) || null,
    sevenDayPct: percent(value.seven_day_pct),
    sevenDayResetsAt: text(value.seven_day_resets_at) || null,
    status: text(value.status) || null,
  };
}

const NAME = /^[A-Za-z][A-Za-z0-9_.:/@+-]{0,127}$/;
const nameOf = (value: unknown) => (typeof value === "string" && NAME.test(value) ? value : null);

function readSensitivity(value: unknown): ClientSensitivity | null {
  if (!isRecord(value)) return null;
  const categories = Array.isArray(value.categories)
    ? value.categories.map(nameOf).filter((entry): entry is string => entry !== null)
    : [];
  const detectors = isRecord(value.detectors)
    ? Object.entries(value.detectors).flatMap(([key, n]): [string, number][] =>
      nameOf(key) && typeof n === "number" && Number.isInteger(n) && n > 0 ? [[key, n]] : [])
    : [];
  const routeTo = nameOf(value.route_to);
  if (!categories.length && !routeTo) return null;
  return { categories, detectors, since: text(value.since) || null, policyId: nameOf(value.policy_id), routeTo };
}

/** One connected client read strictly; null when the entry has no id. */
export function readClient(value: unknown): ConnectedClient | null {
  const id = isRecord(value) ? text(value.id) : "";
  if (!isRecord(value) || !id) return null;
  const user = isRecord(value.user) ? text(value.user.display_name) || text(value.user.id) : "";
  const state = STATES.find((entry) => entry === text(value.state)) ?? "unknown";
  const item = isRecord(value.work_item) && text(value.work_item.key)
    ? { id: text(value.work_item.id), key: text(value.work_item.key), title: text(value.work_item.title) }
    : null;
  const device = isRecord(value.device) ? text(value.device.name) : "";
  const sessions = typeof value.sessions === "number" && Number.isInteger(value.sessions) && value.sessions > 0
    ? value.sessions : 0;
  return {
    id,
    sessions,
    device,
    user: user || "Unknown user",
    userId: isRecord(value.user) ? text(value.user.id) : "",
    client: text(value.client) || "unknown client",
    profile: text(value.profile),
    state,
    workItem: item,
    branch: text(value.branch),
    model: text(value.model),
    lastSeenAt: text(value.last_seen_at) || null,
    allowance: readAllowance(value.allowance),
    sensitive: readSensitivity(value.sensitive),
  };
}

/** The listing read strictly; null when the answer is not a presence listing. */
export function readPresence(payload: unknown): ConnectedClient[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;
  return payload.items.map(readClient).filter((entry): entry is ConnectedClient => entry !== null);
}

/** "Anna on MacBook" (or the client when no device is named): the object a removal names. */
export function clientObjectName(client: ConnectedClient): string {
  return `${client.user} on ${client.device || client.client}`;
}

export const STATE_LABEL: Record<PresenceState, string> = {
  active: "active",
  idle: "idle",
  stopped: "stopped",
  limit_reached: "limit reached",
  unknown: "state not reported",
};

export const STATE_TONE: Record<PresenceState, "active" | "neutral" | "attention" | "danger"> = {
  active: "active",
  idle: "neutral",
  stopped: "neutral",
  limit_reached: "danger",
  unknown: "neutral",
};

/** "octryx-claude · seat" (the profile decides whose allowance is used; governed runs through the platform). */
export function clientLabel(client: ConnectedClient): string {
  const profile = client.profile === "seat" ? "seat" : client.profile === "governed" ? "governed" : client.profile;
  return profile ? `${client.client} · ${profile}` : client.client;
}

/** The "Sensitive data" badge: "PII · governed until /clear" with counts, time and policy in the tooltip. */
export function sensitivityBadge(sensitive: ClientSensitivity | null): { label: string; title: string } | null {
  if (!sensitive) return null;
  const categories = sensitive.categories.map((entry) => entry.toUpperCase()).join(", ") || "Sensitive";
  const since = serverTimeOf(sensitive.since);
  const title = [
    sensitive.detectors.map(([detector, n]) => `${detector} ×${n}`).join(", "),
    since === null ? "" : `since ${formatClock(since)}`,
  ].filter(Boolean).join(" ") + (sensitive.policyId ? ` · policy ${sensitive.policyId}` : "");
  return { label: `${categories} · ${sensitive.routeTo ? "governed" : "sensitive"} until /clear`, title: title.trim() };
}

/** The model column: "claude-sonnet-5 → company-model" while a content policy routes the conversation. */
export function modelLabel(client: ConnectedClient): string {
  const routed = client.sensitive?.routeTo;
  if (routed && routed !== client.model) return client.model ? `${client.model} → ${routed}` : routed;
  return client.model || "—";
}

/** Whether any listed client carries allowance: then the caller is an admin/owner and the column is shown. */
export function showsAllowance(clients: ConnectedClient[]): boolean {
  return clients.some((client) => client.allowance !== null);
}

export type AllowanceBar = { label: string; pct: number; width: number; tone: "active" | "attention" | "danger"; resets: string | null };

/** A bar for one window, or null when the server sent no percentage for it. */
export function allowanceBar(label: string, pct: number | null, resetsAt: string | null, now = Date.now()): AllowanceBar | null {
  if (pct === null) return null;
  const width = Math.max(0, Math.min(100, pct));
  const reset = serverTimeOf(resetsAt);
  return {
    label,
    pct: Math.round(pct),
    width,
    tone: pct >= 100 ? "danger" : pct >= 80 ? "attention" : "active",
    resets: reset === null ? null : reset <= now ? "resets now" : `resets ${formatDateTime(reset)}`,
  };
}

/** The summary line under the list: one count of connected clients (all but stopped) and how many work now. */
export function presenceSummary(clients: ConnectedClient[]): string {
  if (!clients.length) return "No agent client is connected to this Workspace.";
  const connected = clients.filter((client) => client.state !== "stopped").length;
  const working = clients.filter((client) => client.state === "active").length;
  const limited = clients.filter((client) => client.state === "limit_reached").length;
  return [
    `${connected} connected`,
    `${working} working now`,
    limited ? `${limited} at their allowance limit` : "",
  ].filter(Boolean).join(" · ");
}

/** Refusals of the presence API in words. */
export function presenceErrorText(error: unknown): { kind: "forbidden" | "error"; text: string } {
  const record = isRecord(error) ? error : null;
  const status = typeof record?.status === "number" ? record.status : null;
  // Rule 1: out of scope answers like missing, so a 404 is a Workspace you are not a member of.
  if (status === 401 || status === 403 || status === 404) {
    return { kind: "forbidden", text: "Only members of this Workspace can see its agents." };
  }
  const message = typeof record?.message === "string" && record.message ? record.message : "the request failed";
  return { kind: "error", text: `The agent clients could not be loaded: ${message}.` };
}

export const PRESENCE_POLL_MS = 15_000;
