import { readBoardUser } from "./agentBoardModel";
import type { BoardUser, BoardWorkItem } from "./agentBoardTypes";
import type { AgentsFocus } from "./agentsFocus";

export type ActionKind = "decision_request" | "handoff_confirm" | "available_handoff" | "limit_reached_with_claim";

export type ActionItem = {
  key: string;
  kind: ActionKind;
  project: { id: string; name: string };
  messageId: string;
  claimId: string;
  takeoverId: string;
  handoffId: string;
  workItem: BoardWorkItem | null;
  agentUser: BoardUser | null;
  agentHash: string;
  createdAt: string | null;
};

const KINDS: ActionKind[] = ["decision_request", "handoff_confirm", "available_handoff", "limit_reached_with_claim"];
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

export function readActionItem(value: unknown): ActionItem | null {
  if (!isRecord(value) || !isRecord(value.project) || !text(value.project.id)) return null;
  const kind = KINDS.find((entry) => entry === text(value.kind));
  if (!kind) return null;
  const work = isRecord(value.work_item) && text(value.work_item.id)
    ? { id: text(value.work_item.id), key: text(value.work_item.key), title: text(value.work_item.title) }
    : null;
  const agent = isRecord(value.agent) ? value.agent : {};
  const item = {
    kind,
    project: { id: text(value.project.id), name: text(value.project.name) || text(value.project.id) },
    messageId: text(value.message_id),
    claimId: text(value.claim_id),
    takeoverId: text(value.takeover_id),
    handoffId: text(value.handoff_id),
    workItem: work,
    agentUser: readBoardUser(agent.user),
    agentHash: text(agent.agent_hash),
    createdAt: text(value.created_at) || null,
  };
  const ref = item.takeoverId || item.messageId || item.claimId || item.handoffId || [work?.id ?? "", item.agentHash].join("/");
  return { ...item, key: [kind, item.project.id, ref].join(":") };
}

export function readActionNeeded(payload: unknown): { count: number; items: ActionItem[] } | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;
  const items = payload.items.map(readActionItem).filter((entry): entry is ActionItem => entry !== null);
  const count = typeof payload.count === "number" && Number.isFinite(payload.count) && payload.count >= 0
    ? Math.floor(payload.count)
    : items.length;
  return { count, items };
}

const HEAD: Record<ActionKind, string> = {
  decision_request: "Decision needed",
  handoff_confirm: "Takeover to confirm",
  available_handoff: "Handoff available",
  limit_reached_with_claim: "Agent at its limit holds a claim",
};

// Never a body: the title reaches the operating system's notifications.
export function actionTitle(item: ActionItem): string {
  const parts = [item.workItem?.key || "", item.agentUser ? `agent of ${item.agentUser.name}` : ""].filter(Boolean);
  return parts.length ? `${HEAD[item.kind]}: ${parts.join(" – ")}` : HEAD[item.kind];
}

// The first poll is the baseline and announces nothing.
export function newActionItems(previous: Set<string> | null, items: ActionItem[]): ActionItem[] {
  if (previous === null) return [];
  return items.filter((item) => !previous.has(item.key));
}

export function actionFocus(item: ActionItem): AgentsFocus {
  const projectId = item.project.id;
  if (item.kind === "handoff_confirm") {
    return { projectId, view: "claims", messageId: null, ...(item.takeoverId ? { takeoverId: item.takeoverId } : {}),
      ...(item.workItem ? { workItemId: item.workItem.id } : {}) };
  }
  if (item.kind === "available_handoff") {
    return { projectId, view: "claims", messageId: null, ...(item.workItem ? { workItemId: item.workItem.id } : {}),
      ...(!item.workItem && item.claimId ? { handoffClaimId: item.claimId } : {}) };
  }
  if (item.kind === "limit_reached_with_claim") return { projectId, view: "claims", messageId: null };
  return { projectId, view: "board", messageId: item.messageId || null };
}

export const ACTION_NEEDED_POLL_MS = 30_000;
