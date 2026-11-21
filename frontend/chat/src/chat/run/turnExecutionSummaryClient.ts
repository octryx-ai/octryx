import { chatApiPath } from "../chatApiClient";
import { parseTurnExecutionSummary } from "./turnExecutionSummaryParse";
import type { TurnExecutionSummaryLoad } from "./turnExecutionSummary.types";

// Read-only GET. Loading the summary must never trigger evaluation or any
// other write, so this client intentionally exposes no other verb.
export async function fetchTurnExecutionSummary(
  traceId: string,
  signal?: AbortSignal,
): Promise<Exclude<TurnExecutionSummaryLoad, { status: "idle" | "loading" }>> {
  let response: Response;
  try {
    response = await fetch(
      chatApiPath(
        `/turn-traces/${encodeURIComponent(traceId)}/execution-summary`,
      ),
      {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal,
      },
    );
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }
    return { status: "error" };
  }
  if (response.status === 404) {
    return { status: "unavailable", reason: "not_found" };
  }
  if (!response.ok) {
    // Raw error details are intentionally not surfaced.
    return { status: "error" };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { status: "error" };
  }
  const summary = parseTurnExecutionSummary(payload);
  return summary
    ? { status: "ready", summary }
    : { status: "unavailable", reason: "unsupported_version" };
}
