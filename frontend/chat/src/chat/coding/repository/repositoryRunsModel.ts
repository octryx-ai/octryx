// Read only when the panel opens: a Runs column would cost one request per row on page load.

import type { StatusTone } from "../../../layout/StatusLabel";
import type { SeatFigures } from "../../cost/seatEquivalent";
import { costText, runName, runSeat, runTone, statusWord, type WorkRunRow } from "../../work/workRunsModel";
import { chatSessionHref } from "../../workflowRun/workflowRunModel";
import { WORKFLOW_RUNS_PATH } from "../../workflowRun/workflowRunRequests";

export const RECENT_RUNS = 10;

export type RepositoryRun = WorkRunRow & { repository?: string | null; branch?: string | null };

export type RepositoryRunRow = {
  key: string; name: string; href: string | null; status: string; tone: StatusTone;
  // seat is the API list-price equivalent of the seat calls, kept apart from cost.
  branch: string | null; when: string | null; cost: string; seat: SeatFigures;
};

export function repositoryRunsPath(recordId: string): string {
  return `${WORKFLOW_RUNS_PATH}?${new URLSearchParams({ view: "work", repository_id: recordId }).toString()}`;
}

function timeOf(run: RepositoryRun): number {
  const value = Date.parse(run.updated_at ?? run.created_at ?? "");
  return Number.isFinite(value) ? value : 0;
}

export function recentRepositoryRuns(runs: RepositoryRun[], limit = RECENT_RUNS): RepositoryRunRow[] {
  return [...runs].filter((run) => run && typeof run.id === "string")
    .sort((a, b) => timeOf(b) - timeOf(a)).slice(0, limit)
    .map((run) => ({
      key: run.id, name: runName(run), href: run.session_id ? chatSessionHref(run.session_id) : null,
      status: statusWord(run), tone: runTone(run), branch: run.branch?.trim() || null,
      when: run.created_at ?? run.updated_at ?? null, cost: costText(run.cost),
      seat: runSeat(run),
    }));
}

export function runsCountText(total: number, shown: number): string {
  return total > shown ? `The latest ${shown} of ${total} runs.` : "";
}

export function runsErrorText(message: string): string {
  return /repository record does not exist|repository_not_found/i.test(message)
    ? "This repository record no longer exists. Reload the page."
    : "The runs of this repository could not be loaded. Try again.";
}
