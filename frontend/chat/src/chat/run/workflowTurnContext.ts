// Grouped by position: the turn identity exists only inside each lazily loaded summary.
// The first loaded message of a paginated turn is the lead, so context never hides behind unloaded siblings.

type TimelineItemLike = {
  kind?: unknown;
  message?: { id?: unknown; role?: unknown; turnTraceId?: unknown } | null;
};

export function repeatedTurnMessageIds(items: readonly TimelineItemLike[]): Set<string> {
  const repeated = new Set<string>();
  let leadSeen = false;
  for (const item of items) {
    if (item?.kind !== "message" || !item.message) continue;
    const { id, role, turnTraceId } = item.message;
    if (role === "user") {
      leadSeen = false;
      continue;
    }
    const traced = typeof turnTraceId === "string" && turnTraceId.trim() !== "";
    if (!traced || typeof id !== "string") continue;
    if (leadSeen) repeated.add(id);
    else leadSeen = true;
  }
  return repeated;
}
