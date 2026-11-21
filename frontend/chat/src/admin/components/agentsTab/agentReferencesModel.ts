// Pure presenter of the agent page's "Used by" section. The backend
// lists only workflows the caller may already read, so the labels never claim a
// global total: they describe what this caller can see.
// The editor opens the latest version (the editor link carries only the id),
// so every row says which version the link opens and whether that version
// still uses the agent; a row never implies the link shows an older version.
import { flowEditorHref } from "../../editorLinks";

export type AgentReferenceState = "published" | "in_review" | "current_draft" | "older_revision_only";

export type AgentReference = {
  kind: "workflow";
  id: string;
  name: string;
  workspace_id: string | null;
  workspace_name: string | null;
  reference_state: AgentReferenceState | string;
  revision: number;
  latest_revision?: number;
  latest_references_agent?: boolean;
};

export type AgentReferencesPayload = {
  agent_id: string;
  workflows: AgentReference[];
  truncated: boolean;
};

export type AgentReferenceRow = {
  key: string;
  name: string;
  href: string;
  linkLabel: string;
  workspace: string;
  state: string;
  destination: string;
};

export const NO_REFERENCES_TEXT = "No workflow you can see uses this agent.";
export const TRUNCATED_TEXT = "Only the first matches are listed here; more items you can see may use this agent.";

export function agentReferencesUrl(agentId: string): string {
  return `/admin/chat/api/panel/agents/${encodeURIComponent(agentId)}/references`;
}

// Plain-words state: which version references the agent and whether it runs.
export function referenceStateLabel(reference: Pick<AgentReference, "reference_state" | "revision">): string {
  const number = `version ${reference.revision}`;
  switch (reference.reference_state) {
    case "published":
      return `Published ${number}`;
    case "in_review":
      return `In review, ${number}`;
    case "current_draft":
      return `Current draft, ${number} (not published)`;
    case "older_revision_only":
      return `Only an older ${number}`;
    default:
      return `Referenced in ${number}`;
  }
}

// What the editor link opens: always the latest version. When that version no
// longer uses the agent, say so.
export function referenceDestinationLabel(
  reference: Pick<AgentReference, "revision" | "latest_revision" | "latest_references_agent">,
): string {
  const latest = reference.latest_revision;
  if (typeof latest !== "number") return "Opens the latest version";
  if (reference.latest_references_agent === false) {
    return `Opens the latest version ${latest}, which no longer uses this agent`;
  }
  if (latest === reference.revision) return `Opens version ${latest}, the latest`;
  return `Opens the latest version ${latest}, which also uses this agent`;
}

export function referenceWorkspaceLabel(reference: Pick<AgentReference, "workspace_id" | "workspace_name">): string {
  if (!reference.workspace_id) return "Global";
  return reference.workspace_name || "Workspace not visible to you";
}

export function referenceRow(reference: AgentReference): AgentReferenceRow {
  const latest = typeof reference.latest_revision === "number" ? ` ${reference.latest_revision}` : "";
  return {
    key: `${reference.kind}:${reference.id}`,
    name: reference.name,
    href: flowEditorHref(reference.id),
    linkLabel: `Open workflow ${reference.name} at its latest version${latest}`,
    workspace: referenceWorkspaceLabel(reference),
    state: referenceStateLabel(reference),
    destination: referenceDestinationLabel(reference),
  };
}

export function agentReferenceGroups(payload: AgentReferencesPayload | null) {
  const workflows = (payload?.workflows || []).map(referenceRow);
  return {
    workflows,
    empty: workflows.length === 0,
    truncated: Boolean(payload?.truncated),
  };
}
