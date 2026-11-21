// A Work item's run limits under "Advanced" (backend api/routes/workflow_runs.py, services/workflow_runs/limits.py):
// "Rounds per loop" and "Cost budget (USD)". Pure: no React.
//
// PUT …/work-items/<id>/limits REPLACES the item's limits (`{loop_limit?, budget?}`), so every body carries what the
// item already has: the loop limit and the other budget keys (tokens, active_seconds, tool_calls) stay as stored.
// An empty cost field clears only `cost_usd`. The server has no cascade, so "Also set for all child items" saves the
// same cost budget on each child with the same PUT, each child keeping its own loop limit and other budget keys.

import { isEpic } from "./epicViewModel";
import type { WorkItem } from "./workItemTypes";

export type ItemLimits = { loopLimit: number | null; budget: Record<string, number> };
export type LimitsBody = { loop_limit?: number; budget?: Record<string, number> };

const positive = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value > 0;

/** GET …/limits → `{run_limits: {loop_limit?, budget?}}`, read defensively. */
export function readItemLimits(raw: unknown): ItemLimits {
  const limits = ((raw as { run_limits?: unknown } | null)?.run_limits ?? {}) as Record<string, unknown>;
  const loop = limits.loop_limit;
  const budgetRaw = (limits.budget && typeof limits.budget === "object" ? limits.budget : {}) as Record<string, unknown>;
  const budget = Object.fromEntries(Object.entries(budgetRaw).filter(([, value]) => positive(value))) as Record<string, number>;
  return { loopLimit: typeof loop === "number" && Number.isInteger(loop) && loop >= 1 ? loop : null, budget };
}

/** The fields' text for stored limits. */
export function limitsDraft(limits: ItemLimits): { loop: string; cost: string } {
  return {
    loop: limits.loopLimit ? String(limits.loopLimit) : "",
    cost: limits.budget.cost_usd ? String(limits.budget.cost_usd) : "",
  };
}

/** The cost field: empty clears the budget, otherwise a positive amount in USD (cents at most). */
export function costBudgetValue(draft: string): { value: number | null } | { error: string } {
  const text = draft.trim().replace(",", ".");
  if (!text) return { value: null };
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) return { error: "Enter an amount above 0, for example 5 or 12.50." };
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return { error: "Use at most two decimals, for example 12.50." };
  return { value };
}

/** The stored budget with `cost_usd` set (a number) or removed (null); other keys stay. */
export function budgetWithCost(budget: Record<string, number>, cost: number | null): Record<string, number> {
  const { cost_usd: _old, ...rest } = budget;
  return cost === null ? rest : { ...rest, cost_usd: cost };
}

/** The whole body for one item: its loop limit and its budget with the new cost; empty parts are left out. */
export function limitsBody(loopLimit: number | null, budget: Record<string, number>): LimitsBody {
  const body: LimitsBody = {};
  if (loopLimit) body.loop_limit = loopLimit;
  if (Object.keys(budget).length) body.budget = budget;
  return body;
}

/** A child's body when the cost budget cascades: its own limits, only the cost changed. */
export const childLimitsBody = (child: ItemLimits, cost: number | null): LimitsBody =>
  limitsBody(child.loopLimit, budgetWithCost(child.budget, cost));

export const isStory = (item: Pick<WorkItem, "issue_type">) =>
  String(item.issue_type || "").trim().toLowerCase() === "story";

/** Only an Epic or a Story offers "Also set for all child items". */
export const cascades = (item: Pick<WorkItem, "issue_type">) => isEpic(item) || isStory(item);

/** Every item below `item` in the same list: by `epic_key` (an epic's stories) and `parent_key` (sub-items), deep. */
export function childItems(item: Pick<WorkItem, "id" | "source_key">, items: readonly WorkItem[]): WorkItem[] {
  const found = new Map<string, WorkItem>();
  let keys = new Set([item.source_key].filter(Boolean));
  while (keys.size) {
    const next = new Set<string>();
    for (const candidate of items) {
      if (candidate.id === item.id || found.has(candidate.id)) continue;
      if ((candidate.epic_key && keys.has(candidate.epic_key)) || (candidate.parent_key && keys.has(candidate.parent_key))) {
        found.set(candidate.id, candidate);
        if (candidate.source_key) next.add(candidate.source_key);
      }
    }
    keys = next;
  }
  return [...found.values()];
}

/** The note after a cascade: how many children took the budget, and which did not. */
export function cascadeNote(saved: number, failed: readonly string[]): string {
  const took = saved === 1 ? "1 child item" : `${saved} child items`;
  if (!failed.length) return `Saved here and on ${took}.`;
  return `Saved here and on ${took}; not saved on ${failed.join(", ")}.`;
}

/** A refused limits save in words, shown at the field. */
export function limitsSaveError(error: unknown): string {
  const { status, code } = (error ?? {}) as { status?: number; code?: string | null };
  if (code === "invalid_run_limits" || status === 422) {
    return "The server did not accept these limits: rounds are a whole number of at least 1, the budget an amount above 0.";
  }
  if (code === "work_item_scope" || status === 403) return "You are not a member of this item's Workspace.";
  if (code === "unknown_work_item" || status === 404) return "This item no longer exists.";
  return "The run limits could not be saved. Try again.";
}
