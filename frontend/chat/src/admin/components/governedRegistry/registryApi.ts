// Shared transport of the governed registry APIs (prompt catalog): same-origin JSON, every non-2xx
// response becomes one coded RegistryApiError. Refusals come back as coded errors ({code, ...facts});
// the client keeps the code and the facts and never turns a refusal into a success or a generic message.

export class RegistryApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly facts: Record<string, unknown>;

  constructor(status: number, code: string, facts: Record<string, unknown>, message: string) {
    super(message);
    this.name = "RegistryApiError";
    this.status = status;
    this.code = code;
    this.facts = facts;
  }
}

export type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

// FastAPI renders refusals as {detail: {code, ...facts}}, request-shape errors as {detail: [...]},
// and plain HTTP errors as {detail: "text"}. Each becomes one coded error.
export function refusalFromPayload(status: number, payload: unknown): RegistryApiError {
  const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : undefined;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && typeof (detail as { code?: unknown }).code === "string") {
    const { code, ...facts } = detail as { code: string } & Record<string, unknown>;
    return new RegistryApiError(status, code, facts, code);
  }
  if (Array.isArray(detail)) {
    return new RegistryApiError(status, "request_invalid", { errors: detail }, "request_invalid");
  }
  if (typeof detail === "string" && detail) {
    return new RegistryApiError(status, `http_${status}`, {}, detail);
  }
  return new RegistryApiError(status, `http_${status}`, {}, `Request failed (${status})`);
}

export function createRegistryTransport(fetchFn: FetchFn = (input, init) => fetch(input, init)) {
  async function send(url: string, init?: RequestInit): Promise<Response> {
    const response = await fetchFn(url, {
      credentials: "same-origin",
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        // No JSON body: the status alone is the refusal.
      }
      throw refusalFromPayload(response.status, payload);
    }
    return response;
  }

  async function json<T>(url: string, init?: RequestInit): Promise<T> {
    return (await (await send(url, init)).json()) as T;
  }

  const post = <T>(url: string, body: unknown = {}) => json<T>(url, { method: "POST", body: JSON.stringify(body) });
  return { send, json, post };
}
