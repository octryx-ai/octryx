// Transport for the admin private-host egress allowlist (#S6). The generic admin
// readJson drops a structured 400/409 detail, so these calls read the refusal body
// themselves and hand back only fixed codes. Same-origin fetch carries the Origin
// header the panel CSRF boundary (backend/app/middleware/security/panel_csrf.py) checks.
import {
  draftsFromPayload,
  loadFailureCode,
  parsePrivateHostRefusal,
  type PrivateHostDraft,
  type PrivateHostRefusal,
} from "./privateHostAllowlistModel";

export const PRIVATE_HOSTS_PATH = "/admin/chat/api/panel/egress/private-hosts";

export type LoadOutcome =
  | { ok: true; drafts: PrivateHostDraft[] }
  | { ok: false; code: string };

export type SaveOutcome =
  | { ok: true; entries: string[] }
  | { ok: false; refusal: PrivateHostRefusal };

async function jsonOrNull(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function loadPrivateHostAllowlist(): Promise<LoadOutcome> {
  let response: Response;
  try {
    response = await fetch(PRIVATE_HOSTS_PATH, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
  } catch {
    return { ok: false, code: "request_failed" };
  }
  const payload = await jsonOrNull(response);
  if (!response.ok) {
    return { ok: false, code: loadFailureCode(response.status, payload) };
  }
  return { ok: true, drafts: draftsFromPayload(payload) };
}

export async function savePrivateHostEntries(
  connection: string,
  entries: string[],
): Promise<SaveOutcome> {
  let response: Response;
  try {
    response = await fetch(
      `${PRIVATE_HOSTS_PATH}/${encodeURIComponent(connection)}`,
      {
        method: "PUT",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ entries }),
      },
    );
  } catch {
    return {
      ok: false,
      refusal: { reason: "request_failed", entryIndex: null },
    };
  }
  const payload = await jsonOrNull(response);
  if (!response.ok) {
    const refusal = parsePrivateHostRefusal(response.status, payload) ?? {
      reason: `http_${response.status}`,
      entryIndex: null,
    };
    return { ok: false, refusal };
  }
  const saved = (payload as { entries?: unknown } | null)?.entries;
  return {
    ok: true,
    entries: Array.isArray(saved)
      ? saved.filter((item): item is string => typeof item === "string")
      : entries,
  };
}
