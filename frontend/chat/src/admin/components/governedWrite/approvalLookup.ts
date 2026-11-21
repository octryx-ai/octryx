// One approval by id: GET /api/v1/approvals/{id}. The server answers bounded metadata
// (no reason text) only to a caller who may see the approval, under the same rule as the
// approvals list (backend `services/approval/access.py`); everyone else gets the same 404
// as an unknown id. So "not found" means "unknown or not visible to you", never
// "rejected" or "approved".

export type ApprovalLookup = {
  id: string;
  kind: string | null;
  status: string;
  action: string | null;
  requestedBy: string | null;
  approvedBy: string | null;
  createdAt: string | null;
  resolvedAt: string | null;
};

export type ApprovalLookupResult =
  | { status: "found"; approval: ApprovalLookup }
  | { status: "not_found" }
  | { status: "error"; httpStatus: number };

export type LookupFetch = (input: string, init?: RequestInit) => Promise<Response>;

export function approvalLookupUrl(approvalId: string) {
  return `/api/v1/approvals/${encodeURIComponent(approvalId.trim())}`;
}

function text(value: unknown, max = 200): string | null {
  return typeof value === "string" && value ? value.slice(0, max) : null;
}

export function parseApprovalLookup(payload: unknown): ApprovalLookup | null {
  const record = payload && typeof payload === "object" && !Array.isArray(payload) ? (payload as Record<string, unknown>) : null;
  const id = text(record?.id, 64);
  const status = text(record?.status, 32);
  if (!record || !id || !status) {
    return null;
  }
  return {
    id,
    kind: text(record.kind, 32),
    status,
    action: text(record.action),
    requestedBy: text(record.requested_by, 64),
    approvedBy: text(record.approved_by, 64),
    createdAt: text(record.created_at, 64),
    resolvedAt: text(record.resolved_at, 64),
  };
}

export async function lookupApproval(
  approvalId: string,
  fetchFn: LookupFetch = (input, init) => fetch(input, init),
): Promise<ApprovalLookupResult> {
  if (!approvalId.trim()) {
    return { status: "not_found" };
  }
  const response = await fetchFn(approvalLookupUrl(approvalId), {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (response.status === 404) {
    return { status: "not_found" };
  }
  if (!response.ok) {
    return { status: "error", httpStatus: response.status };
  }
  const approval = parseApprovalLookup(await response.json().catch(() => null));
  return approval ? { status: "found", approval } : { status: "error", httpStatus: response.status };
}
