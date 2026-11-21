// "Model" in the run start box (Work item › Start workflow). Pure: no React.
//
// The server takes a model only on a device target (`runtime_target.model`, backend workflow_runs/runtime_target/
// target.py: `auto`, the Server and a terminal drop it) and checks it against the device's profile
// (services/devices/device_models.check_device_model):
// - Claude Code, or Codex on the company route: the rows of GET …/agent-gateway/device-runs/models?profile=…
//   (seat: the Workspace's seat models; governed: the Workspace's company models);
// - Codex on the person's own subscription: the server has no list (only the tiers luna < terra < sol < astra in
//   octryx/model_guard), so the four Codex models below are offered.
// "Automatic" sends no model: the device's default.

import { CODEX, engineLabel } from "../engines/engineModel";
import { readableModelName } from "../devices/modelNames";
import type { DeviceModels } from "../devices/deviceModelsModel";
import { ROUTE_GOVERNED, ROUTE_SEAT } from "../../mobile/engineSeatModel";
import type { RuntimeTarget } from "./runtimeTargetModel";

export const CODEX_SEAT_MODELS = ["gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna", "gpt-6-astra"] as const;
export const AUTOMATIC = "";

export type ModelSource =
  | { kind: "server"; profile: string; deviceId: string }
  | { kind: "codex_seat" }
  | { kind: "none"; reason: string };

/** A device target's profile; empty means the server's choice, governed when the device offers it. */
const profileOf = (target: Extract<RuntimeTarget, { kind: "device" }>) => (target.profile === "seat" ? "seat" : "governed");

/** Where the model list comes from for this engine and run location. */
export function modelSource(engine: string, target: RuntimeTarget | null): ModelSource {
  if (!target || target.kind !== "device") {
    return { kind: "none", reason: "Pick one of your devices under Run on to choose a model; elsewhere the run uses its own default." };
  }
  const profile = profileOf(target);
  if (engine === CODEX && profile === "seat") return { kind: "codex_seat" };
  return { kind: "server", profile, deviceId: target.device_id };
}

export type ModelOption = { value: string; label: string };

/** "Automatic" first, then the models of the source. */
export function modelOptions(source: ModelSource, rows: DeviceModels | null): ModelOption[] {
  const automatic = { value: AUTOMATIC, label: "Automatic" };
  if (source.kind === "codex_seat") {
    return [automatic, ...CODEX_SEAT_MODELS.map((id) => ({ value: id, label: readableModelName(id) }))];
  }
  if (source.kind === "server" && rows) return [automatic, ...rows.models.map((row) => ({ value: row.id, label: row.label }))];
  return [automatic];
}

/** The line below the select, in the run line's words: "Codex · Own subscription". */
export function engineRouteLine(engine: string, target: RuntimeTarget | null): string | null {
  if (!target || target.kind !== "device") return null;
  return `${engineLabel(engine)} · ${profileOf(target) === "seat" ? ROUTE_SEAT : ROUTE_GOVERNED}`;
}

/** The choice to keep when the options change: the current one while it is offered, else Automatic. */
export const keptChoice = (current: string, options: readonly ModelOption[]) =>
  options.some((option) => option.value === current) ? current : AUTOMATIC;

/** The target sent at start: a device target with the chosen model; Automatic sends none. */
export function targetWithModel(target: RuntimeTarget | null, model: string): RuntimeTarget | null {
  if (!target || target.kind !== "device") return target;
  const { model: _old, ...rest } = target;
  return model ? { ...rest, model } : rest;
}

// The start refusals that concern the model or the route (backend devices/chat_turn REFUSAL_MESSAGES and target.py).
const MODEL_REFUSALS: Record<string, string> = {
  device_model_not_allowed: "This model is not allowed for this route in the Workspace. Choose another or Automatic.",
  runtime_profile_unavailable: "This device does not offer this route. Choose another device or route under Run on.",
  runtime_target_invalid: "The run location is not valid any more. Choose it again under Run on.",
};

/** A start refusal in words at the Model field; null when it belongs to another field. */
export function modelStartError(error: unknown): string | null {
  const code = (error as { code?: string | null } | null)?.code ?? "";
  return MODEL_REFUSALS[code] ?? null;
}

/** The note when the server list could not be read. */
export function modelListError(error: unknown): string {
  const { status } = (error ?? {}) as { status?: number };
  if (status === 404) return "This device is not yours or no longer exists; only Automatic is offered.";
  if (status === 400) return "This route is not known for a device; only Automatic is offered.";
  return "The models could not be loaded; only Automatic is offered.";
}
