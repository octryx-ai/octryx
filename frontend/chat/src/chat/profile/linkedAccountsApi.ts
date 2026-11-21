// Linked accounts (backend api/routes/linked_accounts.py). `userId` is a user id or "me". A refusal answers
// `{state, reason, message}`; the reason and message ride along on the thrown error.
import type { LinkedAccountRequestError } from "./linkedAccountsModel";

async function accountJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    ...init,
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const body = (payload ?? {}) as { reason?: unknown; message?: unknown };
    const code = typeof body.reason === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(body.reason) ? body.reason : null;
    const detail = typeof body.message === "string" ? body.message : null;
    const error = new Error(code ?? (response.statusText || "Request failed")) as LinkedAccountRequestError;
    throw Object.assign(error, { status: response.status, code, detail });
  }
  return payload as T;
}

const base = (userId: string) => `/api/v1/users/${encodeURIComponent(userId)}/linked-accounts`;
const platformPath = (userId: string, platform: string) => `${base(userId)}/${encodeURIComponent(platform)}`;

export function loadLinkedAccounts(userId: string): Promise<unknown> {
  return accountJson<unknown>(base(userId));
}

export function saveLinkedAccount(userId: string, platform: string, body: { identifier: string } | { email: string; project_id: string }) {
  return accountJson<unknown>(platformPath(userId, platform), { method: "PUT", body: JSON.stringify(body) });
}

export function verifyLinkedAccount(userId: string, platform: string, projectId: string) {
  return accountJson<unknown>(`${platformPath(userId, platform)}/verify`, {
    method: "POST",
    body: JSON.stringify({ project_id: projectId }),
  });
}

export function removeLinkedAccount(userId: string, platform: string) {
  return accountJson<unknown>(platformPath(userId, platform), { method: "DELETE" });
}
