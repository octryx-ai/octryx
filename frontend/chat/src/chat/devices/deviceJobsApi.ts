// The chat's device jobs (backend api/routes/device_jobs.py). Refusals carry `{state, reason}`.

async function jobJson<T>(path: string, init?: RequestInit): Promise<T> {
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
    const reason = (payload as { reason?: unknown } | null)?.reason;
    const code = typeof reason === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(reason) ? reason : null;
    throw Object.assign(new Error(code ?? "Request failed"), { status: response.status, code });
  }
  return payload as T;
}

export function loadDeviceJobs(sessionId: string): Promise<unknown> {
  return jobJson<unknown>(`/api/v1/device-jobs?session_id=${encodeURIComponent(sessionId)}`);
}

export function decideDeviceApproval(jobId: string, approvalId: string, decision: "allow_once" | "allow_job_edits" | "deny") {
  return jobJson<unknown>(
    `/api/v1/device-jobs/${encodeURIComponent(jobId)}/approvals/${encodeURIComponent(approvalId)}`,
    { method: "POST", body: JSON.stringify({ decision }) },
  );
}

export function stopDeviceJob(jobId: string) {
  return jobJson<unknown>(`/api/v1/device-jobs/${encodeURIComponent(jobId)}/stop`, { method: "POST" });
}
