import { newStartsHeld, readHold, resumeBody, type Hold } from "../securityControls/securityControlsModel";
import { mainSessionOf, readCosts, type CostGroup, type CostReport } from "./costsModel";
import { readSeatUsage, type SeatUsageReport } from "./seatUsageModel";
import { readOperations } from "./operationsRead";
import { readStopHistory, readStopPreview, stopResultText, type StopPreview, type StopRecord } from "./operationsEmergencyStop";
import { type OperationsLive } from "./operationsTypes";

export type OpsRefusal = Error & { status: number; code: string };

export function isOpsRefusal(error: unknown): error is OpsRefusal {
  return error instanceof Error && error.name === "OpsRefusal";
}

export type OpsOptions = { renew?: () => Promise<unknown> };

async function send(path: string, init: RequestInit | undefined): Promise<Response> {
  return fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
  });
}

async function call(path: string, init?: RequestInit, options: OpsOptions = {}): Promise<unknown> {
  let response = await send(path, init);
  if (response.status === 401 && options.renew) {
    await options.renew();
    response = await send(path, init);
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
    const code = detail && typeof detail === "object" && typeof (detail as { code?: unknown }).code === "string"
      ? (detail as { code: string }).code : "";
    const message = typeof detail === "string" ? detail
      : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
        ? (detail as { message: string }).message : "";
    throw Object.assign(new Error(message || `The request failed (${response.status}).`), { name: "OpsRefusal", status: response.status, code });
  }
  return payload;
}

export type LiveScope = { workspaceId: string; useWorkspaceRoute: boolean };
export type LiveResult = { live: OperationsLive; viaWorkspace: boolean };

// Admin route first; on 403 the current Workspace's route, and the caller remembers that.
export async function loadOperationsLive(scope: LiveScope, options: OpsOptions = {}): Promise<LiveResult> {
  const workspaceRoute = async () => {
    if (!scope.workspaceId) throw Object.assign(new Error("Choose a Workspace to see what runs in it."), { name: "OpsRefusal", status: 400, code: "workspace_required" });
    return { live: readOperations(await call(`/api/v1/workspaces/${encodeURIComponent(scope.workspaceId)}/operations/live`, undefined, options)), viaWorkspace: true };
  };
  if (scope.useWorkspaceRoute) return workspaceRoute();
  const query = scope.workspaceId ? `?workspace_id=${encodeURIComponent(scope.workspaceId)}` : "";
  try {
    return { live: readOperations(await call(`/api/v1/admin/operations/live${query}`, undefined, options)), viaWorkspace: false };
  } catch (error) {
    if (isOpsRefusal(error) && error.status === 403) return workspaceRoute();
    throw error;
  }
}

export type OfferedAction = { key: string; label: string; input: { name: string; kind: string; label: string } | null };

export async function loadRunActions(runId: string, options: OpsOptions = {}): Promise<OfferedAction[]> {
  const body = await call(`/api/v1/workflow-runs/${encodeURIComponent(runId)}`, undefined, options) as { run?: { actions?: unknown } } | null;
  const actions = Array.isArray(body?.run?.actions) ? body.run.actions : [];
  return actions
    .filter((action): action is { key: string; label?: unknown; input?: unknown } =>
      Boolean(action) && typeof (action as { key?: unknown }).key === "string")
    .map((action) => {
      const input = action.input && typeof action.input === "object" ? action.input as Record<string, unknown> : null;
      return {
        key: action.key,
        label: typeof action.label === "string" ? action.label : action.key,
        input: input && typeof input.name === "string"
          ? { name: input.name, kind: String(input.kind ?? ""), label: String(input.label ?? "") } : null,
      };
    });
}

export async function abortRun(runId: string, reason: string, options: OpsOptions = {}): Promise<void> {
  const body: Record<string, unknown> = { action: "abort" };
  if (reason.trim()) body.reason = reason.trim();
  await call(`/api/v1/workflow-runs/${encodeURIComponent(runId)}/actions`, { method: "POST", body: JSON.stringify(body) }, options);
}

export async function stopDeviceJob(jobId: string, options: OpsOptions = {}): Promise<void> {
  await call(`/api/v1/device-jobs/${encodeURIComponent(jobId)}/stop`, { method: "POST" }, options);
}

export async function acknowledgeOpsProblem(key: string, options: OpsOptions = {}): Promise<void> {
  await call(`/api/v1/admin/problems/${encodeURIComponent(key)}/acknowledge`, { method: "POST" }, options);
}

const stopQuery = (workspaceId: string) => (workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "");

export async function loadStopPreview(workspaceId: string): Promise<StopPreview> {
  return readStopPreview(await call(`/api/v1/admin/operations/emergency-stop/preview${stopQuery(workspaceId)}`));
}

export async function emergencyStop(workspaceId: string, reason: string): Promise<string> {
  const body: Record<string, unknown> = { reason };
  if (workspaceId) body.workspace_id = workspaceId;
  return stopResultText(await call("/api/v1/admin/operations/emergency-stop", { method: "POST", body: JSON.stringify(body) }));
}

export async function loadNewStartsHeld(workspaceId: string): Promise<{ held: boolean; hold: Hold | null }> {
  const preview = await call(`/api/v1/admin/operations/emergency-stop/preview${stopQuery(workspaceId)}`);
  return { held: newStartsHeld(preview), hold: readHold(preview) };
}

export async function resumeNewStarts(workspaceId: string, reason: string): Promise<unknown> {
  return call("/api/v1/admin/operations/emergency-stop/resume", { method: "POST", body: JSON.stringify(resumeBody(workspaceId, reason)) });
}

export async function loadStopHistory(workspaceId: string): Promise<StopRecord[]> {
  return readStopHistory(await call(`/api/v1/admin/operations/emergency-stop/history${stopQuery(workspaceId)}`));
}

export async function loadCosts(query: { workspaceId: string; days: number; group: CostGroup }): Promise<CostReport> {
  const params = new URLSearchParams({ days: String(query.days), group: query.group });
  if (query.workspaceId) params.set("workspace_id", query.workspaceId);
  return readCosts(await call(`/api/v1/admin/operations/costs?${params.toString()}`), query.group);
}

export async function loadRunSession(runId: string): Promise<string> {
  return mainSessionOf(await call(`/api/v1/workflow-runs/${encodeURIComponent(runId)}`));
}

// A refusal keeps status and code so the page can tell a missing route (404 without a code) from a refused Workspace.
export async function loadSeatUsage(query: { workspaceId: string; days: number }): Promise<SeatUsageReport> {
  const params = new URLSearchParams({ days: String(query.days) });
  if (query.workspaceId) params.set("workspace_id", query.workspaceId);
  return readSeatUsage(await call(`/api/v1/admin/operations/seat-usage?${params.toString()}`));
}
