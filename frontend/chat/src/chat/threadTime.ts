// Last-activity time of a chat row and its time section (WP chat sidebar).
// Sections: Today / Yesterday / Previous 7 days / Earlier, by local calendar day.

export const THREAD_TIME_SECTIONS = ["Today", "Yesterday", "Previous 7 days", "Earlier"] as const;

export type ThreadTimeSection = (typeof THREAD_TIME_SECTIONS)[number];

const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(date: Date) {
  const start = new Date(date);
  start.setHours(0, 0, 0, 0);
  return start.getTime();
}

function parse(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }
  // Server timestamps are UTC; a value without a zone is read as UTC, not local time.
  const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function threadTimeSection(value: string | null | undefined, now: Date = new Date()): ThreadTimeSection {
  const date = parse(value);
  if (!date) {
    return "Earlier";
  }
  const today = startOfDay(now);
  const at = date.getTime();
  if (at >= today) {
    return "Today";
  }
  if (at >= today - DAY_MS) {
    return "Yesterday";
  }
  if (at >= today - 7 * DAY_MS) {
    return "Previous 7 days";
  }
  return "Earlier";
}

/** `15:28`, `Yesterday`, `Tue`, `30 Sept` — the short form next to the title. */
export function threadTimeLabel(value: string | null | undefined, now: Date = new Date()): string {
  const date = parse(value);
  if (!date) {
    return "";
  }
  const section = threadTimeSection(value, now);
  if (section === "Today") {
    return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }
  if (section === "Yesterday") {
    return "Yesterday";
  }
  if (section === "Previous 7 days") {
    return date.toLocaleDateString("en-GB", { weekday: "short" });
  }
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export type ThreadSection<T> = { label: "Pinned" | ThreadTimeSection; threads: T[] };

/** Pinned first, then Today / Yesterday / Previous 7 days / Earlier by last activity; empty sections are left out. */
export function sectionThreads<T extends { isPinned?: boolean; lastActivityAt?: string | null; startedAt?: string | null }>(
  threads: T[],
  now: Date = new Date(),
): ThreadSection<T>[] {
  const pinned = threads.filter((thread) => thread.isPinned);
  const buckets = new Map<ThreadTimeSection, T[]>(THREAD_TIME_SECTIONS.map((label) => [label, []]));
  for (const thread of threads) {
    if (!thread.isPinned) {
      buckets.get(threadTimeSection(thread.lastActivityAt ?? thread.startedAt, now))?.push(thread);
    }
  }
  const sections: ThreadSection<T>[] = pinned.length ? [{ label: "Pinned", threads: pinned }] : [];
  for (const label of THREAD_TIME_SECTIONS) {
    const bucket = buckets.get(label) ?? [];
    if (bucket.length) {
      sections.push({ label, threads: bucket });
    }
  }
  return sections;
}
