import { readJson } from "../../utils/adminPanelHelpers";
import type { SeatMode } from "./dataClassificationTypes";
import type { CodexSeatModelsBody } from "./codexSeatModelsModel";
import type { SeatSettingBody } from "./seatPolicyModel";

// The data classification routes. Answers are parsed by dataClassificationModel; refusals keep
// their HTTP status and code on the error (readJson).

const workspacePath = (projectId: string) => `/api/v1/workspaces/${encodeURIComponent(projectId)}`;

export function loadWorkspaceClassification(projectId: string): Promise<unknown> {
  return readJson<unknown>(`${workspacePath(projectId)}/data-classification`);
}

/** `null` clears the classification on purpose (the Instance default then never fills it in). */
export function saveWorkspaceClassification(projectId: string, classification: string | null): Promise<unknown> {
  return readJson<unknown>(`${workspacePath(projectId)}/data-classification`, {
    method: "PUT",
    body: JSON.stringify({ classification }),
  });
}

export function loadSeatMode(projectId: string): Promise<unknown> {
  return readJson<unknown>(`${workspacePath(projectId)}/agent-gateway/seat-mode`);
}

export function saveSeatMode(projectId: string, seatMode: SeatMode): Promise<unknown> {
  return readJson<unknown>(`${workspacePath(projectId)}/agent-gateway/seat-mode`, {
    method: "PUT",
    body: JSON.stringify({ seat_mode: seatMode }),
  });
}

/** The Codex seat's own switch, on the same route; the body names only `codex_seat_mode` (codexSeatBody). */
export function saveCodexSeatMode(projectId: string, body: { codex_seat_mode: SeatMode }): Promise<unknown> {
  return readJson<unknown>(`${workspacePath(projectId)}/agent-gateway/seat-mode`, { method: "PUT", body: JSON.stringify(body) });
}

/** One more seat key on the same route (seatPolicyModel): the body names only that key. */
export function saveSeatSetting(projectId: string, body: SeatSettingBody | CodexSeatModelsBody): Promise<unknown> {
  return readJson<unknown>(`${workspacePath(projectId)}/agent-gateway/seat-mode`, { method: "PUT", body: JSON.stringify(body) });
}

const DEFAULT_PATH = "/api/v1/admin/data-classification/default";

export function loadInstanceDefault(): Promise<unknown> {
  return readJson<unknown>(DEFAULT_PATH);
}

// The classification policy matrix: read for any signed-in user, written by platform admins.
const POLICY_PATH = "/api/v1/admin/data-classification/policy";

export function loadClassificationPolicy(): Promise<unknown> {
  return readJson<unknown>(POLICY_PATH);
}

/** The Workspace's effective policy, read-only for members; a non-member gets 404. */
export function loadWorkspacePolicySummary(projectId: string): Promise<unknown> {
  return readJson<unknown>(`${workspacePath(projectId)}/policy-summary`);
}

// Governed classification versions: draft → review → publish under the approval rule.
const VERSIONS_PATH = `${POLICY_PATH}/versions`;
const DRAFT_PATH = `${POLICY_PATH}/draft`;

export function loadClassificationVersions(): Promise<unknown> {
  return readJson<unknown>(VERSIONS_PATH);
}

export function saveClassificationDraft(body: {
  levels: { level: string; rules: Record<string, unknown> }[];
  default_level: string | null;
  level_catalog?: unknown[];
  effect_rules?: unknown[];
}): Promise<unknown> {
  return readJson<unknown>(DRAFT_PATH, { method: "PUT", body: JSON.stringify(body) });
}

export function discardClassificationDraft(): Promise<unknown> {
  return readJson<unknown>(DRAFT_PATH, { method: "DELETE" });
}

export function submitClassificationDraft(note: string | null): Promise<unknown> {
  return readJson<unknown>(`${DRAFT_PATH}/submit`, { method: "POST", body: JSON.stringify({ note }) });
}

export function decideClassificationVersion(version: number, decision: "approve" | "reject" | "rollback", comment?: string): Promise<unknown> {
  return readJson<unknown>(`${VERSIONS_PATH}/${version}/${decision}`, {
    method: "POST", body: JSON.stringify(comment ? { comment } : {}),
  });
}

export function loadGeneratedClassificationPolicies(source: "published" | "draft"): Promise<unknown> {
  return readJson<unknown>(`${POLICY_PATH}/generated?source=${source}`);
}

export function loadClassificationWorkspaces(): Promise<unknown> {
  return readJson<unknown>(`${POLICY_PATH}/workspaces`);
}

export function applyInstanceDefault(): Promise<unknown> {
  return readJson<unknown>(`${DEFAULT_PATH}/apply`, { method: "POST" });
}

export function saveWorkspaceOverrides(projectId: string, overrides: Record<string, unknown>): Promise<unknown> {
  return readJson<unknown>(`${POLICY_PATH}/workspaces/${encodeURIComponent(projectId)}/overrides`, {
    method: "PUT", body: JSON.stringify({ overrides }),
  });
}
