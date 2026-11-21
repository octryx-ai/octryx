// Request plumbing of the Workspace Knowledge client: the refused-request error, fetch wrapper and URL builders.

// A refused request: its sentence for people, the HTTP status and the Knowledge state (X-Knowledge-State) when the
// server named one.
export class KnowledgeRequestError extends Error {
  readonly status: number;
  readonly state: string | null;

  constructor(message: string, status: number, state: string | null) {
    super(message);
    this.name = "KnowledgeRequestError";
    this.status = status;
    this.state = state;
  }
}

export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      // `detail` is a string or the coded object {code, message} (one sentence for people); never "[object Object]".
      const raw = ((await response.json()) as { detail?: unknown }).detail;
      const message = typeof raw === "string" ? raw
        : raw && typeof raw === "object" && typeof (raw as { message?: unknown }).message === "string"
          ? (raw as { message: string }).message : "";
      detail = message || detail;
    } catch {
      // Keep the status text.
    }
    throw new KnowledgeRequestError(detail || `Request failed (${response.status})`, response.status,
      response.headers?.get?.("X-Knowledge-State") || null);
  }
  return (await response.json()) as T;
}

export function knowledgeBase(workspaceId: string): string {
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/knowledge`;
}

// The server's bounds of the source list (ledger/queries.py DEFAULT_SOURCE_LIMIT, MAX_SOURCE_LIMIT).
export const DEFAULT_SOURCE_LIMIT = 50;
export const MAX_SOURCE_LIMIT = 200;

// Authorized, digest-verified original of one revision; PDF opens inline, other types download.
export function originalContentUrl(workspaceId: string, sourceId: string, revisionId: string): string {
  return `${knowledgeBase(workspaceId)}/sources/${encodeURIComponent(sourceId)}/revisions/${encodeURIComponent(revisionId)}/original`;
}

export function splitProducts(raw: string): string[] {
  return raw
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

export function webSearchBase(workspaceId: string): string {
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/web-search`;
}
