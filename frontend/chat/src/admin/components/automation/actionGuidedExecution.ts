import type { PanelAgentRow } from "../taskTypes";
import { hasAuthoredInstruction } from "./actionGuidedPath";

export type AgentExecutionSource = {
  mode: string;
  published_revision_number: number | null;
};

export type ExecutionLookup =
  | { status: "idle" }
  | { status: "loading"; agentId: string }
  | {
      status: "ready";
      agentId: string;
      execution: AgentExecutionSource | null;
      latestRevision: number | null;
      latestRevisionStatus?: string | null;
      latestSnapshot?: unknown;
    }
  | { status: "failed"; agentId: string; error: string };

export type ExecutionView = {
  text: string;
  runnable: boolean;
  retry: boolean;
  mode?: "draft" | "published";
  publishedRevision?: number;
};

const isRevisionNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value > 0;

export function executionView(
  lookup: ExecutionLookup,
  agentId: string,
): ExecutionView {
  if (
    lookup.status === "idle" ||
    lookup.agentId !== agentId ||
    lookup.status === "loading"
  ) {
    return {
      text: "Checking which version of the agent this action runs…",
      runnable: false,
      retry: false,
    };
  }
  if (lookup.status === "failed") {
    return {
      text: `Could not check which version of the agent runs: ${lookup.error}`,
      runnable: false,
      retry: true,
    };
  }
  const execution = lookup.execution;
  if (!execution || typeof execution.mode !== "string") {
    return {
      text: "This server did not say which version of the agent runs, so the action cannot be saved here.",
      runnable: false,
      retry: true,
    };
  }
  if (execution.mode === "draft") {
    return {
      text: "Each run uses the agent's saved settings and steps as they are at that time, including unpublished changes.",
      runnable: true,
      retry: false,
      mode: "draft",
    };
  }
  if (execution.mode === "published") {
    const published: unknown = execution.published_revision_number;
    if (published === null || published === undefined) {
      return {
        text: "The agent has no published revision, so its runs would be refused. Publish it on the agent's page first.",
        runnable: false,
        retry: false,
      };
    }
    if (!isRevisionNumber(published)) {
      return {
        text: "This server reported an invalid published revision, so the action cannot be saved here.",
        runnable: false,
        retry: true,
      };
    }
    const newer =
      isRevisionNumber(lookup.latestRevision) &&
      lookup.latestRevision > published
        ? " The agent has newer changes; they are used only after they are published."
        : "";
    return {
      text: `Each run uses published revision ${published} of the agent.${newer}`,
      runnable: true,
      retry: false,
      mode: "published",
      publishedRevision: published,
    };
  }
  return {
    text: "The platform's agent execution mode is not configured correctly, so this agent's runs would be refused.",
    runnable: false,
    retry: false,
  };
}

export type InstructionCheck =
  | { state: "authored" | "missing"; source: "live" | "published" }
  | { state: "deferred"; publishedRevision: number };

function snapshotHasAuthoredInstruction(snapshot: unknown): boolean | null {
  if (!snapshot || typeof snapshot !== "object") return null;
  const { definition, steps } = snapshot as {
    definition?: unknown;
    steps?: unknown;
  };
  if (!definition || typeof definition !== "object") return null;
  const header = definition as Record<string, unknown>;
  const filled = (value: unknown) =>
    typeof value === "string" && value.trim() !== "";
  return (
    filled(header.goal) ||
    filled(header.system_prompt) ||
    filled(header.output_prompt) ||
    (Array.isArray(steps) ? steps : []).some(
      (step) =>
        Boolean(step) &&
        typeof step === "object" &&
        (step as Record<string, unknown>).is_enabled === true &&
        filled((step as Record<string, unknown>).instructions),
    )
  );
}

// Published content is checked only when the newest revision is the published one; otherwise runtime admission decides.
export function instructionCheck(
  view: ExecutionView,
  lookup: ExecutionLookup,
  agent: PanelAgentRow,
): InstructionCheck {
  if (view.mode === "draft") {
    return {
      state: hasAuthoredInstruction(agent) ? "authored" : "missing",
      source: "live",
    };
  }
  const published = view.publishedRevision as number;
  if (
    lookup.status === "ready" &&
    lookup.latestRevision === published &&
    lookup.latestRevisionStatus === "published"
  ) {
    const authored = snapshotHasAuthoredInstruction(lookup.latestSnapshot);
    if (authored !== null) {
      return { state: authored ? "authored" : "missing", source: "published" };
    }
  }
  return { state: "deferred", publishedRevision: published };
}

export function deferredInstructionNote(
  check: InstructionCheck,
): string | null {
  return check.state === "deferred"
    ? `Whether published revision ${check.publishedRevision} gives the agent a task is checked when the action runs. If it has no instructions of its own and this field is empty, the run is refused.`
    : null;
}
