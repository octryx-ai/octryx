// A JSON request against a governed admin write that keeps the server's refusal intact.
// The shared admin readJson flattens an object `detail` to "[object Object]"; governed
// writes answer with a validation report (`errors[].code`) and an approval gate, and the
// admin must see both exactly as the server stated them.

export type GovernedIssue = { code: string; message: string };

export type ApprovalGate = {
  status: string;
  approval_id: string | null;
  action?: string;
};

export type GovernedOutcome<T> =
  | { ok: true; status: number; data: T }
  | {
      ok: false;
      status: number;
      issues: GovernedIssue[];
      warnings: GovernedIssue[];
      approvalGate: ApprovalGate | null;
    };

function issueList(value: unknown): GovernedIssue[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => item && typeof item === "object")
    .map((item) => {
      const entry = item as Record<string, unknown>;
      return {
        code: typeof entry.code === "string" ? entry.code : "unknown_code",
        message: typeof entry.message === "string" ? entry.message : "",
      };
    });
}

function approvalGateOf(detail: Record<string, unknown>): ApprovalGate | null {
  const review = detail.governance_review;
  const gate = review && typeof review === "object" ? (review as Record<string, unknown>).approval_gate : null;
  if (!gate || typeof gate !== "object") return null;
  const entry = gate as Record<string, unknown>;
  return {
    status: typeof entry.status === "string" ? entry.status : "unknown",
    approval_id: typeof entry.approval_id === "string" ? entry.approval_id : null,
    action: typeof entry.action === "string" ? entry.action : undefined,
  };
}

// Map a non-2xx body to the refusal the admin sees. A plain-string `detail` (for example
// a 400 from a config validator or a 403) becomes one issue coded by its HTTP status.
export function refusalFromBody(status: number, body: unknown) {
  const detail = body && typeof body === "object" ? (body as Record<string, unknown>).detail : undefined;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const report = detail as Record<string, unknown>;
    return {
      issues: issueList(report.errors),
      warnings: issueList(report.warnings),
      approvalGate: approvalGateOf(report),
    };
  }
  const message = typeof detail === "string" && detail ? detail : "Request refused";
  return { issues: [{ code: `http_${status}`, message }], warnings: [], approvalGate: null };
}

export async function governedRequest<T>(
  url: string,
  init: { method: string; body?: unknown },
): Promise<GovernedOutcome<T>> {
  const response = await fetch(url, {
    method: init.method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok) return { ok: true, status: response.status, data: body as T };
  return { ok: false, status: response.status, ...refusalFromBody(response.status, body) };
}
