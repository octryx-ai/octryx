import { storeWorkspacePreference } from "../activeWorkspace";

// The area may not be mounted yet, so the focus is kept until the area takes it.

export type AgentsFocus = {
  projectId: string;
  view: "board" | "claims";
  messageId: string | null;
  takeoverId?: string;
  workItemId?: string;
  handoffClaimId?: string;
};

export const AGENTS_FOCUS_EVENT = "octryx-agents-focus";
let pending: AgentsFocus | null = null;

export function requestAgentsFocus(focus: AgentsFocus) {
  pending = focus;
  storeWorkspacePreference(focus.projectId);
  window.dispatchEvent(new CustomEvent(AGENTS_FOCUS_EVENT, { detail: focus }));
}

/** The Workspace itself is read from `workspace_id` by the shared Workspace selection. */
export function readUrlAgentsFocus(search: string): AgentsFocus | null {
  const params = new URLSearchParams(search);
  const projectId = params.get("workspace_id") || "";
  const messageId = params.get("board_message_id");
  if (messageId) return { projectId, view: "board", messageId };
  const takeoverId = params.get("takeover_id");
  if (takeoverId) return { projectId, view: "claims", messageId: null, takeoverId };
  const handoffClaimId = params.get("handoff_claim_id");
  if (handoffClaimId) return { projectId, view: "claims", messageId: null, handoffClaimId };
  return params.get("claim_id") ? { projectId, view: "claims", messageId: null } : null;
}

export function takeAgentsFocus(): AgentsFocus | null {
  const focus = pending;
  pending = null;
  return focus;
}

const URL_VIEWS = ["clients", "install", "board", "claims", "classification", "policy"] as const;
type UrlAgentsView = (typeof URL_VIEWS)[number];

export function readUrlAgentsView(search: string): UrlAgentsView | null {
  const view = new URLSearchParams(search).get("agents_view");
  return (URL_VIEWS as readonly string[]).includes(view ?? "") ? (view as UrlAgentsView) : null;
}

export function agentsViewHref(projectId: string, view: UrlAgentsView): string {
  return `/chat?${new URLSearchParams({ area: "agents", workspace_id: projectId, agents_view: view }).toString()}`;
}

/** The name of the Workspace seat card wherever it is offered (admins look for "seat", not "classification"). */
export const SEAT_CARD_LABEL = "Seats & data classification";

export const seatCardHref = (projectId: string) => agentsViewHref(projectId, "classification");

export const agentsPolicyHref = (projectId: string) => agentsViewHref(projectId, "policy");
