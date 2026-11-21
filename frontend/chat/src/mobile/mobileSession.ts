// Octryx Mobile's session and pairing requests. The phone holds its own credential cookie (`octryx_mobile`, only sent to /api/v1/mobile);
// POST /api/v1/mobile/session turns it into a five-minute access cookie that every other API accepts. A 401 from
// any API renews the session once and retries; a refused session means the phone is signed out.

// `detail`: the server's own sentence when it sends one as a string (e.g. "Choose the repository the run works in").
export type MobileError = Error & { status: number; code: string | null; detail?: string | null };

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    // A refusal's code: `reason` (mobile routes) or `detail.code` (the platform's other routes, e.g. run actions).
    const body = payload as { reason?: unknown; detail?: { code?: unknown } | string } | null;
    const reason = body?.reason ?? (body?.detail && typeof body.detail === "object" ? body.detail.code : undefined);
    const code =
      typeof reason === "string" && CODE.test(reason) ? reason : null;
    const detail = typeof body?.detail === "string" ? body.detail.slice(0, 500) : null;
    throw Object.assign(
      new Error(code ?? `request_failed_${response.status}`),
      { status: response.status, code, detail },
    );
  }
  return payload as T;
}

export type PhoneSession = {
  user: { id: string; name: string };
  device: {
    id: string;
    name: string;
    login_expires_at: string;
    this_device: boolean;
  };
  access_expires_in: number;
};

let current: Promise<PhoneSession> | null = null;
const signedOutListeners = new Set<() => void>();

export function onSignedOut(listener: () => void): () => void {
  signedOutListeners.add(listener);
  return () => signedOutListeners.delete(listener);
}

/** A fresh access cookie from the phone credential (one request at a time). */
export function startSession(): Promise<PhoneSession> {
  current ??= request<PhoneSession>("/api/v1/mobile/session", {
    method: "POST",
  }).finally(() => {
    current = null;
  });
  return current;
}

/** Any authenticated API; a 401 renews the session once, a refused session signs the phone out. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await request<T>(path, init);
  } catch (error) {
    if ((error as MobileError).status !== 401) throw error;
    try {
      await startSession();
    } catch (refused) {
      signedOutListeners.forEach((listener) => listener());
      throw refused;
    }
    return request<T>(path, init);
  }
}

// --- pairing (no login yet) ------------------------------------------------------------------------------------

export type Scan = {
  pairing_id: string;
  scan_secret: string;
  match_number: string;
  expires_at: string;
};
export type PairingStatus =
  | { state: "waiting"; match_number: string }
  | { state: "confirmed"; claim: string };

export const scanCode = (code: string) =>
  request<Scan>("/api/v1/mobile/pairings/scan", {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const pairingStatus = (pairingId: string, scanSecret: string) =>
  request<PairingStatus>(
    `/api/v1/mobile/pairings/${encodeURIComponent(pairingId)}/status`,
    { method: "POST", body: JSON.stringify({ scan_secret: scanSecret }) },
  );

export const claimPhone = (claim: string) =>
  request<unknown>("/api/v1/mobile/claim", {
    method: "POST",
    body: JSON.stringify({ claim }),
  });

export const signOutPhone = () =>
  request<unknown>("/api/v1/mobile/logout", { method: "POST" });
