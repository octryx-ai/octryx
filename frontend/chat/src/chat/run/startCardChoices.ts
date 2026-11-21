// The chat start card's "Model" and "Cost budget (USD)" (a benchmark start is set entirely in
// the UI). Pure: no React.
//
// Model: the card's "Run on" options carry only key and label; a device key is the server's `option_key`
// (`device:<device_id>:<profile>:<folder>`, backend workflow_runs/runtime_target/target.py), so the device target is
// read back from it and the work item dialog's model list is reused (runModelModel). The answer carries `model` next
// to `run_on` (WorkflowProposalDecisionRequest); the server refuses it (422) without a device location.
//
// Cost budget: the start answer carries it as `budget` (validated like the limits PUT, 422 "Invalid budget: …")
// and the server patches it onto the Work item before the run, for a new item too; the item's other limits stay and
// its stories inherit it. An existing item's stored budget prefills the field (GET …/limits).

import type { RuntimeTarget } from "../workflowRun/runtimeTargetModel";
import { costBudgetValue } from "../work/workItemLimitsModel";

const DEVICE_PREFIX = "device:";

/** The run target a "Run on" key names; a device key gives the device target, any other key its kind. */
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

/** The model to send with the answer: only for a device location, Automatic sends none. */
export function answerModel(runOn: string, model: string): string | undefined {
  const chosen = model.trim();
  return chosen && runOnTarget(runOn)?.kind === "device" ? chosen : undefined;
}

export type StartBudgetBody = { cost_usd: number };

/** The cost field as the answer's `budget`: null when empty (the item keeps what it has), else a positive amount. */
export function startBudget(draft: string): { budget: StartBudgetBody | null } | { error: string } {
  const value = costBudgetValue(draft);
  if ("error" in value) return value;
  return { budget: value.value === null ? null : { cost_usd: value.value } };
}

/** The server's budget refusal (422 "Invalid budget: …") in words at the cost field; null for other refusals. */
export function startBudgetError(message: string): string | null {
  const refused = /^Invalid budget:\s*(.*)$/.exec(message.trim());
  return refused ? `The server did not accept this budget${refused[1] ? ` (${refused[1].replace(/\.$/, "")})` : ""}. Enter a positive amount in USD.` : null;
}

/** The stored cost of GET …/limits (`{run_limits: {budget: {cost_usd}}}`); null when none. */
export function storedCost(raw: unknown): number | null {
  const limits = (raw as { run_limits?: { budget?: { cost_usd?: unknown } } } | null)?.run_limits;
  const cost = limits?.budget?.cost_usd;
  return typeof cost === "number" && Number.isFinite(cost) && cost > 0 ? cost : null;
}

/**
 * A refused start that concerns the model, in words at the Model field ('s two 422 sentences); null when it
 * belongs elsewhere (the card's general line).
 */
export function startModelError(message: string): string | null {
  if (message.startsWith("Choose one of your devices under Run on to pick a model")) {
    return "Pick one of your devices under Run on to choose a model, or keep Automatic.";
  }
  const refused = /^This model is not allowed here \((.*)\)\.?$/.exec(message);
  return refused ? `This model is not allowed on this device and route (${refused[1]}). Choose another or Automatic.` : null;
}
