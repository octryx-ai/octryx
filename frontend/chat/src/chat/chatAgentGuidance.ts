// Agent identity and guidance shown in the chat. The server projects `chatAgentGuidance` for
// the bootstrap and the turn response (backend services/session/chat_agent_guidance.py); this module
// is the one place that turns it, plus the unsent composer selection, into what the composer and the
// empty chat display. Nothing here decides which agent runs or what it may do.

export type ChatAgentAvailability = "available" | "inactive" | "unavailable";
export type ChatToolSurface = "none" | "governed" | "unknown";

export type ChatAgentIdentity = {
  id: string;
  name: string | null;
  availability: ChatAgentAvailability;
};

export type ChatAgentGuidance = {
  contractVersion: 1;
  sessionId: string | null;
  nextTurnAgent: ChatAgentIdentity | null;
  nextTurnAgentSource:
    | "session_binding"
    | "launch_request"
    | "none";
  // The latest recorded turn: written when a turn is prepared, so it may have failed or still run.
  lastTurnAgent: ChatAgentIdentity | null;
  lastTurnSelectionSource: string | null;
  toolSurface: ChatToolSurface;
  contentSource:
    | "published_revision"
    | "live_draft_row"
    | "needs_publication"
    | "unknown";
};

// selected: the unsent explicit choice, sent with the next message.
// bound: the server's next-turn agent for this chat.
// latest_turn: display without guidance; the agent of the latest recorded turn, nothing more.
export type ComposerAgentRole = "selected" | "bound" | "latest_turn";

export type ComposerAgentIdentity = {
  id: string;
  label: string;
  role: ComposerAgentRole;
  availability: ChatAgentAvailability | "unknown";
  clearable: boolean;
  // "Latest turn: …" when the latest recorded turn used a different agent than the one shown.
  latestTurnNote: string;
};

// Why a new chat's requested agent ("Test in chat") is not the agent of the next message.
export type UnusedLaunchAgentReason =
  | "inactive"
  | "unavailable"
  | "not_in_list"
  | "not_selected";

export type UnusedLaunchAgent = {
  id: string;
  // Always null for "unavailable": nothing about a deleted or foreign agent is shown.
  name: string | null;
  reason: UnusedLaunchAgentReason;
};

export type ChatAgentPresentation = {
  identity: ComposerAgentIdentity | null;
  // The surface of `identity` in this session only; another agent or session is always "unknown".
  toolSurface: ChatToolSurface;
  // A requested agent that the next message does not send; shown as a notice, never as a chip.
  unusedLaunchAgent: UnusedLaunchAgent | null;
};

type SessionRef =
  | { id: string; agentId?: string | null; agentName?: string | null }
  | null
  | undefined;
type AgentOptionRef = { id: string; name: string };

const UNAVAILABLE_LABEL = "Agent unavailable";

// Guidance for the displayed session, or null: a missing field, another contract version or another
// session's guidance never applies.
export function currentChatAgentGuidance(
  guidance: ChatAgentGuidance | null | undefined,
  selectedSession: SessionRef,
): ChatAgentGuidance | null {
  if (!guidance || guidance.contractVersion !== 1) return null;
  return (guidance.sessionId ?? null) === (selectedSession?.id ?? null)
    ? guidance
    : null;
}

function unusedLaunchAgent(
  requested: ChatAgentIdentity,
  agentOptions: AgentOptionRef[],
): UnusedLaunchAgent {
  if (requested.availability !== "available") {
    return {
      id: requested.id,
      name: requested.availability === "unavailable" ? null : requested.name,
      reason: requested.availability,
    };
  }
  // Owned and active: either cleared from the selection or not offered by the agent list.
  const listed = agentOptions.some((agent) => agent.id === requested.id);
  return {
    id: requested.id,
    name: requested.name,
    reason: listed ? "not_selected" : "not_in_list",
  };
}

function identityLabel(identity: ChatAgentIdentity): string {
  if (identity.availability === "unavailable") return UNAVAILABLE_LABEL;
  return identity.name || UNAVAILABLE_LABEL;
}

type PresentationInput = {
  guidance: ChatAgentGuidance | null;
  selectedSession: SessionRef;
  routingOverridesEnabled: boolean;
  selectedAgentId: string;
  agentOptions: AgentOptionRef[];
  // A name the caller already matched to `selectedAgentId`; never an unmatched pill label.
  selectedAgentLabel?: string;
};

const NO_PRESENTATION: ChatAgentPresentation = { identity: null, toolSurface: "unknown", unusedLaunchAgent: null };

function shownIdentity(id: string, label: string, role: ComposerAgentRole, availability: ComposerAgentIdentity["availability"],
  latestTurnNote = ""): ComposerAgentIdentity {
  return { id, label, role, availability, clearable: role === "selected", latestTurnNote };
}

export function deriveChatAgentPresentation(input: PresentationInput): ChatAgentPresentation {
  if (input.routingOverridesEnabled && input.selectedAgentId) return selectedPresentation(input);
  if (input.guidance) return boundPresentation(input.guidance, input.agentOptions);
  // No guidance in the answer: only an identity that matches the session's own
  // latest-turn record is shown, never as a future binding and never with a capability.
  const sessionAgentId = input.selectedSession?.agentId || "";
  const sessionAgentName = input.selectedSession?.agentName || "";
  if (sessionAgentId && sessionAgentName && sessionAgentId === input.selectedAgentId) {
    return { ...NO_PRESENTATION, identity: shownIdentity(sessionAgentId, sessionAgentName, "latest_turn", "unknown") };
  }
  return NO_PRESENTATION;
}

// The unsent explicit choice in the composer.
function selectedPresentation({ guidance, selectedAgentId, agentOptions, selectedAgentLabel = "" }: PresentationInput):
  ChatAgentPresentation {
  const next = guidance?.nextTurnAgent ?? null;
  if (guidance && next && next.id === selectedAgentId) {
    return {
      identity: shownIdentity(next.id, identityLabel(next), "selected", next.availability),
      toolSurface: next.availability === "available" ? guidance.toolSurface : "unknown",
      unusedLaunchAgent: null,
    };
  }
  // The catalog lists owned, active agents only; it carries no tool surface.
  const option = agentOptions.find((agent) => agent.id === selectedAgentId);
  const label = option?.name || selectedAgentLabel || "Selected agent";
  return { ...NO_PRESENTATION, identity: shownIdentity(selectedAgentId, label, "selected", option ? "available" : "unknown") };
}

// The server's next-turn agent for this chat.
function boundPresentation(guidance: ChatAgentGuidance, agentOptions: AgentOptionRef[]): ChatAgentPresentation {
  const next = guidance.nextTurnAgent;
  if (!next) return NO_PRESENTATION;
  if (guidance.nextTurnAgentSource === "launch_request") {
    // A requested agent is not a binding: it runs only when the send carries it, which the
    // explicit branch covers. Anything else would show an agent that does not run.
    return { ...NO_PRESENTATION, unusedLaunchAgent: unusedLaunchAgent(next, agentOptions) };
  }
  const latest = guidance.lastTurnAgent;
  const latestTurnNote = latest && latest.id !== next.id ? `Latest turn: ${identityLabel(latest)}` : "";
  return {
    identity: shownIdentity(next.id, identityLabel(next), "bound", next.availability, latestTurnNote),
    toolSurface: next.availability === "available" ? guidance.toolSurface : "unknown",
    unusedLaunchAgent: null,
  };
}
