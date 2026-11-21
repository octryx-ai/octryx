// Chat sidebar group pages. Pure.
//
// A refresh answers each group's first page only. Pages the user loaded with "Show more" survive it:
// rows beyond the first page are kept (newest page first, no duplicates) until the total is reached.
// `null` from the server means "list not included" (an acknowledgement); `[]` means no chats at all.
import type { ThreadGroup, ThreadSummary } from "../chatThreadTypes";

export function threadGroupKey(group: Pick<ThreadGroup, "projectId" | "projectName">) {
  return group.projectId ?? `name:${group.projectName}`;
}

function withLoaded(group: ThreadGroup, sessions: ThreadSummary[]): ThreadGroup {
  const total = group.totalThreadCount ?? sessions.length;
  return {
    ...group,
    sessions,
    loadedThreadCount: sessions.length,
    nextOffset: sessions.length,
    hasMore: sessions.length < total,
  };
}

export function mergeThreadGroupPages(
  previous: ThreadGroup[] | null | undefined,
  next: ThreadGroup[] | null | undefined,
): ThreadGroup[] {
  if (next == null) {
    return previous ?? [];
  }
  const previousByKey = new Map((previous ?? []).map((group) => [threadGroupKey(group), group]));
  return next.map((group) => {
    const before = previousByKey.get(threadGroupKey(group));
    const pageSize = group.pageSize ?? 20;
    if (!before || before.sessions.length <= Math.max(pageSize, group.sessions.length)) {
      return group;
    }
    const fresh = new Set(group.sessions.map((thread) => thread.id));
    const kept = before.sessions.filter((thread) => !fresh.has(thread.id));
    const total = group.totalThreadCount ?? group.sessions.length + kept.length;
    return withLoaded(group, [...group.sessions, ...kept].slice(0, total));
  });
}

/** Rows the user just archived or deleted leave the list at once (also loaded pages). */
export function removeThreadsFromGroups(groups: ThreadGroup[], ids: string[]): ThreadGroup[] {
  if (!ids.length) {
    return groups;
  }
  const gone = new Set(ids);
  return groups
    .map((group) => {
      const sessions = group.sessions.filter((thread) => !gone.has(thread.id));
      const removed = group.sessions.length - sessions.length;
      if (!removed) {
        return group;
      }
      const total = Math.max(0, (group.totalThreadCount ?? group.sessions.length) - removed);
      return withLoaded({ ...group, totalThreadCount: total }, sessions);
    })
    .filter((group) => (group.totalThreadCount ?? group.sessions.length) > 0);
}

/** Appends a loaded page to its group (deduplicated). */
export function appendThreadGroupPage(groups: ThreadGroup[], page: ThreadGroup): ThreadGroup[] {
  return groups.map((group) => {
    if (threadGroupKey(group) !== threadGroupKey(page)) {
      return group;
    }
    const seen = new Set(group.sessions.map((thread) => thread.id));
    const sessions = [...group.sessions, ...page.sessions.filter((thread) => !seen.has(thread.id))];
    return withLoaded({ ...group, ...page, sessions }, sessions);
  });
}
