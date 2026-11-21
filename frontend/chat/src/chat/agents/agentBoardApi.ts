import { readJson } from "../../admin/utils/adminPanelHelpers";

// The agent board routes. Answers are parsed by agentBoardModel / actionNeededModel;
// refusals keep their HTTP status and code on the error (readJson).

const BASE = "/api/v1/agent-board";
const post = (path: string, body: unknown = {}) => readJson<unknown>(`${BASE}${path}`, { method: "POST", body: JSON.stringify(body) });

export type BoardFilters = { workItemId?: string; kind?: string; agentHash?: string };

export function loadBoardMessages(projectId: string, filters: BoardFilters, cursor: string | null, limit: number): Promise<unknown> {
  const params = new URLSearchParams({ project_id: projectId, limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  if (filters.workItemId) params.set("work_item_id", filters.workItemId);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.agentHash) params.set("agent_hash", filters.agentHash);
  return readJson<unknown>(`${BASE}/messages?${params.toString()}`);
}

export function loadBoardThread(messageId: string): Promise<unknown> {
  return readJson<unknown>(`${BASE}/messages/${encodeURIComponent(messageId)}/thread`);
}

/** Answers a decision request with one of its options and/or a short text. */
export function postDecision(messageId: string, decision: { option?: string; text?: string }): Promise<unknown> {
  return post(`/messages/${encodeURIComponent(messageId)}/decision`, decision);
}

export function redactMessage(messageId: string): Promise<unknown> {
  return post(`/messages/${encodeURIComponent(messageId)}/redact`);
}

export function requestHandoff(request: { project_id: string; work_item_id: string; to_user_id: string; body: string }): Promise<unknown> {
  return post("/handoff-requests", request);
}

export function loadClaims(projectId: string): Promise<unknown> {
  return readJson<unknown>(`${BASE}/claims?project_id=${encodeURIComponent(projectId)}`);
}

export function releaseClaim(claimId: string): Promise<unknown> {
  return post(`/claims/${encodeURIComponent(claimId)}/release`);
}

/** Freeze 3c, admins: posts the handoff request now; the holder's launcher hands its work over on its next hook call. */
export function handOverNow(claimId: string): Promise<unknown> {
  return post(`/claims/${encodeURIComponent(claimId)}/hand-over-now`);
}

/** Freeze 3c: a handoff's git bundle, downloaded with the platform login by Workspace members. */
export function handoffBundleHref(bundleId: string): string {
  return `${BASE}/handoff-attachments/${encodeURIComponent(bundleId)}`;
}

export function loadActionNeeded(): Promise<unknown> {
  return readJson<unknown>(`${BASE}/action-needed`);
}

// Structured handoffs and takeovers.
export function loadHandoffs(projectId: string, workItemId: string | null = null): Promise<unknown> {
  const params = new URLSearchParams({ project_id: projectId });
  if (workItemId) params.set("work_item_id", workItemId);
  return readJson<unknown>(`${BASE}/handoffs?${params.toString()}`);
}

export function loadTakeovers(projectId: string, status: string | null = null): Promise<unknown> {
  const params = new URLSearchParams({ project_id: projectId });
  if (status) params.set("status", status);
  return readJson<unknown>(`${BASE}/takeovers?${params.toString()}`);
}

export function confirmTakeover(takeoverId: string): Promise<unknown> {
  return post(`/takeovers/${encodeURIComponent(takeoverId)}/confirm`);
}

export function declineTakeover(takeoverId: string): Promise<unknown> {
  return post(`/takeovers/${encodeURIComponent(takeoverId)}/decline`);
}
