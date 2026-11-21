import { readBoardUser } from "./agentBoardModel";
import type { BoardWorkItem } from "./agentBoardTypes";
import type { Handoff, HandoffSections, PolicySnapshot, Takeover, TakeoverStatus } from "./agentHandoffTypes";

// Structured handoffs and takeovers of the "Agents" area. Pure: no requests, no React.
//
// Contract (backend agent-board handoffs endpoint; every answer carries `viewer`):
//   GET  /api/v1/agent-board/handoffs?project_id=&work_item_id=
//        -> {items: [{id, work_item, version, author, created_at, sections}]} (latest per item, or every version of one)
//   GET  /api/v1/agent-board/handoffs/{id}
//   GET  /api/v1/agent-board/takeovers?project_id=&status=
//        -> {items: [{id, project_id, work_item, from: {user, agent_hash}, to: {user, agent_hash}, status (effective:
//                     a pending one past expires_at reads expired), reason|null, expires_at, created_at, decided_at,
//                     decided_by (freeze 3b): null | {kind: "human", user: {id, display_name}} | {kind: "system"},
//                     policy_mode, automatic, message_id, handoff: {id, version}|null}]}
//        `policy_snapshot` ({mode, auto_threshold_pct, require_spare_pct, allowed_requesters, conditions}) is stored with
//        an automatic confirm; it is shown when the answer carries it.
//        An admin's "Request handoff to…" creates one with to.agent_hash null: confirming it only releases the claim,
//        and the person's agent claims the item next. An agent's request hands the claim straight to that agent.
//   POST /api/v1/agent-board/takeovers/{id}/confirm | /decline   (the to_user, a Workspace admin/owner or a platform
//        admin; 409 takeover_not_pending when it was already decided or expired)
// Handoff sections are data written by agents or people: they stay plain strings and are rendered as text only.

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : "");
const id = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const strings = (value: unknown) => (Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : []);
const integer = (value: unknown) => (typeof value === "number" && Number.isInteger(value) ? value : null);
const STATUSES: TakeoverStatus[] = ["pending", "confirmed", "declined", "expired", "cancelled"];

function readWorkItem(value: unknown): BoardWorkItem | null {
  if (!isRecord(value) || !id(value.id)) return null;
  return { id: id(value.id), key: id(value.key), title: id(value.title) };
}

/** The sections exactly as sent; a non-string value is left out, never stringified. */
export function readSections(value: unknown): HandoffSections {
  const raw = isRecord(value) ? value : {};
  const repo = isRecord(raw.repo) ? raw.repo : null;
  const commands = isRecord(raw.commands) ? raw.commands : null;
  return {
    goal: text(raw.goal),
    acceptance: text(raw.acceptance),
    rules: text(raw.rules),
    repo: repo
      ? { url: text(repo.url), branch: text(repo.branch), worktree: text(repo.worktree), baseCommit: text(repo.base_commit),
        wipCommit: text(repo.wip_commit), bundleId: text(repo.bundle_id) }
      : null,
    commands: commands
      ? { build: text(commands.build), test: text(commands.test), deploy: text(commands.deploy), other: strings(commands.other) }
      : null,
    state: text(raw.state),
    lastCommits: strings(raw.last_commits),
    nextSteps: strings(raw.next_steps),
    openDecisions: strings(raw.open_decisions),
    pitfalls: strings(raw.pitfalls),
    notes: text(raw.notes),
    linkedSessions: strings(raw.linked_sessions),
    changedFiles: strings(raw.changed_files),
    excludedFiles: strings(raw.excluded_files),
  };
}

export function readHandoff(value: unknown): Handoff | null {
  if (!isRecord(value) || !id(value.id)) return null;
  const author = isRecord(value.author) ? value.author : {};
  return {
    id: id(value.id),
    workItem: readWorkItem(value.work_item),
    version: integer(value.version),
    authorType: id(author.type),
    author: readBoardUser(author.user),
    agentHash: id(author.agent_hash),
    createdAt: id(value.created_at) || null,
    sections: readSections(value.sections),
  };
}

export function readHandoffs(payload: unknown): Handoff[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;
  return payload.items.map(readHandoff).filter((entry): entry is Handoff => entry !== null);
}

const readParty = (value: unknown) => {
  const party = isRecord(value) ? value : {};
  return { user: readBoardUser(party.user), agentHash: id(party.agent_hash) };
};

function readPolicySnapshot(value: unknown): PolicySnapshot | null {
  if (!isRecord(value)) return null;
  const conditions = isRecord(value.conditions)
    ? Object.entries(value.conditions).filter(([, met]) => typeof met === "boolean").map(([key, met]) => ({ key, met: met as boolean }))
    : [];
  return {
    mode: id(value.mode),
    autoThresholdPct: integer(value.auto_threshold_pct),
    requireSparePct: integer(value.require_spare_pct),
    allowedRequesters: id(value.allowed_requesters),
    conditions,
  };
}

function readDecidedBy(value: unknown): Takeover["decidedBy"] {
  if (!isRecord(value)) return null;
  const kind = id(value.kind);
  if (kind === "system") return { kind: "system", user: null };
  return kind === "human" ? { kind: "human", user: readBoardUser(value.user) } : null;
}

export function readTakeover(value: unknown): Takeover | null {
  if (!isRecord(value) || !id(value.id)) return null;
  const handoff = isRecord(value.handoff) && id(value.handoff.id)
    ? { id: id(value.handoff.id), version: integer(value.handoff.version) }
    : null;
  return {
    id: id(value.id),
    workItem: readWorkItem(value.work_item),
    from: readParty(value.from),
    to: readParty(value.to),
    status: STATUSES.find((entry) => entry === id(value.status)) ?? "unknown",
    reason: text(value.reason),
    expiresAt: id(value.expires_at) || null,
    createdAt: id(value.created_at) || null,
    decidedAt: id(value.decided_at) || null,
    decidedBy: readDecidedBy(value.decided_by),
    policyMode: id(value.policy_mode),
    policySnapshot: readPolicySnapshot(value.policy_snapshot),
    triggerPct: typeof value.trigger_pct === "number" && Number.isFinite(value.trigger_pct) ? value.trigger_pct : null,
    handoff,
    automatic: value.automatic === true,
  };
}

export function readTakeovers(payload: unknown): Takeover[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;
  return payload.items.map(readTakeover).filter((entry): entry is Takeover => entry !== null);
}
