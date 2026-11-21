import type { SelectedSession } from "../chatThreadTypes";

type RoutingSummaryArgs = {
  selectedSession: SelectedSession | null;
  workspaceLabel: string;
  runtimeLabel: string;
};

// The closed agent selection sources of a turn (backend `agent_selection_sources`).
const AGENT_SELECTION_EXPLANATIONS: Record<string, string> = {
  explicit: "The agent was chosen explicitly.",
  session: "The thread's agent continues.",
  mention: "The prompt named the agent with an exact @mention.",
  default: "The Workspace default agent runs.",
  none: "No agent was chosen; the turn runs without an agent definition.",
};

export type RoutingSummary = {
  label: string;
  detail: string;
};

function humanizeToken(value: string | null | undefined, fallback: string) {
  const normalized = String(value || "")
    .trim()
    .replace(/^intent:/, "")
    .replace(/[_:-]+/g, " ")
    .replace(/\s+/g, " ");
  if (!normalized) {
    return fallback;
  }
  return normalized.replace(/\b\w/g, (character) => character.toUpperCase());
}

function explainReason(reason: string | null | undefined) {
  const normalized = String(reason || "").trim();
  if (!normalized) {
    return "The execution path is derived from the task, workspace, and policy.";
  }
  if (normalized.startsWith("intent:")) {
    return `Task wording matched ${humanizeToken(normalized, "the selected intent")}.`;
  }
  if (AGENT_SELECTION_EXPLANATIONS[normalized]) {
    return AGENT_SELECTION_EXPLANATIONS[normalized];
  }
  return humanizeToken(normalized, "Policy selected this route.");
}

export function buildRoutingSummary({
  selectedSession,
  workspaceLabel,
  runtimeLabel,
}: RoutingSummaryArgs): RoutingSummary {
  if (!selectedSession) {
    return {
      label: "Route · Auto",
      detail:
        "Ask in plain language. Runtime, workspace, and thinking are explicit controls; mode, agent group, and agent are derived by policy.",
    };
  }

  const workspace = selectedSession.projectName || workspaceLabel || "Global";
  const runtime = selectedSession.runtimeLabel || runtimeLabel || "Automatic";
  const routeName = humanizeToken(
    selectedSession.routingIntent || selectedSession.agentType,
    "Auto",
  );
  const reason = explainReason(
    selectedSession.routingReason || selectedSession.agentSelectionSource,
  );

  return {
    label: `Route · ${routeName}`,
    detail: [
      `Workspace: ${workspace}.`,
      `Runtime: ${runtime}.`,
      reason,
      "Mode, agent group, and agent remain policy-derived and hidden from the launch surface.",
    ].join(" "),
  };
}
