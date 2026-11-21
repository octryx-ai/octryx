import { readJson } from "../../utils/adminPanelHelpers";
import { POLICY_ENGINE_PATH } from "./policyEngineApi";

// Content detectors admin API (backend `api/routes/policy_engine_detectors.py`). Writes keep the 422
// `issues` on the error (readJson drops them) so the drawer can show them inline.

const JSON_HEADERS = { Accept: "application/json", "Content-Type": "application/json" };

async function send(method: string, path: string, body: unknown, headers: Record<string, string> = {}): Promise<unknown> {
  const response = await fetch(`${POLICY_ENGINE_PATH}${path}`, {
    method, credentials: "same-origin", body: JSON.stringify(body), headers: { ...JSON_HEADERS, ...headers },
  });
  let payload: unknown = null;
  try { payload = await response.json(); } catch { /* no body */ }
  if (response.ok) return payload;
  const detail = (payload as { detail?: unknown } | null)?.detail;
  const record = typeof detail === "object" && detail !== null ? detail as Record<string, unknown> : {};
  throw Object.assign(new Error(typeof detail === "string" ? detail : response.statusText || "Request failed"), {
    status: response.status,
    code: typeof record.code === "string" ? record.code : null,
    issues: Array.isArray(record.issues) ? record.issues : [],
  });
}

export const loadDetectorCatalog = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/content-detectors`);

/** The live test of an unsaved definition; the text is answered and dropped, never stored or logged. */
export const previewDetectors = (body: unknown) => send("POST", "/content-detectors/preview", body);

/** Replace the custom detectors and categories of the draft; `etag` is the digest of `version` as the page saw it. */
export const saveDetectors = (version: number, body: unknown, etag: string) =>
  send("PUT", `/policy-sets/${version}/detectors`, body, { "If-Match": etag });
