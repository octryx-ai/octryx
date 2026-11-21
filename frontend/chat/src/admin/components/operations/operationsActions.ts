// Operations row actions: main action, abort candidates, acknowledging problems, stopping jobs, links and cost lines.
import { seatShort } from "../../../chat/cost/seatEquivalent";
import type { OpsDevice, OpsItem, OpsJob, OpsProblem, OpsRun } from "./operationsTypes";
import { whereText } from "./operationsWhere";
import { costText, waitsFor } from "./operationsWords";

// ---- Actions ---------------------------------------------------------------------------------------------------

export type ActionContext = { isAdmin: boolean; me: string; devices: OpsDevice[] };

/**
 * The main action of a run: answer when it waits for the person, else open its chat. Abort is offered as a
 * candidate on every active run; the page asks the run itself (GET workflow-runs/{id}, run.actions) before it
 * shows the confirm step, because only the server knows whether the viewer may abort.
 */
export function runMainAction(run: Pick<OpsRun, "state" | "sessionId"> & Partial<Pick<OpsRun, "requestedBy" | "responsible">>): { label: string } | null {
  if (!run.sessionId) return null;
  return { label: run.state === "needs_you" && !waitsFor(run) ? "Answer" : "Open" };
}

export function canAbortCandidate(run: Pick<OpsRun, "status">): boolean {
  return ["running", "waiting", "paused"].includes(run.status);
}

/** Problems an admin can hide until they happen again (the run's and its items'). */
export function acknowledgeable(problems: OpsProblem[], ctx: Pick<ActionContext, "isAdmin">): OpsProblem[] {
  return ctx.isAdmin ? problems : [];
}

const STOPPABLE = new Set(["queued", "starting", "running", "idle", "waiting"]);

/**
 * A device job can be stopped by its owner only (the server refuses everyone else), and only while it is active.
 * The owner is the device's (is_me from the server, else the viewer's id).
 */
export function canStopJob(job: OpsJob | null, ctx: Pick<ActionContext, "me" | "devices">): boolean {
  if (!job || !STOPPABLE.has(job.status)) return false;
  const owner = ctx.devices.find((entry) => entry.id === job.deviceId)?.owner ?? null;
  return Boolean(owner && (owner.isMe || (ctx.me && owner.id === ctx.me)));
}

/** An item's last sign of life: its job's last event, else when it finished or started. */
export function itemLastSeen(item: Pick<OpsItem, "job" | "startedAt" | "finishedAt">): string | null {
  return item.job?.lastEventAt ?? item.finishedAt ?? item.startedAt ?? null;
}

export function openHref(sessionId: string, workspaceId?: string): string {
  const params = new URLSearchParams({ session_id: sessionId });
  if (workspaceId) params.set("workspace_id", workspaceId);
  return `/chat?${params.toString()}`;
}

/** "API $0.41" and, apart, "Seat $1.20 (list price)": the run's two figures for a line, never one sum. */
export function runCostParts(run: Pick<OpsRun, "costUsd" | "seat">): string[] {
  const api = costText(run.costUsd);
  return [api ? `API ${api}` : "", seatShort(run.seat)].filter(Boolean);
}

/** The phone's card line: the step and where it runs, or the item that loops. */
export function cardLine(run: OpsRun, devices: OpsDevice[] = []): string {
  const looping = run.items.find((item) => item.problems.some((problem) => problem.reasonCode === "looping"))
    ?? (run.state === "looping" ? [...run.items].sort((a, b) => b.dispatches5m - a.dispatches5m)[0] : undefined);
  const where = whereText(run.where, devices).place;
  if (looping) return [`${looping.title} started ${looping.dispatches5m}× in 5 min`, where].filter(Boolean).join(" · ");
  return [run.currentNode, where, ...runCostParts(run)].filter(Boolean).join(" · ");
}
