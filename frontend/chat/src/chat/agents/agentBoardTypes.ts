// Kinds and types of the agent message board and claims: users, viewer, messages, acks, decisions and claims.
export const BOARD_KINDS = [
  "question", "answer", "info", "conflict", "handoff_request", "handoff_accept", "decision_request", "decision",
] as const;
export type BoardKind = (typeof BOARD_KINDS)[number] | "unknown";

export type BoardUser = { id: string; name: string };
export type BoardViewer = { userId: string; canAdmin: boolean };
export type BoardDecided = { by: BoardUser | null; at: string | null; option: string; text: string };
export type BoardAck = { recipient: string; ackedAt: string | null };
export type BoardWorkItem = { id: string; key: string; title: string };

export type BoardMessage = {
  id: string;
  kind: BoardKind;
  // "system": an automatic handoff request posted by Octryx for a claim holder; author.user is the holder.
  authorType: "agent" | "human" | "system";
  author: BoardUser | null;
  agentHash: string;
  onBehalfOf: BoardUser | null;
  to: { user: BoardUser | null; agentHash: string; role: string } | null;
  workItem: BoardWorkItem | null;
  replyTo: string;
  createdAt: string | null;
  body: string;
  options: string[];
  redacted: boolean;
  decided: BoardDecided | null;
  ackedByMe: boolean;
  acks: BoardAck[];
};

export type BoardClaim = {
  id: string;
  workItem: BoardWorkItem | null;
  holder: BoardUser | null;
  agentHash: string;
  holderKind: string;
  epoch: number | null;
  leaseUntil: string | null;
  paths: string[];
  claimedAt: string | null;
};
