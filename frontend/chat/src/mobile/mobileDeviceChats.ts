// Chats on the person's Macs and on the Server, local Claude Code sessions, claim links, billing choices and job event merging.
import type { ThreadGroup, ThreadSummary } from "../chatThreadTypes";
import type { MyDevice } from "../chat/devices/devicesModel";
import type { DeviceRunsPolicy } from "../chat/devices/deviceRunsPolicyModel";
import { ROUTE_GOVERNED, ROUTE_SEAT } from "./engineSeatModel";

export type Billing = "governed" | "seat";

export const billingLabel = (profile: string) =>
  profile.startsWith("local:")
    ? `Claude Code · ${profile.slice("local:".length)}`
    : profile === "seat"
      ? ROUTE_SEAT
      : ROUTE_GOVERNED;

/** A Claude Code session outside octryx on one of the person's Macs, as the Mac reports it. */
export type LocalSession = {
  id: string;
  profile: string;
  title: string;
  folder: string;
  folderName: string;
  lastText: string;
  updatedAt: string;
  threadId: string;
  deviceName: string;
  online: boolean;
  // The Mac's own opt-in for remote runs in this profile (`octryx-claude profiles connect … --allow-takeover`).
  takeoverAllowed: boolean;
  // Phone-made forks of this session (phase B): their threads continue the copy, not the original.
  forkThreadIds: string[];
};

export function readLocalSessions(raw: unknown): LocalSession[] {
  const items = (raw as { items?: unknown } | null)?.items;
  if (!Array.isArray(items)) return [];
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  return items
    .map((item) => item as Record<string, unknown>)
    .filter((item) => typeof item.id === "string" && item.id)
    .map((item) => {
      const device = (item.device ?? {}) as Record<string, unknown>;
      return {
        id: String(item.id),
        profile: text(item.profile),
        title: text(item.title) || text(item.folder_name) || "Claude Code",
        folder: text(item.folder),
        folderName: text(item.folder_name),
        lastText: text(item.last_text),
        updatedAt: text(item.updated_at),
        threadId: text(item.thread_id),
        forkThreadIds: Array.isArray(item.fork_thread_ids) ? item.fork_thread_ids.map(String) : [],
        deviceName: text(device.name),
        online: device.online === true,
        takeoverAllowed: item.takeover_allowed === true,
      };
    });
}

/** `#claim=K7Q4-XM9P&chat=…` → `{claim: "K7Q4-XM9P", chat: "…"}`. */
export function parseHash(hash: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of hash.replace(/^#/, "").split("&")) {
    const [key, ...rest] = part.split("=");
    if (!key) continue;
    try {
      out[key] = decodeURIComponent(rest.join("="));
    } catch {
      out[key] = "";
    }
  }
  return out;
}

/** `k7q4xm9p` → `K7Q4-XM9P` while typing; at most eight characters. */
export function formatClaimInput(text: string): string {
  const raw = text
    .toUpperCase()
    .replace(/[^0-9A-Z]/g, "")
    .slice(0, 8);
  return raw.length > 4 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
}

export type DeviceThread = ThreadSummary & { projectId: string };

/** The chats that run on the person's Macs, newest first. */
export function deviceThreads(
  groups: ThreadGroup[] | null | undefined,
): DeviceThread[] {
  const out: DeviceThread[] = [];
  for (const group of groups ?? []) {
    for (const thread of group.sessions ?? []) {
      if (thread.executionTarget?.kind === "device")
        out.push({ ...thread, projectId: group.projectId ?? "" });
    }
  }
  const at = (thread: ThreadSummary) =>
    Date.parse(thread.lastActivityAt || thread.startedAt || "") || 0;
  return out.sort((a, b) => at(b) - at(a));
}

export const folderName = (path: string) =>
  path.replace(/\/+$/, "").split("/").pop() || path;

