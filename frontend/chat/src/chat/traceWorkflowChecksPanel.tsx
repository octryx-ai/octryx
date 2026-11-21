// The session's latest workflow check result: what the selected workflow's checks found at turn end, in
// platform chat or at octryx-claude's Stop. Admins only (the results API is admin-scoped). Replaces the quality
// gate panel; nothing is evaluated from here.
import { useEffect, useState } from "react";

import { checkTypeLabel } from "../admin/components/agentsWorkflows/canvas/checkTypeLabels";
import { readJson } from "./chatApiClient";

type CheckOutcome = { type: string; outcome: string; blocking: boolean; description: string; detail: string };
type CheckResultRow = { id: string; workflow_key: string; runtime: string; state: string; results: CheckOutcome[] };

export const CHECK_STATE_LABELS: Record<string, string> = {
  passed: "passed",
  not_verified: "not verified",
  stop_blocked: "Stop blocked",
};

function badgeClass(outcome: string) {
  if (outcome === "passed") return "trace-gates__badge trace-gates__badge--passed";
  if (outcome === "failed" || outcome === "not_verified" || outcome === "stop_blocked") {
    return "trace-gates__badge trace-gates__badge--failed";
  }
  return "trace-gates__badge";
}

export function TraceWorkflowChecksPanel({ sessionId, open }: { sessionId?: string | null; open: boolean }) {
  const [latest, setLatest] = useState<CheckResultRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !sessionId) {
      setLatest(null);
      return;
    }
    let active = true;
    readJson<{ results: CheckResultRow[] }>(
      `/api/v1/workflow-checks/results?session_id=${encodeURIComponent(sessionId)}&limit=1`,
    )
      .then((payload) => {
        if (!active) return;
        setLatest(payload.results[0] ?? null);
        setError(null);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Check results failed to load");
      });
    return () => {
      active = false;
    };
  }, [open, sessionId]);

  return (
    <section className="trace-drawer__section trace-gates" data-testid="trace-workflow-checks">
      <div className="trace-drawer__section-header">
        <div>
          <div className="trace-drawer__section-title">Workflow checks</div>
          <div className="trace-drawer__section-copy">The selected workflow's done criteria at the end of the last checked turn.</div>
        </div>
      </div>
      {error ? <div className="trace-gates__error">{error}</div> : null}
      {!error && !latest ? <div className="trace-empty">No workflow with checks ran in this session.</div> : null}
      {latest ? (
        <div className="trace-gates__result">
          <div className="trace-gates__summary">
            <div>
              <strong>{latest.workflow_key}</strong>
              <span>{latest.runtime}</span>
            </div>
            <span className={badgeClass(latest.state)}>{CHECK_STATE_LABELS[latest.state] ?? latest.state}</span>
          </div>
          <div className="trace-gates__list">
            {latest.results.map((check, index) => (
              <div key={`${check.type}-${index}`} className="trace-gates__summary">
                <div>
                  <strong>{check.description || checkTypeLabel(check.type)}</strong>
                  <span>{`${checkTypeLabel(check.type)} · ${check.blocking ? "blocking" : "advisory"}${check.detail ? ` · ${check.detail}` : ""}`}</span>
                </div>
                <span className={badgeClass(check.outcome)}>{check.outcome}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
