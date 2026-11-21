import { buildChatSearch } from "./search";
import {
  SecretRebindRequiredError,
  parseSecretRebindRefusal,
} from "../secretRebind/secretRebindModel";
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import type { ThreadSummary } from "../../chatThreadTypes";

export function isObjectRecord(
  value: unknown,
): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function sanitizeOfficeTemplateKey(value: string) {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "office-template";
}

/** A read (GET without its own signal) gives up after this long, so a page never stays on "Loading…" forever. */
export const ADMIN_READ_TIMEOUT_MS = 30_000;

/** The words for a read that gave up or a server that is busy (no raw "Service Unavailable"). */
export function unavailableText(status: number | null): string {
  if (status === null) return `The server did not answer within ${ADMIN_READ_TIMEOUT_MS / 1000} seconds. Try again.`;
  return `The server is busy or restarting (${status}). Try again in a moment.`;
}

const isRead = (init?: RequestInit) => !init?.method || init.method.toUpperCase() === "GET";

export async function readJson<T>(
  input: RequestInfo,
  init?: RequestInit,
): Promise<T> {
  const normalizedInput = sanitizeAdminJsonRequestInput(input);
  // A read without its own signal ends after ADMIN_READ_TIMEOUT_MS with words the page shows, so a hung read
  // (the API's pool exhausted) never leaves a page on "Loading…".
  const timeout = isRead(init) && !init?.signal && typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
    ? AbortSignal.timeout(ADMIN_READ_TIMEOUT_MS) : undefined;
  let response: Response;
  try {
    response = await fetch(normalizedInput, {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
      ...(timeout ? { signal: timeout } : {}),
      ...init,
    });
  } catch (error) {
    if (timeout?.aborted) throw Object.assign(new Error(unavailableText(null)), { status: 0, code: "timeout" });
    throw error;
  }
  if (!response.ok) {
    let detail = [502, 503, 504].includes(response.status) ? unavailableText(response.status) : response.statusText;
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      // Ignore JSON parse failures and keep the status text.
    }
    const refusal = parseSecretRebindRefusal(response.status, payload);
    if (refusal) throw new SecretRebindRequiredError(refusal);
    const payloadDetail = (payload as { detail?: unknown } | null)?.detail;
    if (typeof payloadDetail === "string" && payloadDetail) detail = payloadDetail;
    // Typed refusals ({code, message, field}, e.g.) carry their text in `message`; nothing else
    // of the object is shown, and it is never stringified.
    else if (
      isObjectRecord(payloadDetail) &&
      typeof payloadDetail.message === "string" &&
      payloadDetail.message.trim()
    )
      detail = payloadDetail.message;
    // The HTTP status rides along (additive) so a caller can tell a missing route (404) from a refusal.
    // The fixed refusal code rides along too (`detail.code`, `detail.reason`, or the first of a validation list
    // `detail.errors: [{code, path}]`; a plain name only), so a caller can tell refusals apart without
    // matching message text.
    const firstError =
      isObjectRecord(payloadDetail) && Array.isArray(payloadDetail.errors) && isObjectRecord(payloadDetail.errors[0])
        ? payloadDetail.errors[0].code
        : undefined;
    const refusalCode = isObjectRecord(payloadDetail)
      ? [payloadDetail.code, payloadDetail.reason, firstError].find(
          (value): value is string => typeof value === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(value),
        ) ?? null
      : null;
    // A typed refusal's structured detail rides along as well (e.g. the references of a level still in use), for
    // pages that list them; it is never shown as raw text.
    throw Object.assign(new Error(detail || "Request failed"), {
      status: response.status,
      code: refusalCode,
      detail: isObjectRecord(payloadDetail) ? payloadDetail : undefined,
    });
  }
  return (await response.json()) as T;
}

function sanitizeAdminQueryParams(url: URL): string {
  const search = new URLSearchParams(url.search);
  let dirty = false;

  for (const key of Array.from(search.keys())) {
    const values = search.getAll(key);
    const filtered = values
      .map((value) => value.trim())
      .filter((value) => {
        if (value === "") return false;
        if (value.toLowerCase() === "undefined") return false;
        if (value.toLowerCase() === "null") return false;
        if (key === "limit") {
          const parsed = Number(value);
          return Number.isFinite(parsed) && parsed >= 1;
        }
        if (key === "offset") {
          const parsed = Number(value);
          return Number.isFinite(parsed) && parsed >= 0;
        }
        return true;
      });
    if (filtered.length === values.length) {
      continue;
    }
    dirty = true;
    search.delete(key);
    if (filtered.length === 0) {
      continue;
    }
    for (const value of filtered) {
      search.append(key, value);
    }
  }

  if (!dirty) {
    return url.toString();
  }
  url.search = search.toString();
  return `${url.pathname}${url.search}${url.hash}`;
}

function sanitizeAdminJsonRequestInput(input: RequestInfo): RequestInfo {
  if (typeof input === "string" || input instanceof URL) {
    input = typeof input === "string" ? input : input.toString();
  } else {
    return input;
  }
  if (!input.includes("?")) return input;
  try {
    const sanitized = sanitizeAdminQueryParams(new URL(input, window.location.origin));
    return sanitized;
  } catch {
    return input;
  }
}

export function threadHref(thread: ThreadSummary) {
  return buildChatSearch({ sessionId: thread.id });
}
