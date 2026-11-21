// Chat API base paths and the JSON request helper with refusal detail/code handling.

export const CHAT_API_BASE = "/chat/api";
export const CHAT_API_V1_BASE = `${CHAT_API_BASE}/v1`;

export function chatApiPath(path: string) {
  if (!path) {
    return CHAT_API_BASE;
  }
  return `${CHAT_API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}
// A refusal detail is plain text or a typed record (e.g. an inactive agent) whose
// operator text is its `message`; anything else falls back to the status text.
export function responseDetailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  const message = detail && typeof detail === "object" ? (detail as { message?: unknown }).message : null;
  return typeof message === "string" ? message : "";
}

/** The refusal code of a structured `detail` ({code, message}), else null. */
export function responseDetailCode(detail: unknown): string | null {
  const code = detail && typeof detail === "object" ? (detail as { code?: unknown }).code : null;
  return typeof code === "string" && code ? code : null;
}

export async function readJson<T>(
  input: RequestInfo,
  init?: RequestInit,
): Promise<T> {
  const requestStartedAt = performance.now();
  const response = await fetch(input, {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  const responseReceivedAt = performance.now();
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | null = null;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = responseDetailText(payload.detail) || detail;
      code = responseDetailCode(payload.detail);
    } catch {
      // Ignore JSON parse failures and keep the status text.
    }
    // The HTTP status rides along (additive), so a caller can put a refusal into words (a 409 on "always").
    // So does the refusal's code, when the server sends one (`detail.code`, e.g. approval_already_resolved).
    throw Object.assign(new Error(detail || "Request failed"), { status: response.status, code });
  }
  const payload = (await response.json()) as T;
  if (isChatPerformanceDebugEnabled()) {
    logChatRequestTiming(input, response, requestStartedAt, responseReceivedAt);
  }
  return payload;
}

function isChatPerformanceDebugEnabled() {
  try {
    return window.localStorage.getItem("octryx-chat-debug-performance") === "1";
  } catch {
    return false;
  }
}

function logChatRequestTiming(
  input: RequestInfo,
  response: Response,
  requestStartedAt: number,
  responseReceivedAt: number,
) {
  const requestCompletedAt = performance.now();
  const url = typeof input === "string" ? input : input.url;
  if (!url.includes(`${CHAT_API_BASE}/bootstrap`)) {
    return;
  }
  console.info("chat.bootstrap.client_timing", {
    url,
    fetch_ms: Math.round(responseReceivedAt - requestStartedAt),
    json_ms: Math.round(requestCompletedAt - responseReceivedAt),
    total_ms: Math.round(requestCompletedAt - requestStartedAt),
    kind: response.headers.get("X-Chat-Bootstrap-Kind") || "",
    server_elapsed_ms:
      response.headers.get("X-Chat-Bootstrap-Elapsed-Ms") || "",
    payload_bytes: response.headers.get("X-Chat-Bootstrap-Payload-Bytes") || "",
  });
}
