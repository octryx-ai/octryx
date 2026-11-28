// The Workspace session pool (GET /api/v1/session-handovers/pool): sessions someone handed into the pool, with what
// a taker's runtime needs. A member sees the entry, never the transcript, until they take it.
import { record, str } from "./companionValues";

export type PoolEntry = {
  id: string;
  sessionId: string;
  runId: string | null;
  title: string;
  engine: string;
  seat: boolean;
  state: string;
  summary: string;
  canRunNow: boolean;
  createdAt: string | null;
};

export const POOL_PATH = "/api/v1/session-handovers/pool";
export const takePath = (id: string) => `/api/v1/session-handovers/${encodeURIComponent(id)}/accept`;
export const POOL_EMPTY = "No session waits in the pool.";
export const POOL_TAKEN = "You took the session over: it is yours now.";

export function readPool(payload: unknown): PoolEntry[] {
  const entries = record(payload)?.entries;
  return (Array.isArray(entries) ? entries : []).map((value): PoolEntry | null => {
    const entry = record(value);
    if (!entry || !str(entry.id) || !str(entry.session_id)) return null;
    const needs = record(entry.needs) ?? {};
    return {
      id: str(entry.id), sessionId: str(entry.session_id), runId: str(entry.run_id) || null,
      title: str(entry.title) || "Session", engine: str(needs.engine), seat: str(needs.profile) === "seat",
      state: str(entry.state), summary: str(entry.summary), canRunNow: entry.can_run_now === true,
      createdAt: str(entry.created_at) || null,
    };
  }).filter((entry): entry is PoolEntry => entry !== null);
}

export const engineName = (engine: string) =>
  engine.split("_").filter(Boolean).map((word) => word[0].toUpperCase() + word.slice(1)).join(" ") || "Agent";

/** What the taker needs: a seat only lives on a person's device; the platform's models also run on a server runner. */
export const needsText = (entry: PoolEntry) =>
  entry.seat ? `${engineName(entry.engine)} on your own seat` : `${engineName(entry.engine)} on the platform's models`;

export const runNowText = (entry: PoolEntry) =>
  entry.canRunNow ? "You can run it now"
    : entry.seat ? `Needs a device of yours with a ${engineName(entry.engine)} seat online` : "Needs a device of yours online";
