// What a payload does not carry is left out, never guessed.

import { engineLabel } from "../chat/engines/engineModel";
import { readableModelName } from "../chat/devices/modelNames";
import type { MyDevice } from "../chat/devices/devicesModel";
import { CODEX_SEAT_LABEL, readCodexSeat } from "../admin/components/dataClassification/codexSeatModel";
import { seatReasonText } from "../admin/components/dataClassification/dataClassificationSeat";
import { seatStateView } from "../admin/components/dataClassification/seatStateModel";

export const ROUTE_SEAT = "Own subscription";
export const ROUTE_GOVERNED = "Company model";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const pct = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? Math.round(value) : null);

const ROUTES: Record<string, string> = { own_subscription: ROUTE_SEAT, company_model: ROUTE_GOVERNED };

export function routeLabel(route: string | null | undefined): string | null {
  return ROUTES[text(route)] ?? null;
}

export function routeOf(profile: string | null | undefined): string | null {
  const value = text(profile);
  if (!value) return null;
  // A Mac's own Claude Code profile (`local:<name>`) is paid by that profile's own subscription.
  if (value === "seat" || value.startsWith("local:")) return ROUTE_SEAT;
  if (value === "governed") return ROUTE_GOVERNED;
  return null;
}

export type RunLine = { engine: string; route: string | null; model: string | null };

type RunSource = { engine?: string | null; profile?: string | null; route?: string | null; model?: string | null };

export function runLine(source: RunSource): RunLine {
  const model = text(source.model);
  return {
    engine: engineLabel(source.engine),
    route: routeLabel(source.route) ?? routeOf(source.profile),
    model: model ? readableModelName(model) : null,
  };
}

export function workflowRunLine(run: { engine?: unknown; route?: unknown }): RunLine | null {
  const engine = text(run.engine);
  const route = text(run.route);
  return engine || route ? runLine({ engine: engine || null, route }) : null;
}

export function threadRunLineText(target: unknown): string {
  if (!isRecord(target) || target.kind !== "device") return "";
  const device = text(target.deviceName);
  if (!text(target.engine) && !text(target.profile) && !text(target.model)) return device;
  return runLineText(runLine({ engine: text(target.engine) || null, profile: text(target.profile), model: text(target.model) }), device);
}

export function runLineText(line: RunLine, ...more: (string | null | undefined)[]): string {
  return [line.engine, line.route, line.model, ...more].filter(Boolean).join(" · ");
}

export function runLineRest(line: RunLine, ...more: (string | null | undefined)[]): string {
  return [line.route, line.model, ...more].filter(Boolean).join(" · ");
}

export type SeatWindow = { key: "5h" | "7d"; label: string; percent: number; resetsAt: string | null };

export type SeatStatus = {
  // true: signed in on an online Mac; false: online Macs, none signed in; null: no Mac online (not known).
  signedIn: boolean | null;
  macs: string[];
  windows: SeatWindow[];
  updatedAt: string | null;
};

export type SeatKind = "claude" | "codex";

type SeatMac = Pick<MyDevice, "name" | "connected" | "seatLogin" | "codexSeatLogin">;

export function readSeatStatus(devices: SeatMac[] | null, usage: unknown, kind: SeatKind = "claude"): SeatStatus {
  const online = (devices ?? []).filter((device) => device.connected);
  const macs = online.filter((device) => (kind === "codex" ? device.codexSeatLogin : device.seatLogin)).map((device) => device.name);
  const signedIn = macs.length ? true : online.length ? false : null;
  const key = kind === "codex" ? "codex_seat_allowance" : "seat_allowance";
  const allowance = isRecord(usage) && isRecord(usage[key]) ? usage[key] : null;
  const windows: SeatWindow[] = [];
  if (allowance) {
    const five = pct(allowance.five_hour_pct);
    const seven = pct(allowance.seven_day_pct);
    if (five !== null) windows.push({ key: "5h", label: "5 hours", percent: five, resetsAt: text(allowance.five_hour_resets_at) || null });
    if (seven !== null) windows.push({ key: "7d", label: "7 days", percent: seven, resetsAt: text(allowance.seven_day_resets_at) || null });
  }
  return { signedIn, macs, windows, updatedAt: (allowance && text(allowance.updated_at)) || null };
}

export function seatSignInText(status: SeatStatus): string {
  if (status.signedIn) return `Signed in on ${status.macs.join(", ")}`;
  return status.signedIn === false ? "Not signed in" : "No Mac online";
}

export const CLAUDE_SEAT_LABEL = "Claude subscription (seat)";

export type SeatRule = {
  key: "claude" | "codex";
  label: string;
  value: string;
  note: string | null;
};

function rule(key: SeatRule["key"], label: string, mode: unknown, inEffect: unknown, reason: unknown, set?: unknown): SeatRule {
  const why = text(reason) || null;
  const view = seatStateView(mode === "allowed" || mode === "forbidden" ? mode : null,
    typeof inEffect === "boolean" ? inEffect : null, typeof set === "boolean" ? set : null);
  if (view.byDefault) return { key, label, value: view.mode === "allowed" ? "Allowed by default" : "Off by default", note: null };
  if (mode === "forbidden") return { key, label, value: "Forbidden", note: null };
  if (mode === "allowed") {
    const blocked = inEffect === false;
    return { key, label, value: "Allowed", note: blocked ? `Not in effect: ${seatReasonText(why)}.` : null };
  }
  return { key, label, value: "Unknown", note: null };
}

export function seatRules(seatMode: unknown): SeatRule[] {
  const answer = isRecord(seatMode) ? seatMode : {};
  const codex = readCodexSeat(answer);
  return [
    rule("claude", CLAUDE_SEAT_LABEL, answer.seat_mode, answer.in_effect, answer.reason, answer.seat_mode_set),
    rule("codex", CODEX_SEAT_LABEL, codex.mode, codex.inEffect, codex.reason, answer.codex_seat_mode_set),
  ];
}

function seatLogins(device: Pick<MyDevice, "seatLogin" | "codexSeatLogin">): string {
  if (device.seatLogin && device.codexSeatLogin) return " (Claude and Codex signed in)";
  if (device.codexSeatLogin) return " (Codex signed in)";
  return device.seatLogin ? " (signed in)" : " (not signed in)";
}

export function deviceRoutes(device: Pick<MyDevice, "profiles" | "connected" | "seatLogin" | "codexSeatLogin">): string {
  const seat = device.profiles.includes("seat")
    ? `${ROUTE_SEAT}${device.connected ? seatLogins(device) : ""}`
    : "";
  return [device.profiles.includes("governed") ? ROUTE_GOVERNED : "", seat].filter(Boolean).join(" · ");
}

export function resetText(iso: string | null, now: Date = new Date()): string {
  const at = new Date(iso ?? "");
  if (!iso || Number.isNaN(at.getTime())) return "";
  const time = at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return at.toDateString() === now.toDateString() ? time : `${at.toLocaleDateString([], { weekday: "short" })} ${time}`;
}
