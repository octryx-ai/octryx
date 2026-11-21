import { knowledgeBase } from "../../../admin/components/workspaceKnowledge/workspaceKnowledgeRequest";
import type { DocumentDiff, DocumentView } from "./documentViewModel";
import { originalErrorText } from "./documentViewModel";

// The original routes answer refusals as {detail: {code, detail}}; the shared request() only reads string
// details, so these two calls read the code and turn it into the page's sentence.

export type Loaded<T> = { ok: true; data: T } | { ok: false; code: string | null; message: string };

async function readCoded<T>(url: string): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
  } catch {
    return { ok: false, code: null, message: "The original could not be loaded. Try again." };
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok) return { ok: true, data: payload as T };
  const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
  const code = detail && typeof detail === "object" && typeof (detail as { code?: unknown }).code === "string"
    ? String((detail as { code: string }).code) : null;
  const text = typeof detail === "string" ? detail : null;
  return { ok: false, code, message: originalErrorText(code, text ?? undefined) };
}

const sourcePath = (workspaceId: string, sourceId: string) =>
  `${knowledgeBase(workspaceId)}/sources/${encodeURIComponent(sourceId)}`;

export function loadRevisionView(workspaceId: string, sourceId: string, revisionId: string): Promise<Loaded<DocumentView>> {
  return readCoded<DocumentView>(`${sourcePath(workspaceId, sourceId)}/revisions/${encodeURIComponent(revisionId)}/view`);
}

export function loadRevisionDiff(workspaceId: string, sourceId: string, fromId: string, toId: string): Promise<Loaded<DocumentDiff>> {
  const query = `from_revision_id=${encodeURIComponent(fromId)}&to_revision_id=${encodeURIComponent(toId)}`;
  return readCoded<DocumentDiff>(`${sourcePath(workspaceId, sourceId)}/diff?${query}`);
}
