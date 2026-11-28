import { serverTimeOf } from "../../admin/utils/serverTime";
import type { BoardDecided, BoardKind, BoardMessage, BoardViewer } from "./agentBoardTypes";

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

export function authorLabel(message: BoardMessage): string {
  const name = message.author?.name || "an unknown user";
  if (message.authorType === "human") return `${name} (person)`;
  if (message.authorType === "system") return message.author ? `Octryx (automatic), for the claim of ${name}` : "Octryx (automatic)";
  const behalf = message.onBehalfOf && message.onBehalfOf.id !== message.author?.id ? `, on behalf of ${message.onBehalfOf.name}` : "";
  return `Agent of ${name}${behalf}`;
}

// Offered, never assigned: the item changes hands only if that agent requests the takeover.
export function offeredToLabel(message: BoardMessage): string {
  if (message.kind !== "handoff_request" || message.authorType !== "system" || !message.to?.agentHash) return "";
  return message.to.user ? `agent of ${message.to.user.name}` : `agent ${shortId(message.to.agentHash)}`;
}

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

export function decidedLabel(decided: BoardDecided): string {
  const answer = [decided.option, decided.text].filter(Boolean).join(" — ");
  return `Decided by ${decided.by?.name || "an unknown user"}${answer ? `: ${answer}` : ""}`;
}

// Mirrors the server's may_decide; the server decides for real and a refusal is shown.
export function mayDecide(message: BoardMessage, viewer: BoardViewer | null, isPlatformAdmin = false): boolean {
  if (message.kind !== "decision_request" || message.redacted || message.decided || !viewer) return false;
  const to = message.to;
  if (to?.user?.id === viewer.userId || isPlatformAdmin) return true;
  const unaddressed = !to || (!to.user && !to.agentHash && !to.role);
  return (to?.role === "admins" || unaddressed) && viewer.canAdmin;
}

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
