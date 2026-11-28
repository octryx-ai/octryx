// Read from the timeline's structure only, never from the message text.

type TimelineMessage = {
  id?: unknown;
  role?: unknown;
  toolEvents?: readonly unknown[] | null;
};
type TimelineItemLike = { kind?: unknown; message?: TimelineMessage | null };

const roleOf = (message: TimelineMessage) =>
  String(message.role ?? "")
    .trim()
    .toLowerCase();

export function intermediateToolMessageIds(
  items: readonly TimelineItemLike[],
): Set<string> {
  const intermediate = new Set<string>();
  let previousAssistant: TimelineMessage | null = null;
  for (const item of items) {
    if (item?.kind !== "message" || !item.message) continue;
    const role = roleOf(item.message);
    if (role === "user") {
      previousAssistant = null;
      continue;
    }
    if (role !== "assistant") continue;
    if (
      previousAssistant &&
      typeof previousAssistant.id === "string" &&
      (previousAssistant.toolEvents?.length ?? 0) > 0
    )
      intermediate.add(previousAssistant.id);
    previousAssistant = item.message;
  }
  return intermediate;
}
