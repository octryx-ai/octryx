import { readJson } from "../../admin/utils/adminPanelHelpers";
import { transcriptFilterQuery, type TranscriptFilter } from "./transcriptModel";

// Full session transcripts (backend); answers are read by transcriptModel.

const settingsPath = (projectId: string) =>
  `/api/v1/workspaces/${encodeURIComponent(projectId)}/agent-gateway/session-transcripts`;

export function loadTranscriptSettings(projectId: string): Promise<unknown> {
  return readJson<unknown>(settingsPath(projectId));
}

/** Saves a partial change. Keeps a refusal's body: a 422 names the refused field and the card shows it there. */
export async function saveTranscriptSettings(projectId: string, body: Record<string, unknown>): Promise<{ ok: boolean; status: number; body: unknown }> {
  const response = await fetch(settingsPath(projectId), {
    method: "PUT",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // An answer without JSON keeps its status only.
  }
  return { ok: response.ok, status: response.status, body: payload };
}

export function listTranscripts(projectId: string, filter: TranscriptFilter): Promise<unknown> {
  return readJson<unknown>(`/api/v1/workspaces/${encodeURIComponent(projectId)}/session-transcripts?${transcriptFilterQuery(filter)}`);
}

/** One page of one stream. Every call writes an audit row on the server, so the view asks only on demand. */
export function loadTranscriptPage(sessionId: string, stream: string, fromLine: number, limit: number): Promise<unknown> {
  const params = new URLSearchParams({ stream, from_line: String(fromLine), limit: String(limit) });
  return readJson<unknown>(`/api/v1/session-transcripts/${encodeURIComponent(sessionId)}?${params.toString()}`);
}
