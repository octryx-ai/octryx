// Builds the run / partial-run request for exactly the saved revision the editor shows.
// The path carries that revision's id; there is no fallback to another (e.g. the published)
// revision, and nothing is sent while the next action is not "run". A DAG run starts in a
// Workspace (the flow's own, or the one chosen for the run): without one nothing is sent.
import { parseJsonObject } from "./flowBuilderDefinition";
import type { FlowNextAction } from "./flowNextAction";

export type FlowRunRequest =
  | { ok: true; path: string; body: string }
  | { ok: false; error: string };

export const RUN_WORKSPACE_REQUIRED = "Choose the Workspace this run starts in.";

export function flowRunRequest(
  nextAction: Pick<FlowNextAction, "canRun" | "detail">,
  versionId: string | undefined,
  options: { projectId: string | null; inputJson: string; nodeId?: string | null },
): FlowRunRequest {
  if (!nextAction.canRun || !versionId) return { ok: false, error: nextAction.detail };
  if (!options.projectId) return { ok: false, error: RUN_WORKSPACE_REQUIRED };
  let initialInput: Record<string, unknown>;
  try {
    initialInput = parseJsonObject<Record<string, unknown>>(options.inputJson);
  } catch (err) {
    return { ok: false, error: err instanceof Error ? `Test input: ${err.message}` : "Test input must be a JSON object." };
  }
  const partial = options.nodeId !== undefined;
  if (partial && !options.nodeId) return { ok: false, error: "Select a step before running a partial trace." };
  return {
    ok: true,
    path: `/api/v1/flows/versions/${encodeURIComponent(versionId)}/${partial ? "partial-run" : "run"}`,
    body: JSON.stringify({
      ...(partial ? { node_id: options.nodeId } : {}),
      project_id: options.projectId,
      initial_input: initialInput,
    }),
  };
}
