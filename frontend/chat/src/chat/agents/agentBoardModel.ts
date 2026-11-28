// Bodies are written by agents or people: kept as plain strings and rendered as text only.

import { BOARD_KINDS } from "./agentBoardTypes";
import type { BoardAck, BoardClaim, BoardDecided, BoardMessage, BoardUser, BoardViewer, BoardWorkItem } from "./agentBoardTypes";
import { shortId } from "./agentBoardLabels";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const strings = (value: unknown) => (Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : []);

export function readBoardUser(value: unknown): BoardUser | null {
  if (!isRecord(value)) return null;
  const id = text(value.id);
  const name = text(value.display_name) || id;
  return name ? { id, name } : null;
}

function readWorkItem(value: unknown): BoardWorkItem | null {
  if (!isRecord(value) || !text(value.id)) return null;
  return { id: text(value.id), key: text(value.key), title: text(value.title) };
}

function readAck(value: unknown): BoardAck | null {
  if (!isRecord(value) || !isRecord(value.recipient)) return null;
  const user = readBoardUser(value.recipient.user);
  const hash = text(value.recipient.agent_hash);
  const recipient = text(value.recipient.kind) === "agent"
    ? (user ? `agent of ${user.name}` : hash ? `agent ${shortId(hash)}` : "")
    : user?.name ?? "";
  return recipient ? { recipient, ackedAt: text(value.acked_at) || null } : null;
}

function readDecided(value: unknown): BoardDecided | null {
  if (!isRecord(value)) return null;
  return { by: readBoardUser(value.by), at: text(value.at) || null, option: text(value.option), text: text(value.text) };
}

// can_admin only decides what the UI offers; the server authorizes every action.
export function readViewer(payload: unknown): BoardViewer | null {
  if (!isRecord(payload) || !isRecord(payload.viewer) || !text(payload.viewer.user_id)) return null;
  return { userId: text(payload.viewer.user_id), canAdmin: payload.viewer.can_admin === true };
}

export function readBoardMessage(value: unknown): BoardMessage | null {
  if (!isRecord(value) || !text(value.id)) return null;
  const author = isRecord(value.author) ? value.author : {};
  const to = isRecord(value.to) ? value.to : null;
  const kind = BOARD_KINDS.find((entry) => entry === text(value.kind)) ?? "unknown";
  return {
    id: text(value.id),
    kind,
    authorType: text(author.type) === "human" ? "human" : text(author.type) === "system" ? "system" : "agent",
    author: readBoardUser(author.user),
    agentHash: text(author.agent_hash),
    onBehalfOf: readBoardUser(value.on_behalf_of),
    to: to ? { user: readBoardUser(to.user), agentHash: text(to.agent_hash), role: text(to.role) } : null,
    workItem: readWorkItem(value.work_item),
    replyTo: text(value.reply_to),
    createdAt: text(value.created_at) || null,
    body: typeof value.body === "string" ? value.body : "",
    options: strings(value.options),
    redacted: Boolean(text(value.redacted_at)),
    decided: kind === "decision_request" ? readDecided(value.decided) : null,
    ackedByMe: value.acked_by_me === true,
    acks: Array.isArray(value.acks) ? value.acks.map(readAck).filter((ack): ack is BoardAck => ack !== null) : [],
  };
}

const readMessages = (value: unknown) =>
  (Array.isArray(value) ? value : []).map(readBoardMessage).filter((entry): entry is BoardMessage => entry !== null);

export function readBoardPage(payload: unknown): { items: BoardMessage[]; nextCursor: string | null } | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;
  return { items: readMessages(payload.items), nextCursor: text(payload.next_cursor) || null };
}

export function readBoardThread(payload: unknown): { root: BoardMessage; replies: BoardMessage[] } | null {
  const root = isRecord(payload) ? readBoardMessage(payload.root) : null;
  return root && isRecord(payload) ? { root, replies: readMessages(payload.replies) } : null;
}

// Polling refreshes the first page and keeps the older pages already loaded.
export function mergeNewest(fresh: BoardMessage[], existing: BoardMessage[]): BoardMessage[] {
  const seen = new Set(fresh.map((message) => message.id));
  return [...fresh, ...existing.filter((message) => !seen.has(message.id))];
}

export function readClaim(value: unknown): BoardClaim | null {
  if (!isRecord(value) || !text(value.id)) return null;
  const holder = isRecord(value.holder) ? value.holder : {};
  return {
    id: text(value.id),
    workItem: readWorkItem(value.work_item),
    holder: readBoardUser(holder.user),
    agentHash: text(holder.agent_hash),
    holderKind: text(holder.kind),
    epoch: typeof value.epoch === "number" && Number.isFinite(value.epoch) ? value.epoch : null,
    leaseUntil: text(value.lease_until) || null,
    paths: strings(value.paths),
    claimedAt: text(value.claimed_at) || null,
  };
}

export function readClaims(payload: unknown): BoardClaim[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;
  return payload.items.map(readClaim).filter((entry): entry is BoardClaim => entry !== null);
}

export function workItemHref(projectId: string, workItemId: string): string {
  const params = new URLSearchParams({ area: "work", workspace_id: projectId, work_item_id: workItemId });
  return `?${params.toString()}`;
}

const errorParts = (error: unknown) => {
  const record = isRecord(error) ? error : null;
  return {
    status: typeof record?.status === "number" ? record.status : null,
    code: typeof record?.code === "string" ? record.code : "",
    message: typeof record?.message === "string" && record.message ? record.message : "the request failed",
  };
};

// Out of scope answers like missing, so a 404 cannot say which.
export function boardLoadErrorText(error: unknown, what: string): string {
  const { status, message } = errorParts(error);
  if (status === 404) return `No ${what} shown: this server does not offer the agent board yet, or you are not a member of this Workspace.`;
  if (status === 401 || status === 403) return "Only members of this Workspace can see its agent board.";
  return `The ${what} could not be loaded: ${message}.`;
}

export function boardActionErrorText(error: unknown): string {
  const { status, code, message } = errorParts(error);
  if (code === "already_decided") return "This request has already been decided.";
  if (code === "takeover_not_pending") return "This takeover is no longer waiting: it was decided, it expired, or it was cancelled because the claim changed.";
  if (code === "requester_not_member") return "The requesting agent's user is no longer a member of this Workspace, so the takeover cannot be confirmed.";
  if (code === "interactive_session_required") return "Takeovers are confirmed or declined only in a signed-in Octryx session, never with an API key or an agent's login.";
  if (code === "not_claimed") return "Nothing to take over: the item is no longer claimed.";
  if (code === "already_holder") return "The receiving agent already holds this item.";
  if (code === "claim_released") return "This claim was released in the meantime; there is nothing to hand over.";
  if (code === "secret_detected") return "The text looks like it contains a secret, so nothing was posted. Remove it and try again.";
  if (status === 401 || status === 403) return "The server did not allow this for you. Nothing was changed.";
  if (status === 404) return "This entry no longer exists or is not in this Workspace.";
  return `The action failed: ${message}.`;
}

export const BOARD_POLL_MS = 10_000;
export const BOARD_PAGE_SIZE = 50;
