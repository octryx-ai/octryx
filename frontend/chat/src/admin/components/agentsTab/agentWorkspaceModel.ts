export type WorkspaceOption = { id: string; name: string; is_active?: boolean };

// An inactive workspace the agent already uses stays visible so editing never silently rebinds the agent.
export function agentWorkspaceOptions(projects: WorkspaceOption[], currentProjectId?: string | null) {
  const current = (currentProjectId || "").trim();
  return projects
    .filter((project) => project.is_active !== false || project.id === current)
    .map((project) => ({
      id: project.id,
      label: project.is_active === false ? `${project.name} (inactive)` : project.name,
      inactive: project.is_active === false,
    }));
}

// A global agent needs an explicit workspace so the chat never keeps one remembered elsewhere.
export function agentTestChatHref(agentId: string, workspaceId: string | null): string {
  const params = new URLSearchParams({ new: "true", agent_id: agentId });
  if (workspaceId) {
    params.set("project_id", workspaceId);
    params.set("workspace_id", workspaceId);
  }
  return `/chat?${params.toString()}`;
}

export type AgentRevision = { id: string; revision_number: number; status: string };

export function revisionLabel(revision: AgentRevision | null): string {
  if (!revision) return "No revision recorded yet";
  if (revision.status === "draft") return `Draft revision ${revision.revision_number} · not published`;
  if (revision.status === "published") return `Published revision ${revision.revision_number}`;
  return `Revision ${revision.revision_number} · ${revision.status}`;
}

export function stepToolsLabel(allowedTools: string[] | undefined): string {
  return allowedTools?.length
    ? `Limited to: ${allowedTools.join(", ")}`
    : "No step-level restriction — tools still depend on the agent's mode, workspace connectors and policy";
}

export type AgentExecutionSource = { mode: string; published_revision_number: number | null };

export function executionSourceLabel(
  execution: AgentExecutionSource | null,
  latest: AgentRevision | null,
): { text: string; blocked: boolean } {
  if (!execution) return { text: "", blocked: false };
  if (execution.mode === "draft") {
    return { text: "Chats run the saved settings and steps as they are now, including unpublished changes.", blocked: false };
  }
  if (execution.mode === "published") {
    const published = execution.published_revision_number;
    if (published === null) {
      return { text: "Chats run published revisions only, and this agent has none yet. Publish a draft to test it.", blocked: true };
    }
    const newer = latest && latest.revision_number > published ? " Newer draft changes are not used until published." : "";
    return { text: `Chats run published revision ${published}.${newer}`, blocked: false };
  }
  return { text: "The platform execution mode is not configured correctly, so chats with this agent are refused.", blocked: true };
}