/** The billing choices a new chat offers: what the Mac has set up and the Workspace allows. */
export function billingOptions(
  device: MyDevice | null,
  policy: DeviceRunsPolicy | null,
): Billing[] {
  if (!device || !policy || !policy.enabled || !policy.platformEnabled)
    return [];
  const allowed = new Set(policy.allowedProfiles);
  const options: Billing[] = [];
  if (device.profiles.includes("governed") && allowed.has("governed"))
    options.push("governed");
  if (
    device.profiles.includes("seat") &&
    allowed.has("seat") &&
    policy.seatAllowed &&
    device.seatLogin
  ) {
    options.push("seat");
  }
  return options;
}

/** Every open chat, on a Mac or on the Server, newest first; ``onServer`` when it has no device target. */
export function chatThreads(
  groups: ThreadGroup[] | null | undefined,
): (DeviceThread & { onServer: boolean })[] {
  const out: (DeviceThread & { onServer: boolean })[] = [];
  for (const group of groups ?? []) {
    for (const thread of group.sessions ?? []) {
      out.push({
        ...thread,
        projectId: group.projectId ?? "",
        onServer: thread.executionTarget?.kind !== "device",
      });
    }
  }
  const at = (thread: ThreadSummary) =>
    Date.parse(thread.lastActivityAt || thread.startedAt || "") || 0;
  return out.sort((a, b) => at(b) - at(a));
}

/** Whether a Server chat still works on its answer: the last message is the person's, and recent. */
export function serverAnswerPending(
  messages: { role: string; createdAt?: string }[],
  now = Date.now(),
): boolean {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "user") return false;
  const at = Date.parse(last.createdAt ?? "");
  return Number.isNaN(at) || now - at < 15 * 60 * 1000;
}

/** How the phone writes to a thread that continues a Claude Code session from the Mac: the take-over of that session,
 * and, for a fork, the fork's own thread. ``null``: an ordinary chat. */
export function takeOverTarget(
  sessions: LocalSession[],
  threadId: string,
): { localSessionId: string; forkThreadId?: string } | null {
  const own = sessions.find((session) => session.threadId === threadId);
  if (own) return { localSessionId: own.id };
  const forked = sessions.find((session) => session.forkThreadIds.includes(threadId));
  return forked ? { localSessionId: forked.id, forkThreadId: threadId } : null;
}

export const isFork = (title: string) => title.startsWith("Fork of ");

// A Mac chat asks only for the events it does not have yet; the jobs it already knows
// answer ``partial`` and their new events are added to the ones on the phone.
type KnownJob = { id: string; events: { seq: number }[] };

/** "job:seq,…" of what the phone already has (a job without events is asked for in full). */
export function knownSeqs(jobs: KnownJob[]): string {
  return jobs
    .filter((job) => job.events.length > 0)
    .map((job) => `${job.id}:${job.events[job.events.length - 1].seq}`)
    .join(",");
}

/** The ids of the jobs the platform answered only partly. */
export function partialJobIds(raw: unknown): Set<string> {
  const items = (raw as { items?: unknown } | null)?.items;
  return new Set(
    (Array.isArray(items) ? items : [])
      .map((item) => (item ?? {}) as Record<string, unknown>)
      .filter((item) => item.partial === true && typeof item.id === "string")
      .map((item) => String(item.id)),
  );
}

/** The fresh list (jobs, their state and approvals as the platform says now) with the phone's events kept for the
 * jobs that came partly; each seq once, in order. A job the platform no longer lists is dropped. */
export function mergeJobs<T extends KnownJob & { events: { seq: number }[] }>(
  previous: T[],
  fresh: T[],
  partial: Set<string>,
): T[] {
  return fresh.map((job) => {
    if (!partial.has(job.id)) return job;
    const before = previous.find((item) => item.id === job.id);
    if (!before) return job;
    const bySeq = new Map(before.events.map((event) => [event.seq, event]));
    for (const event of job.events) bySeq.set(event.seq, event);
    return { ...job, events: [...bySeq.values()].sort((a, b) => a.seq - b.seq) };
  });
}
