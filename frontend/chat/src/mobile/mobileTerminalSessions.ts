// The person's open octryx-claude sessions (terminal, VS Code) and the start screen's combined list.
import type { DeviceThread } from "./mobileDeviceChats";
import { str } from "./mobilePayloadValues";

// --- the person's open octryx-claude sessions (terminal, VS Code) ----------------------------------------

export type Activity = "working" | "approval" | "waiting";

export type TerminalSession = {
  id: string;
  title: string;
  workspace: string;
  device: string;
  profile: string;
  activity: Activity;
  activityAt: string | null;
  lastText: string;
  branch: string;
  /** The model the session reported (presence row); "" when none (Claude Code does not report it yet). */
  model: string;
  /** The coding engine the launcher registered the session with (`claude_code` | `codex`), as the server sends it. */
  engine: string;
  startedAt: string | null;
  lastSeenAt: string | null;
};

const ACTIVITIES: Activity[] = ["working", "approval", "waiting"];

export function readOpenSessions(raw: unknown): TerminalSession[] {
  const items =
    raw && typeof raw === "object" ? (raw as { items?: unknown }).items : null;
  if (!Array.isArray(items)) return [];
  return items.flatMap((value) => {
    const item =
      value && typeof value === "object"
        ? (value as Record<string, unknown>)
        : {};
    const id = str(item.id);
    if (!id) return [];
    const workspace =
      item.workspace && typeof item.workspace === "object"
        ? (item.workspace as Record<string, unknown>)
        : {};
    const activity = ACTIVITIES.includes(item.activity as Activity)
      ? (item.activity as Activity)
      : "working";
    return [
      {
        id,
        title: str(item.title) ?? str(item.work_item) ?? "Terminal session",
        workspace: str(workspace.name) ?? "",
        device: str(item.device) ?? "",
        profile: str(item.profile) ?? "governed",
        activity,
        activityAt: str(item.activity_at),
        lastText: str(item.last_text) ?? "",
        branch: str(item.branch) ?? "",
        model: str(item.model) ?? "",
        engine: str(item.engine) ?? "",
        startedAt: str(item.started_at),
        lastSeenAt: str(item.last_seen_at),
      },
    ];
  });
}

export const activityLabel = (activity: Activity) =>
  activity === "approval"
    ? "Needs your approval"
    : activity === "waiting"
      ? "Waiting for you"
      : "Working";

export const activityDot = (activity: Activity) =>
  activity === "working" ? "m-dot-blue" : "m-dot-need";

export type HomeRow =
  | { kind: "session"; at: number; session: TerminalSession }
  | { kind: "thread"; at: number; thread: DeviceThread };

const at = (iso: string | null | undefined) => Date.parse(iso || "") || 0;

/** The start screen's one list: open terminal sessions and Mac chats together, the most recent activity first. */
export function homeRows(
  sessions: TerminalSession[],
  threads: DeviceThread[],
): HomeRow[] {
  return [
    ...sessions.map((session) => ({
      kind: "session" as const,
      at: at(session.activityAt || session.lastSeenAt),
      session,
    })),
    ...threads.map((thread) => ({
      kind: "thread" as const,
      at: at(thread.lastActivityAt || thread.startedAt),
      thread,
    })),
  ].sort((a, b) => b.at - a.at);
}
