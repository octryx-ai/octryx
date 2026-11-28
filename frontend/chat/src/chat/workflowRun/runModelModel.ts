// The server takes a model only on a device target; auto, the Server and a terminal drop it.
// Codex on the person's own subscription has no server list, so the four models below are offered.

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

const profileOf = (target: Extract<RuntimeTarget, { kind: "device" }>) => (target.profile === "seat" ? "seat" : "governed");

export function modelSource(engine: string, target: RuntimeTarget | null): ModelSource {
  if (!target || target.kind !== "device") {
    return { kind: "none", reason: "Pick one of your devices under Run on to choose a model; elsewhere the run uses its own default." };
  }
  const profile = profileOf(target);
  if (engine === CODEX && profile === "seat") return { kind: "codex_seat" };
  return { kind: "server", profile, deviceId: target.device_id };
}

export type ModelOption = { value: string; label: string };

export function modelOptions(source: ModelSource, rows: DeviceModels | null): ModelOption[] {
  const automatic = { value: AUTOMATIC, label: "Automatic" };
  if (source.kind === "codex_seat") {
    return [automatic, ...CODEX_SEAT_MODELS.map((id) => ({ value: id, label: readableModelName(id) }))];
  }
  if (source.kind === "server" && rows) return [automatic, ...rows.models.map((row) => ({ value: row.id, label: row.label }))];
  return [automatic];
}

export function engineRouteLine(engine: string, target: RuntimeTarget | null): string | null {
  if (!target || target.kind !== "device") return null;
  return `${engineLabel(engine)} · ${profileOf(target) === "seat" ? ROUTE_SEAT : ROUTE_GOVERNED}`;
}

export const keptChoice = (current: string, options: readonly ModelOption[]) =>
  options.some((option) => option.value === current) ? current : AUTOMATIC;

export function targetWithModel(target: RuntimeTarget | null, model: string): RuntimeTarget | null {
  if (!target || target.kind !== "device") return target;
  const { model: _old, ...rest } = target;
  return model ? { ...rest, model } : rest;
}

const MODEL_REFUSALS: Record<string, string> = {
  device_model_not_allowed: "This model is not allowed for this route in the Workspace. Choose another or Automatic.",
  runtime_profile_unavailable: "This device does not offer this route. Choose another device or route under Run on.",
  runtime_target_invalid: "The run location is not valid any more. Choose it again under Run on.",
};

export function modelStartError(error: unknown): string | null {
  const code = (error as { code?: string | null } | null)?.code ?? "";
  return MODEL_REFUSALS[code] ?? null;
}

export function modelListError(error: unknown): string {
  const { status } = (error ?? {}) as { status?: number };
  if (status === 404) return "This device is not yours or no longer exists; only Automatic is offered.";
  if (status === 400) return "This route is not known for a device; only Automatic is offered.";
  return "The models could not be loaded; only Automatic is offered.";
}
