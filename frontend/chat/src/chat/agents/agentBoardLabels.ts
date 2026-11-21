// Agent board wording and permissions: kind labels and tones, author and addressee lines, decisions and leases.
import { serverTimeOf } from "../../admin/utils/serverTime";
import type { BoardDecided, BoardKind, BoardMessage, BoardViewer } from "./agentBoardTypes";

/** A long id (agent key hash, commit, checksum) shortened for display: the first 10 characters and an ellipsis. */
export function shortId(value: string): string {
  return value.length > 14 ? `${value.slice(0, 10)}…` : value;
}

export const KIND_LABEL: Record<BoardKind, string> = {
  question: "question",
  answer: "answer",
  info: "info",
  conflict: "conflict",
  handoff_request: "handoff request",
  handoff_accept: "handoff accepted",
  decision_request: "decision request",
  decision: "decision",
  unknown: "other",
};

export const KIND_TONE: Record<BoardKind, "active" | "neutral" | "attention" | "danger"> = {
  question: "neutral",
  answer: "active",
  info: "neutral",
  conflict: "danger",
  handoff_request: "attention",
  handoff_accept: "active",
  decision_request: "attention",
  decision: "active",
  unknown: "neutral",
};

/** "Agent of Anna" (on behalf of someone else when that differs) or "Anna (person)"; humans are always marked. */
export function authorLabel(message: BoardMessage): string {
  const name = message.author?.name || "an unknown user";
  if (message.authorType === "human") return `${name} (person)`;
  if (message.authorType === "system") return message.author ? `Octryx (automatic), for the claim of ${name}` : "Octryx (automatic)";
  const behalf = message.onBehalfOf && message.onBehalfOf.id !== message.author?.id ? `, on behalf of ${message.onBehalfOf.name}` : "";
  return `Agent of ${name}${behalf}`;
}

/**
 * The agent an automatic handoff request offers the item to (judge-s4 F1: offered, never assigned), or "". The offer
 * is the request's agent addressee; the item changes hands only if that agent requests the takeover.
 */
export function offeredToLabel(message: BoardMessage): string {
  if (message.kind !== "handoff_request" || message.authorType !== "system" || !message.to?.agentHash) return "";
  return message.to.user ? `agent of ${message.to.user.name}` : `agent ${shortId(message.to.agentHash)}`;
}

/** The addressee in words, or "" for a message to the whole Workspace. An automatic request's offer is apart. */
export function addresseeLabel(message: BoardMessage): string {
  const to = message.to;
  if (!to) return "";
  if (offeredToLabel(message)) return to.role === "admins" ? "Workspace admins" : "";
  if (to.user && to.agentHash) return `agent of ${to.user.name}`;
  if (to.user) return to.user.name;
  if (to.agentHash) return `agent ${shortId(to.agentHash)}`;
  if (to.role === "admins") return "Workspace admins";
  return "";
}

/** "Decided by Alex: merge — after CI". */
export function decidedLabel(decided: BoardDecided): string {
  const answer = [decided.option, decided.text].filter(Boolean).join(" — ");
  return `Decided by ${decided.by?.name || "an unknown user"}${answer ? `: ${answer}` : ""}`;
}

/**
 * Whether to offer the decision controls on an undecided, unredacted request (D-F2 `decided` is null). It mirrors the
 * server's `may_decide` (judge-board L7): the addressed user or a platform admin always; a Workspace admin
 * (`viewer.can_admin`, D-F1) when the request is addressed to admins or to no one; nobody else, so a request to an
 * agent is for platform admins only. The server decides for real; a refusal is shown, never hidden.
 */
export function mayDecide(message: BoardMessage, viewer: BoardViewer | null, isPlatformAdmin = false): boolean {
  if (message.kind !== "decision_request" || message.redacted || message.decided || !viewer) return false;
  const to = message.to;
  if (to?.user?.id === viewer.userId || isPlatformAdmin) return true;
  const unaddressed = !to || (!to.user && !to.agentHash && !to.role);
  return (to?.role === "admins" || unaddressed) && viewer.canAdmin;
}

/** "lease ends in 4 min 12 s" / "lease expired"; whole seconds, no estimate when the server sent no time. */
export function leaseText(leaseUntil: string | null, now = Date.now()): string {
  const until = serverTimeOf(leaseUntil);
  if (until === null) return "lease end not reported";
  const seconds = Math.floor((until - now) / 1000);
  if (seconds <= 0) return "lease expired";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `lease ends in ${hours} h ${minutes} min`;
  return minutes ? `lease ends in ${minutes} min ${seconds % 60} s` : `lease ends in ${seconds} s`;
}
