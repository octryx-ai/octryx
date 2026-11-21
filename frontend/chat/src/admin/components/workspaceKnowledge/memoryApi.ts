import { knowledgeBase, request } from "./workspaceKnowledgeRequest";

// One memory item of the Memory lobe: experience from a session, never a cited source.
export type MemoryItem = {
  id: string;
  kind: "memory";
  scope: "personal" | "workspace";
  class: string;
  author_class: "human_stated" | "model_inferred" | "verified";
  state: "observed" | "confirmed" | "superseded" | "contradicted" | "expired" | "forgotten" | "promoted" | "proposed";
  product: string | null;
  text: string | null;
  recorded_by: string | null;
  present_as: string | null;
  session_id: string | null;
  session_link: string | null;
  supersedes_id: string | null;
  created_at: string | null;
  expires_at: string | null;
  state_changed_at: string | null;
  may_change: boolean;
};

export type MemoryOverview = {
  workspace_id: string;
  may_author: boolean;
  // Automatic capture at turn end (inferred memories); off unless an admin or owner turns it on.
  automatic_capture: boolean;
  // Lessons learned proposed by octryx sessions (off by default), and who may confirm them.
  session_lessons?: boolean;
  confirm_roles?: string[];
  items: MemoryItem[];
};

export const CONFIRM_ROLE_CHOICES = ["viewer", "member", "owner", "admin"] as const;

function memoryBase(workspaceId: string): string {
  return `${knowledgeBase(workspaceId)}/memory`;
}

function itemUrl(workspaceId: string, memoryId: string, action: string): string {
  return `${memoryBase(workspaceId)}/${encodeURIComponent(memoryId)}/${action}`;
}

export const memoryApi = {
  list: (workspaceId: string, includeHistory: boolean) =>
    request<MemoryOverview>(`${memoryBase(workspaceId)}${includeHistory ? "?include_history=true" : ""}`),
  confirm: (workspaceId: string, memoryId: string) =>
    request<MemoryOverview>(itemUrl(workspaceId, memoryId, "confirm"), { method: "POST" }),
  correct: (workspaceId: string, memoryId: string, text: string) =>
    request<MemoryOverview>(itemUrl(workspaceId, memoryId, "correct"), {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  reject: (workspaceId: string, memoryId: string) =>
    request<MemoryOverview>(itemUrl(workspaceId, memoryId, "reject"), { method: "POST" }),
  setLessons: (workspaceId: string, settings: { session_lessons?: boolean; confirm_roles?: string[] }) =>
    request<MemoryOverview>(`${memoryBase(workspaceId)}/settings`, {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  forget: (workspaceId: string, memoryId: string) =>
    request<MemoryOverview>(itemUrl(workspaceId, memoryId, "forget"), { method: "POST" }),
  setAutomaticCapture: (workspaceId: string, enabled: boolean) =>
    request<MemoryOverview>(`${memoryBase(workspaceId)}/settings`, {
      method: "PUT",
      body: JSON.stringify({ automatic_capture: enabled }),
    }),
};
