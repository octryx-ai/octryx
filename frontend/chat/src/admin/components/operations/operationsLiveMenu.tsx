// The row menu of Operations › Live: acknowledge a problem, abort a run, open an item's chat or stop its device job.
// Abort and stop are confirmed first; every action shows its outcome as a notice and reloads the view.
import type { ReactNode } from "react";

import type { useConfirmAction } from "../confirm/useConfirmAction";
import { ActionMenu, type ActionMenuItem } from "../workflowSurfaces/ActionMenu";
import { abortRun, acknowledgeOpsProblem, loadRunActions, stopDeviceJob } from "./operationsApi";
import { acknowledgeable, canAbortCandidate, canStopJob, openHref, type ActionContext } from "./operationsActions";
import { problemWords } from "./operationsWords";
import { type OpsItem, type OpsProblem, type OpsRun } from "./operationsTypes";
import type { Row } from "./OperationsLiveCells";

type MenuInput = {
  ctx: ActionContext;
  confirm: ReturnType<typeof useConfirmAction>;
  reload: () => Promise<void>;
  setNotice: (notice: string) => void;
};

// Shows the outcome of an action as a notice, then reloads.
async function act({ setNotice, reload }: MenuInput, work: () => Promise<void>, done: string) {
  try {
    await work();
    setNotice(done);
  } catch (failure) {
    setNotice(failure instanceof Error ? failure.message : "The action failed.");
  }
  await reload();
}

// Abort only when the run offers it to this viewer (its reason field too), after a confirmation.
async function askAbort({ confirm, reload, setNotice }: MenuInput, run: OpsRun) {
  setNotice("");
  let offered;
  try {
    offered = (await loadRunActions(run.id)).find((action) => action.key === "abort");
  } catch (failure) {
    setNotice(failure instanceof Error ? failure.message : "The run could not be read.");
    return;
  }
  if (!offered) {
    setNotice(`“${run.title}” cannot be aborted by you right now.`);
    return;
  }
  confirm.ask({
    title: `Abort “${run.title}”?`,
    body: <p className="ops-confirm">The run stops now and cannot be resumed. Its running steps and device jobs are
      stopped; finished work, branches and pull requests stay as they are.</p>,
    confirmLabel: "Abort run",
    field: offered.input ? { label: offered.input.label || "Reason", placeholder: "Why it is stopped (optional)" } : undefined,
    run: async (reason) => { await abortRun(run.id, reason); await reload(); },
    done: `“${run.title}” was aborted.`,
  });
}

function askStop({ confirm, reload }: MenuInput, run: OpsRun, item: OpsItem) {
  if (!item.job) return;
  const jobId = item.job.id;
  confirm.ask({
    title: `Stop the job of “${item.title}”?`,
    body: <p className="ops-confirm">The device stops this item's job now. The run itself keeps going and may start
      the item again.</p>,
    confirmLabel: "Stop job",
    run: async () => { await stopDeviceJob(jobId); await reload(); },
    done: `The job of “${item.title}” in “${run.title}” was stopped.`,
  });
}

export function liveRowMenu(input: MenuInput): (row: Row) => ReactNode {
  const { ctx } = input;
  const ackItems = (problems: OpsProblem[]): ActionMenuItem[] => acknowledgeable(problems, ctx).map((problem) => ({
    label: `Acknowledge “${problemWords(problem)}”`,
    onSelect: () => void act(input, () => acknowledgeOpsProblem(problem.key), `Hidden until it happens again: ${problem.title || problemWords(problem)}`),
  }));

  const menu = (row: Row) => {
    const items: ActionMenuItem[] = row.kind === "run"
      ? [
        ...ackItems(row.run.problems),
        ...(canAbortCandidate(row.run) ? [{ label: "Abort run…", danger: true, onSelect: () => void askAbort(input, row.run), testId: "ops-abort" }] : []),
      ]
      : [
        ...(row.item.sessionId ? [{ label: "Open item chat", onSelect: () => window.location.assign(openHref(row.item.sessionId, row.run.workspace?.id)) }] : []),
        ...ackItems(row.item.problems),
        ...(canStopJob(row.item.job, ctx) ? [{ label: "Stop job…", danger: true, onSelect: () => askStop(input, row.run, row.item), testId: "ops-stop-job" }] : []),
      ];
    const name = row.kind === "run" ? row.run.title : row.item.title;
    return items.length ? <ActionMenu row={{ objectName: name }} items={items} /> : null;
  };
  return menu;
}
