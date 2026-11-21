import { readJson } from "../../utils/adminPanelHelpers";

// The Cedar policy engine admin API (backend `api/routes/policy_engine.py`): platform admins only. Answers are
// parsed by policyEngineModel; refusals keep their HTTP status and code on the error (readJson).

export const POLICY_ENGINE_PATH = "/api/v1/admin/policy-engine";

const post = (path: string, body: unknown = {}) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}${path}`, { method: "POST", body: JSON.stringify(body) });

export const loadEngineStatus = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/status`);
export const saveEngineMode = (mode: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/mode`, { method: "PUT", body: JSON.stringify({ mode }) });
export const saveEngineSettings = (settings: { enforce_window_hours?: number; decision_log_retention_days?: number }) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/settings`, { method: "PUT", body: JSON.stringify(settings) });
export const loadSchema = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/schema`);
export const loadBaseline = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/baseline`);
export const loadEntities = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/entities`);
export const validatePolicies = (policies: string) => post("/validate", { policies });

export const loadVersions = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets`);
export const loadVersion = (version: number) => readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets/${version}`);
export const createDraft = (policies: string, note: string) => post("/policy-sets", { policies, note });
/** Save the whole text; `etag` is the digest the editor started from (409 `policy_set_draft_conflict` when it changed). */
export const saveDraft = (version: number, policies: string, note: string, etag: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets/${version}`, {
    method: "PUT",
    body: JSON.stringify({ policies, note }),
    headers: { Accept: "application/json", "Content-Type": "application/json", "If-Match": etag },
  });
/** Change only the draft's note: the text is not re-sent, so a concurrent edit is never overwritten. */
export const saveDraftNote = (version: number, note: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets/${version}`, { method: "PATCH", body: JSON.stringify({ note }) });
export const submitVersion = (version: number) => post(`/policy-sets/${version}/submit`);
/** `selfApprove`: the single-step publish the approval rule may allow (the server approves the own pending review). */
export const publishVersion = (version: number, approvalId: string | null, selfApprove = false) =>
  post(`/policy-sets/${version}/publish`, selfApprove ? { self_approve: true } : { governance_approval_id: approvalId });
export const retireVersion = (version: number) => post(`/policy-sets/${version}/retire`);
export const rollbackVersion = (version: number) => post(`/policy-sets/${version}/rollback`);
/** The governance approval a submit opened; decided by another platform admin through the approvals API. */
export const approveReview = (approvalId: string) =>
  readJson<unknown>(`/api/v1/approvals/${encodeURIComponent(approvalId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ reason: "Cedar policy set reviewed" }),
  });

export const runTestBench = (request: unknown) => post("/test-bench", request);
export const loadTestCases = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/tests`);
export const saveTestCase = (testCase: unknown) => post("/tests", testCase);
export const deleteTestCase = (id: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/tests/${encodeURIComponent(id)}`, { method: "DELETE" });
/** `source`: the published custom policies (default) or the open draft. */
export const runTestCases = (body: { source?: "published" | "draft" }) => post("/tests/run", body);

export function loadDecisions(filters: Record<string, string | number | undefined>): Promise<unknown> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && String(value).trim() !== "") query.set(key, String(value));
  }
  const suffix = query.toString();
  return readJson<unknown>(`${POLICY_ENGINE_PATH}/decisions${suffix ? `?${suffix}` : ""}`);
}

export const loadDecision = (id: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/decisions/${encodeURIComponent(id)}`);

// Policy UX read model (backend `api/routes/policy_engine_catalog.py`).
export const loadCatalog = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/catalog`);
export const loadPickerEntities = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/catalog/entities`);
/** The working version per policy (draft, in review, else published); `generated` adds the baseline. */
export const loadPolicies = (generated = false) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/policies${generated ? "?include_generated=true" : ""}`);
export const loadPolicy = (version: number, policyId: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets/${version}/policies/${encodeURIComponent(policyId)}`);

// Guided builder (backend `api/routes/policy_engine_builder.py`). Headers are given whole because
// readJson replaces them when `init.headers` is set.
const JSON_HEADERS = { Accept: "application/json", "Content-Type": "application/json" };
export const renderPolicyModel = (model: unknown) => post("/policy-builder/render", { model });
/** Save one policy into the draft; `etag` is the digest of `version` as the page saw it (409 when it changed). */
export const savePolicy = (version: number, policyId: string, body: unknown, etag: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets/${version}/policies/${encodeURIComponent(policyId)}`, {
    method: "PUT", body: JSON.stringify(body), headers: { ...JSON_HEADERS, "If-Match": etag },
  });
export const removePolicy = (version: number, policyId: string, etag: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets/${version}/policies/${encodeURIComponent(policyId)}`, {
    method: "DELETE", headers: { Accept: "application/json", "If-Match": etag },
  });
/** Examples the policy must block and one it must leave alone, answered against the draft with it. */
export const generateExamples = (model: unknown, originalId: string | null) => post("/test-bench/generate", { model, original_id: originalId });
export const loadPolicyReferences = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/policies/references`);
/** What this version, as the open draft, would have blocked in live traffic (the draft shadow). */
export const loadDraftImpact = (version: number, hours = 24) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/policy-sets/${version}/impact?hours=${hours}`);

/** Denied (or would-deny) decisions per policy in the last 7 days, from Observability → Decisions. */
export const loadPolicyDenialCounts = () => readJson<unknown>("/api/v1/observability/decisions/policy-counts?days=7");
