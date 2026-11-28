import { serverTimeOf } from "../../admin/utils/serverTime";
import { shortId } from "./agentBoardLabels";
import type { BoardUser, BoardViewer } from "./agentBoardTypes";
import type { Handoff, HandoffSections, Takeover, TakeoverStatus } from "./agentHandoffTypes";

const CONDITION_LABEL: Record<string, string> = {
  holder_needs_handoff: "holder at its limit, threshold, stopped or silent",
  requester_has_spare: "requester had spare allowance",
  requester_allowed: "requester allowed by the policy",
  handoff_exists: "a handoff existed",
};

export function decisionLabel(takeover: Takeover): string {
  if (takeover.status === "cancelled") return "Cancelled: the claim changed before a decision";
  if (!takeover.decidedBy) return "";
  if (takeover.decidedBy.kind === "system") {
    return takeover.triggerPct !== null ? `Handed over automatically at ${takeover.triggerPct} %` : "Handed over automatically";
  }
  const verb = takeover.status === "declined" ? "Declined" : "Confirmed";
  return takeover.decidedBy.user ? `${verb} by ${takeover.decidedBy.user.name}` : verb;
}

export function snapshotLines(takeover: Takeover): string[] {
  const snapshot = takeover.policySnapshot;
  if (!snapshot) return takeover.policyMode ? [`Workspace handoff mode at the request: ${takeover.policyMode === "auto" ? "automatic" : "confirm each handoff"}`] : [];
  const lines = [
    `Policy: ${snapshot.mode === "auto" ? "automatic" : snapshot.mode || "not reported"}` +
      (snapshot.autoThresholdPct !== null ? ` · threshold ${snapshot.autoThresholdPct} %` : "") +
      (snapshot.requireSparePct !== null ? ` · spare ${snapshot.requireSparePct} %` : "") +
      (snapshot.allowedRequesters ? ` · requesters: ${snapshot.allowedRequesters === "members" ? "members" : "admins and owners"}` : ""),
  ];
  for (const condition of snapshot.conditions) {
    lines.push(`${condition.met ? "✓" : "✗"} ${CONDITION_LABEL[condition.key] ?? condition.key}`);
  }
  return lines;
}


export function byVersionDesc(handoffs: Handoff[]): Handoff[] {
  return [...handoffs].sort((a, b) => (b.version ?? -1) - (a.version ?? -1));
}

// The server authorizes for real; a refusal is shown.
export function mayDecideTakeover(takeover: Takeover, viewer: BoardViewer | null, now = Date.now()): boolean {
  if (takeover.status !== "pending" || !viewer) return false;
  const expires = serverTimeOf(takeover.expiresAt);
  if (expires !== null && expires <= now) return false;
  return takeover.to.user?.id === viewer.userId || viewer.canAdmin;
}

export function handsToAgent(takeover: Takeover): boolean {
  return Boolean(takeover.to.agentHash);
}

export function partyLabel(party: { user: BoardUser | null; agentHash: string }): string {
  if (party.user) return party.agentHash ? `agent of ${party.user.name}` : party.user.name;
  return party.agentHash ? `agent ${shortId(party.agentHash)}` : "unknown";
}

export const TAKEOVER_STATUS_LABEL: Record<TakeoverStatus, string> = {
  pending: "waiting for confirmation",
  confirmed: "confirmed",
  declined: "declined",
  expired: "expired",
  cancelled: "cancelled",
  unknown: "status not reported",
};

export function expiryText(expiresAt: string | null, now = Date.now()): string {
  const until = serverTimeOf(expiresAt);
  if (until === null) return "expiry not reported";
  const minutes = Math.floor((until - now) / 60_000);
  if (minutes <= 0) return "expired";
  const hours = Math.floor(minutes / 60);
  return hours ? `expires in ${hours} h ${minutes % 60} min` : `expires in ${minutes} min`;
}

export const SECTION_ORDER: Array<{ key: keyof HandoffSections; label: string }> = [
  { key: "goal", label: "Goal" },
  { key: "acceptance", label: "Acceptance" },
  { key: "rules", label: "Rules and limits" },
  { key: "repo", label: "Repository" },
  { key: "commands", label: "Commands" },
  { key: "state", label: "Current state" },
  { key: "lastCommits", label: "Last commits" },
  { key: "nextSteps", label: "Next steps" },
  { key: "openDecisions", label: "Open decisions" },
  { key: "pitfalls", label: "Pitfalls" },
  { key: "notes", label: "Notes" },
  { key: "linkedSessions", label: "Linked sessions" },
  { key: "changedFiles", label: "Changed files" },
];

export function sectionLines(sections: HandoffSections, key: keyof HandoffSections): string[] {
  const value = sections[key];
  if (key === "repo" && sections.repo) {
    const repo = sections.repo;
    return [["URL", repo.url], ["Branch", repo.branch], ["Worktree", repo.worktree], ["Base commit", repo.baseCommit],
      ["WIP commit", repo.wipCommit]]
      .filter(([, entry]) => entry).map(([label, entry]) => `${label}: ${entry}`);
  }
  if (key === "commands" && sections.commands) {
    const commands = sections.commands;
    return [
      ...[["Build", commands.build], ["Test", commands.test], ["Deploy", commands.deploy]]
        .filter(([, entry]) => entry).map(([label, entry]) => `${label}: ${entry}`),
      ...commands.other,
    ];
  }
  if (Array.isArray(value)) return value.filter((entry) => typeof entry === "string" && entry.length > 0);
  return typeof value === "string" && value ? [value] : [];
}

export const HANDOFF_POLL_MS = 10_000;
