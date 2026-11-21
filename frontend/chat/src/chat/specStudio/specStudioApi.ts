import { readJson } from "../chatApiClient";
import type { StudioPayload } from "./specStudioModel";

// The Studio's calls. Every product owner change is saved at once (one PATCH, audited on the run); the page shows
// "Saving…", "Saved" or the refusal in words with Retry (nothing is lost silently).

export type StudioChange = Record<string, unknown> & { op: string };

const base = (runId: string) => `/api/v1/workflow-runs/${encodeURIComponent(runId)}/spec-studio`;

export function loadStudio(runId: string): Promise<StudioPayload> {
  return readJson<StudioPayload>(base(runId));
}

export function saveChange(runId: string, change: StudioChange): Promise<StudioPayload> {
  return readJson<StudioPayload>(base(runId), { method: "PATCH", body: JSON.stringify(change) });
}

export function approveStudio(runId: string): Promise<StudioPayload> {
  return readJson<StudioPayload>(`${base(runId)}/approve`, { method: "POST", body: "{}" });
}

export function reviseStudio(runId: string): Promise<StudioPayload> {
  return readJson<StudioPayload>(`${base(runId)}/revise`, { method: "POST", body: "{}" });
}

export function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "The change could not be saved.";
}
