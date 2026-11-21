// Observability → Audit log: who changed what (administrative changes only).

import { SEAT_TRAFFIC_AUDIT_ACTION } from "../seatTraffic/seatTrafficModel";
import { SEAT_EVENT_AUDIT_LABELS } from "../../../chat/workflowRun/seatEventsModel";
import { SEAT_AUDIT_ACTION, seatAuditDiffLines, seatAuditSummary } from "./seatAuditModel";

export type AuditItem = {
  id: string;
  time: string | null;
  actor: string;
  change: string;
  object: string | null;
  category: string;
  ip_address: string | null;
  details: Record<string, unknown>;
};
export type AuditPage = { window_days: number; categories: string[]; page: number; page_size: number; total: number; items: AuditItem[] };

export function auditQuery(params: { category: string; query: string; page: number; windowDays: number }): string {
  const search = new URLSearchParams({ window_days: String(params.windowDays), page: String(params.page) });
  if (params.category) search.set("category", params.category);
  if (params.query.trim()) search.set("q", params.query.trim());
  return search.toString();
}

/** Diff lines from ``details.before`` / ``details.after`` (changed keys only); otherwise the details as lines. A seat
 * setting row (``change``) reads with the setting's name and value words. */
export function auditDiffLines(details: Record<string, unknown>, change?: string): Array<{ kind: "del" | "add" | "same"; text: string }> {
  const seat = change === SEAT_AUDIT_ACTION ? seatAuditDiffLines(details) : null;
  if (seat) return seat;
  const before = details.before;
  const after = details.after;
  const show = (value: unknown) => (typeof value === "string" ? value : JSON.stringify(value));
  if (before && after && typeof before === "object" && typeof after === "object") {
    const lines: Array<{ kind: "del" | "add" | "same"; text: string }> = [];
    const keys = new Set([...Object.keys(before as object), ...Object.keys(after as object)]);
    for (const key of [...keys].sort()) {
      const left = (before as Record<string, unknown>)[key];
      const right = (after as Record<string, unknown>)[key];
      if (JSON.stringify(left) === JSON.stringify(right)) continue;
      if (left !== undefined) lines.push({ kind: "del", text: `- ${key}: ${show(left)}` });
      if (right !== undefined) lines.push({ kind: "add", text: `+ ${key}: ${show(right)}` });
    }
    return lines.length ? lines : [{ kind: "same", text: "  no field changed" }];
  }
  return Object.entries(details).map(([key, value]) => ({ kind: "same", text: `  ${key}: ${show(value)}` }));
}

const sentence = (text: string) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : text);

// Events whose generic reading would be unclear ("Agent engine updated"): their own words.
const KNOWN_CHANGES: Record<string, string> = {
  "admin.agent_gateway.default_engine_updated": "Platform coding engine changed",
  "admin.agent_gateway.engines_updated": "Workspace coding engines changed",
  "user.agent_engine_updated": "Personal coding engine changed",
  "admin.local_models.permissive_only_updated": "Local model licence switch changed",
  [SEAT_AUDIT_ACTION]: "Seat setting changed",
  [SEAT_TRAFFIC_AUDIT_ACTION]: "Seat traffic changed",
  ...SEAT_EVENT_AUDIT_LABELS,
};

/**
 * The change in words: a recorded event name (`policy_engine.policy_set_draft_saved`, `admin.project_config.updated`)
 * becomes "Policy set draft saved" / "Project config updated"; the module prefix is dropped when the rest still says
 * what happened. A request line (`POST /api/…`) and free text stay as they are.
 * ``details``: the row's details, read only for the events that summarize them (the seat settings).
 */
export function auditChangeLabel(change: string, details?: Record<string, unknown> | null): string {
  const text = (change ?? "").trim();
  // A seat setting names which setting changed and its old and new value ("Codex seat: Forbidden → Allowed").
  if (text === SEAT_AUDIT_ACTION) return seatAuditSummary(details) ?? KNOWN_CHANGES[text];
  if (KNOWN_CHANGES[text]) return KNOWN_CHANGES[text];
  if (!/^[a-z0-9_]+(\.[a-z0-9_]+)*$/.test(text) || !/[._]/.test(text)) return text;
  const parts = text.split(".");
  const rest = parts.slice(1);
  const words = (rest.length > 1 || rest[0]?.includes("_") ? rest : parts).join(" ").replace(/_/g, " ");
  return sentence(words.replace(/\s+/g, " ").trim());
}

/** The object as a readable kind and a short id: `policy_set_version · b5df4d67-…` → kind "Policy set version", id "b5df4d67". */
export function auditObjectParts(object: string | null): { kind: string; id: string | null; full: string } | null {
  if (!object) return null;
  const [head, ...tail] = object.split(" · ");
  const id = tail.join(" · ").trim();
  const kind = /^[a-z0-9_]+$/.test(head.trim()) ? sentence(head.trim().replace(/_/g, " ")) : head.trim();
  const shortId = /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(id) ? id.slice(0, 8) : id || null;
  return { kind: kind === "Api" ? "API" : kind, id: shortId, full: object };
}
