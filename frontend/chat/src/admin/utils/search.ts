import type { ThreadSummary } from "../../chatThreadTypes";

export function buildChatSearch(params: {
  sessionId?: string | null;
  newThread?: boolean;
  projectId?: string;
  runtimeTargetId?: string;
  agentId?: string;
  agentType?: string;
}) {
  const search = new URLSearchParams();
  if (params.sessionId) {
    search.set("session_id", params.sessionId);
  } else if (params.newThread) {
    search.set("new", "true");
  }
  if (!params.sessionId && params.projectId) {
    search.set("project_id", params.projectId);
  }
  if (!params.sessionId && params.runtimeTargetId) {
    search.set("runtime_target_id", params.runtimeTargetId);
  }
  if (!params.sessionId && params.agentId) {
    search.set("agent_id", params.agentId);
  }
  if (!params.sessionId && params.agentType) {
    search.set("agent_type", params.agentType);
  }
  const searchString = search.toString();
  return searchString ? `?${searchString}` : "";
}

export function buildComposerDraftKey(params: {
  sessionId?: string | null;
  projectId?: string;
  runtimeTargetId?: string;
  modeKey?: string;
}) {
  if (params.sessionId) {
    return `octryx-chat-draft:${params.sessionId}`;
  }
  return `octryx-chat-draft:new:${params.projectId || "global"}:${params.runtimeTargetId || "auto"}:${params.modeKey || "diagnosis"}`;
}

export function flattenThreadSearchFields(thread: ThreadSummary): string[] {
  return [
    thread.title,
    thread.preview,
    thread.projectName,
    ...(thread.subThreads ?? []).flatMap((child) =>
      flattenThreadSearchFields(child),
    ),
  ];
}
