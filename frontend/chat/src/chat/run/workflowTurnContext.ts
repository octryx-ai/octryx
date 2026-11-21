// Which assistant messages repeat their user turn's workflow context.
//
// A user turn (the messages after a user message, up to the next one) can produce several
// assistant messages — tool progress and the final answer — and each one carries its own trace and
// loads its own execution summary, which repeats the same applied workflow. The stable turn
// identity (`turn.user_message_id`) only exists inside each lazily loaded summary, so the feed
// groups conservatively by position: the first traced assistant message of a user turn is its
// lead and shows the context; every later traced assistant message of that turn is a "repeat".
// A new user message starts a new turn, so its context shows again even when the workflow is
// unchanged. Messages without a trace load no summary, so they are neither lead nor repeat. The
// first loaded message of a paginated turn is the lead, so context is never hidden because its
// earlier siblings are not loaded yet. Pending decisions are not affected: callers only suppress
// an already applied note.

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
