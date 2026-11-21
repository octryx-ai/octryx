// The audit rows of the Workspace seat settings (`admin.agent_gateway.seat_mode_updated`, Data classification card).
// One row per saved key: details `{<key>: after, before: {<key>: …}, after: {<key>: …}}` (backend
// `agent_gateway/seat_settings.py`); a value that was not set reads "not set".

export const SEAT_AUDIT_ACTION = "admin.agent_gateway.seat_mode_updated";

const SEAT_SETTING_NAMES: Record<string, string> = {
  seat_mode: "Claude seat",
  codex_seat_mode: "Codex seat",
  requires_governed_routing: "Only company models",
  seat_models: "Claude seat models",
  seat_allows_governed_models: "Company models in seat sessions",
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function valueText(value: unknown): string {
  if (value === "allowed") return "Allowed";
  if (value === "forbidden") return "Forbidden";
  if (value === true) return "On";
  if (value === false) return "Off";
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : "none";
  if (value === undefined || value === null) return "not set";
  return String(value);
}

type SeatChange = { key: string; name: string; before: unknown; after: unknown };

/** The seat key a row is about (the first known key of its `after`) with both values, or null. */
function seatChange(details: Record<string, unknown>): SeatChange | null {
  if (!isRecord(details.after) || !isRecord(details.before)) return null;
  const after = details.after;
  const key = Object.keys(SEAT_SETTING_NAMES).find((name) => name in after);
  return key ? { key, name: SEAT_SETTING_NAMES[key], before: details.before[key], after: after[key] } : null;
}

/** "Codex seat: Forbidden → Allowed"; a model list names what was added and removed. Null when the details name no
 * seat key. */
export function seatAuditSummary(details: Record<string, unknown> | null | undefined): string | null {
  if (!isRecord(details)) return null;
  const change = seatChange(details);
  if (!change) return null;
  const { name, before, after } = change;
  if (Array.isArray(before) && Array.isArray(after)) {
    const added = after.filter((item) => !before.includes(item));
    const removed = before.filter((item) => !after.includes(item));
    const parts = [added.length ? `added ${valueText(added)}` : "", removed.length ? `removed ${valueText(removed)}` : ""].filter(Boolean);
    return `${name}: ${parts.length ? parts.join("; ") : "order changed"}`;
  }
  return `${name}: ${valueText(before)} → ${valueText(after)}`;
}

/** The diff lines of a seat row, with the setting's name and value words instead of the stored key and value. */
export function seatAuditDiffLines(details: Record<string, unknown>): Array<{ kind: "del" | "add" | "same"; text: string }> | null {
  const change = seatChange(details);
  if (!change) return null;
  const { name, before, after } = change;
  if (JSON.stringify(before) === JSON.stringify(after)) return [{ kind: "same", text: `  ${name}: ${valueText(after)} (unchanged)` }];
  return [{ kind: "del", text: `- ${name}: ${valueText(before)}` }, { kind: "add", text: `+ ${name}: ${valueText(after)}` }];
}
