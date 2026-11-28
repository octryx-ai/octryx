// The server patches the budget onto the Work item before the run; its other limits stay and its stories inherit it.

import type { RuntimeTarget } from "../workflowRun/runtimeTargetModel";
import { costBudgetValue } from "../work/workItemLimitsModel";

const DEVICE_PREFIX = "device:";

export function runOnTarget(key: string): RuntimeTarget | null {
  const value = key.trim();
  if (value === "auto" || value === "server" || value === "terminal") return { kind: value };
  if (!value.startsWith(DEVICE_PREFIX)) return null;
  // device_id and profile hold no ':', the folder may (a Windows path): split only twice.
  const rest = value.slice(DEVICE_PREFIX.length);
  const first = rest.indexOf(":");
  const second = first < 0 ? -1 : rest.indexOf(":", first + 1);
  if (first <= 0 || second <= first + 1 || second === rest.length - 1) return null;
  return { kind: "device", device_id: rest.slice(0, first), profile: rest.slice(first + 1, second), folder: rest.slice(second + 1) };
}

export function answerModel(runOn: string, model: string): string | undefined {
  const chosen = model.trim();
  return chosen && runOnTarget(runOn)?.kind === "device" ? chosen : undefined;
}

export type StartBudgetBody = { cost_usd: number };

/** Null when empty, so the item keeps the budget it has. */
export function startBudget(draft: string): { budget: StartBudgetBody | null } | { error: string } {
  const value = costBudgetValue(draft);
  if ("error" in value) return value;
  return { budget: value.value === null ? null : { cost_usd: value.value } };
}

export function startBudgetError(message: string): string | null {
  const refused = /^Invalid budget:\s*(.*)$/.exec(message.trim());
  return refused ? `The server did not accept this budget${refused[1] ? ` (${refused[1].replace(/\.$/, "")})` : ""}. Enter a positive amount in USD.` : null;
}

export function storedCost(raw: unknown): number | null {
  const limits = (raw as { run_limits?: { budget?: { cost_usd?: unknown } } } | null)?.run_limits;
  const cost = limits?.budget?.cost_usd;
  return typeof cost === "number" && Number.isFinite(cost) && cost > 0 ? cost : null;
}

/** null when the refusal belongs on the card's general line instead of the Model field. */
export function startModelError(message: string): string | null {
  if (message.startsWith("Choose one of your devices under Run on to pick a model")) {
    return "Pick one of your devices under Run on to choose a model, or keep Automatic.";
  }
  const refused = /^This model is not allowed here \((.*)\)\.?$/.exec(message);
  return refused ? `This model is not allowed on this device and route (${refused[1]}). Choose another or Automatic.` : null;
}
