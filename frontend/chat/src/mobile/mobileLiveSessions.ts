// Live Claude Code sessions on the person's Macs and the delivery state of their messages.
import { engineLabel } from "../chat/engines/engineModel";
import { folderName } from "./mobileDeviceChats";
import { liveText } from "./mobilePayloadValues";

// Live: Claude Code sessions running on the person's Macs right now, reached through their inbox
// socket; the Mac relays each message and reports whether it arrived exactly as written.
export type LiveMessage = {
  id: string;
  direction: "out" | "in";
  name: string;
  text: string;
  state: string;
  reason: string;
  createdAt: string;
  // How many pictures the person attached; the pictures themselves live only on the Mac.
  attachments: number;
};

export type LiveSession = {
  deviceId: string;
  deviceName: string;
  fresh: boolean;
  peer: string;
  name: string;
  profile: string;
  cwd: string;
  folderName: string;
  status: string;
  /** The coding engine the session runs on (claude_code | codex), as the server names it (`devices/live_values`). */
  engine: string;
  last: LiveMessage | null;
};

export function readLiveMessage(raw: unknown): LiveMessage | null {
  const item = (raw ?? null) as Record<string, unknown> | null;
  if (!item || typeof item.id !== "string" || typeof item.text !== "string")
    return null;
  return {
    id: item.id,
    direction: item.direction === "in" ? "in" : "out",
    name: liveText(item.name),
    text: item.text,
    state: liveText(item.state),
    reason: liveText(item.reason),
    createdAt: liveText(item.created_at),
    attachments: typeof item.attachments === "number" ? item.attachments : 0,
  };
}

export function readLiveSessions(raw: unknown): LiveSession[] {
  const items = (raw as { items?: unknown } | null)?.items;
  if (!Array.isArray(items)) return [];
  const out: LiveSession[] = [];
  for (const entry of items) {
    const device = (entry ?? {}) as Record<string, unknown>;
    if (typeof device.device_id !== "string") continue;
    const sessions = Array.isArray(device.sessions) ? device.sessions : [];
    for (const raw of sessions) {
      const session = (raw ?? {}) as Record<string, unknown>;
      const peer = liveText(session.peer);
      if (!peer.startsWith("uds:")) continue;
      const cwd = liveText(session.cwd);
      const folderName = cwd.split("/").filter(Boolean).pop() ?? "";
      const engine = liveText(session.engine);
      out.push({
        deviceId: device.device_id,
        deviceName: liveText(device.device_name),
        fresh: device.fresh === true,
        peer,
        name: liveText(session.name) || folderName || engineLabel(engine),
        profile: liveText(session.profile),
        cwd,
        folderName,
        status: liveText(session.status),
        engine,
        last: readLiveMessage(session.last_message),
      });
    }
  }
  return out;
}

export function readLiveMessages(raw: unknown): {
  running: boolean;
  items: LiveMessage[];
} {
  const data = (raw ?? {}) as Record<string, unknown>;
  const items = Array.isArray(data.items) ? data.items : [];
  return {
    running: data.running === true,
    items: items
      .map(readLiveMessage)
      .filter((item): item is LiveMessage => item !== null),
  };
}

const LIVE_REASONS: Record<string, string> = {
  live_off: "Live is off on your Mac",
  session_gone: "The session has ended",
  relay_failed: "Your Mac could not relay it",
  relay_changed_text: "Not delivered as written",
  no_answer: "Your Mac did not answer",
  invalid: "Not a valid message",
  attachment_missing: "The picture did not arrive whole",
};

/** The line under one of the person's messages: on its way, arrived, or why not. */
export function liveDeliveryLabel(message: LiveMessage): string {
  if (message.direction !== "out") return "";
  if (message.state === "delivered") return "Delivered";
  if (message.state === "pending" || message.state === "sent")
    return "Sending…";
  return LIVE_REASONS[message.reason] ?? "Not delivered";
}
