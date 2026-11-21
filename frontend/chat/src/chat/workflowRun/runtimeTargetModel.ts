// Where a workflow run executes: the Server, an octryx-claude terminal, or one of
// the requester's devices with one of its allowed folders. The server lists the choices and validates them; this
// module only reads them and turns the run's target into the card's text and the composer's target.

import { WORKFLOW_RUNS_PATH } from "./workflowRunRequests";
import type { ExecutionTarget } from "../devices/executionTarget";

// `auto` (the requester's device with a seat first, governed when a rule or the allowance says so) is resolved by
// the server at start; the run then carries the concrete target with `resolved_from: "auto"` and a `reason`.
export type RuntimeTarget =
  | { kind: "auto" }
  | { kind: "server" }
  | { kind: "terminal" }
  | { kind: "device"; device_id: string; folder: string; profile: string; model?: string };

// `help`: one sentence on what the choice does (the server sends it for "Automatic"), shown below the select.
export type RuntimeTargetOption = { key: string; label: string; target: RuntimeTarget; online?: boolean; help?: string };

export type RunRuntimeTarget = {
  kind: string;
  label: string;
  device_id?: string;
  device_name?: string;
  folder?: string;
  profile?: string;
  model?: string;
  online?: boolean;
  resolved_from?: string;
  reason?: string;
};

export type RuntimeTargetChoices = { options: RuntimeTargetOption[]; default: string };

export function runtimeTargetsPath(projectId: string | null | undefined): string {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return `${WORKFLOW_RUNS_PATH}/runtime-targets${query}`;
}

const isTarget = (value: unknown): value is RuntimeTarget => {
  if (!value || typeof value !== "object") return false;
  const target = value as Record<string, unknown>;
  if (target.kind === "auto" || target.kind === "server" || target.kind === "terminal") return true;
  return target.kind === "device" && typeof target.device_id === "string" && typeof target.folder === "string";
};

export function readRuntimeTargetChoices(raw: unknown): RuntimeTargetChoices {
  const payload = (raw ?? {}) as { options?: unknown; default?: unknown };
  const options = Array.isArray(payload.options)
    ? payload.options.filter((item): item is RuntimeTargetOption => {
        const option = item as Partial<RuntimeTargetOption> | null;
        return !!option && typeof option.key === "string" && typeof option.label === "string" && isTarget(option.target);
      })
    : [];
  const fallback = options[0]?.key ?? "server";
  const chosen = typeof payload.default === "string" && options.some((option) => option.key === payload.default)
    ? payload.default
    : fallback;
  return { options, default: chosen };
}

/** The card's "Runs on …" fact; a device that is offline says so. */
export function runtimeTargetText(target: RunRuntimeTarget | null | undefined): string | null {
  if (!target) return null;
  if (target.kind !== "device") return `Runs on ${target.label}`;
  return `Runs on ${target.label}${target.online === false ? " · offline" : ""}`;
}

/**
 * Why the run runs where it does: the server's reason when it chose the target ("auto"), e.g. "seat on Studio Mac";
 * "Chosen when started" when the person chose it in the start dialog.
 */
export function runtimeTargetReason(target: RunRuntimeTarget | null | undefined): string | null {
  if (!target) return null;
  if (target.resolved_from !== "auto") return "Chosen when started";
  const reason = typeof target.reason === "string" ? target.reason.trim() : "";
  return reason ? `Chosen automatically: ${reason}` : "Chosen automatically";
}

/** A device run's thread sends from that device and folder (the server refuses anything else). */
export function composerTargetOf(target: RunRuntimeTarget | null | undefined): ExecutionTarget | null {
  if (!target || target.kind !== "device" || !target.device_id || !target.folder) return null;
  return { kind: "device", deviceId: target.device_id, folder: target.folder,
    profile: target.profile === "seat" ? "seat" : "governed", model: target.model ?? "" };
}
