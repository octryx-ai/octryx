// Seat traffic (backend): where seat model calls go out, the platform switch
// `agent_gateway.seat_traffic`.
//   GET|PUT /api/v1/admin/seat-traffic -> {seat_traffic, modes, can_edit}; PUT {seat_traffic} (platform admins, audited).
// `device` (default): the person's Mac sends each call the server admitted; `gateway`: the platform server relays it.
// Never an automatic fallback. Pure: no React.

export const SEAT_TRAFFIC_PATH = "/api/v1/admin/seat-traffic";
export const SEAT_TRAFFIC_AUDIT_ACTION = "admin.agent_gateway.seat_traffic_updated";

export type SeatTrafficMode = "device" | "gateway";
export type SeatTrafficSetting = { mode: SeatTrafficMode; canEdit: boolean };

export const SEAT_TRAFFIC_HELP = "Where seat calls go out: device = from the person's own Mac (the server admits each "
  + "call, the token never leaves the Mac), gateway = through the platform server. No automatic fallback.";

export const SEAT_TRAFFIC_OPTIONS: { value: SeatTrafficMode; title: string; desc: string }[] = [
  { value: "device", title: "From the person's device",
    desc: "The server admits each call; the Mac sends it with the person's login. The token never leaves the Mac." },
  { value: "gateway", title: "Through the platform gateway",
    desc: "The platform server sends each call. The server needs to reach the provider." },
];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export const seatTrafficTitle = (mode: SeatTrafficMode) =>
  SEAT_TRAFFIC_OPTIONS.find((option) => option.value === mode)?.title ?? mode;

/** The server's answer; anything but `gateway` reads as the default `device`. */
export function readSeatTrafficSetting(raw: unknown): SeatTrafficSetting | null {
  if (!isRecord(raw) || !("seat_traffic" in raw)) return null;
  return { mode: raw.seat_traffic === "gateway" ? "gateway" : "device", canEdit: raw.can_edit === true };
}

export const seatTrafficBody = (mode: SeatTrafficMode) => ({ seat_traffic: mode });

/** The in-page confirmation before a change: it affects every seat session. */
export function seatTrafficConfirmText(next: SeatTrafficMode): string {
  const how = next === "device"
    ? "Every seat call then goes out from the person's own Mac. Macs need the updated launcher and direct access to the provider."
    : "Every seat call then goes out through the platform server. The server needs access to the provider.";
  return `Switch seat traffic to "${seatTrafficTitle(next)}"? This affects every seat session. ${how} There is no automatic fallback.`;
}

/** Hidden when the GET is forbidden; any other failure shows a problem. */
export function seatTrafficLoadOutcome(status: number | null): "hidden" | "problem" {
  return status === 403 ? "hidden" : "problem";
}

const CODE_TEXT: Record<string, string> = {
  unknown_setting: "the server does not know this setting.",
  invalid_seat_traffic: "the value must be device or gateway.",
};

export function seatTrafficSaveError(status: number, body: unknown): string {
  if (status === 403) return "Not saved: only platform admins can change seat traffic.";
  if (status === 422) {
    const detail = isRecord(body) ? body.detail : null;
    const errors = isRecord(detail) && Array.isArray(detail.errors) ? detail.errors.filter(isRecord) : [];
    const code = errors.length ? String(errors[0].code ?? "") : "";
    return `Not saved: ${CODE_TEXT[code] ?? "this value was refused."}`;
  }
  return "Not saved: the request failed.";
}
