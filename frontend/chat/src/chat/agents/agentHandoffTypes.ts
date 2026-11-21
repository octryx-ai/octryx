// Handoff and takeover types of the "Agents" area, shared by the payload readers and the view helpers.
import type { BoardUser, BoardWorkItem } from "./agentBoardTypes";

export type HandoffSections = {
  goal: string;
  acceptance: string;
  rules: string;
  // Freeze 3c: the work state that travels (base and WIP commit, and a bundle when the branch could not be pushed).
  repo: { url: string; branch: string; worktree: string; baseCommit: string; wipCommit: string; bundleId: string } | null;
  commands: { build: string; test: string; deploy: string; other: string[] } | null;
  state: string;
  lastCommits: string[];
  nextSteps: string[];
  openDecisions: string[];
  pitfalls: string[];
  notes: string;
  linkedSessions: string[];
  changedFiles: string[];
  excludedFiles: string[];
};

export type Handoff = {
  id: string;
  workItem: BoardWorkItem | null;
  version: number | null;
  authorType: string;
  author: BoardUser | null;
  agentHash: string;
  createdAt: string | null;
  sections: HandoffSections;
};

export type TakeoverStatus = "pending" | "confirmed" | "declined" | "expired" | "cancelled" | "unknown";

export type Takeover = {
  id: string;
  workItem: BoardWorkItem | null;
  from: { user: BoardUser | null; agentHash: string };
  to: { user: BoardUser | null; agentHash: string };
  status: TakeoverStatus;
  reason: string;
  expiresAt: string | null;
  createdAt: string | null;
  decidedAt: string | null;
  decidedBy: { kind: "human" | "system"; user: BoardUser | null } | null;
  policyMode: string;
  policySnapshot: PolicySnapshot | null;
  // Freeze 3c: the allowance percentage that triggered a launcher's own handoff, when the answer names it
  // (`trigger_pct`, proposed to 37f7). Never derived from the reason text.
  triggerPct: number | null;
  handoff: { id: string; version: number | null } | null;
  automatic: boolean;
};

export type PolicySnapshot = {
  mode: string;
  autoThresholdPct: number | null;
  requireSparePct: number | null;
  allowedRequesters: string;
  conditions: Array<{ key: string; met: boolean }>;
};
