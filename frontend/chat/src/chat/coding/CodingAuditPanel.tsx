import { useEffect, useMemo, useState } from "react";

import { evaluateCodingQualityGates } from "../work/workCodingApi";
import type { WorkCodingAuditReport, WorkCodingQualityGate } from "../work/workCodingReviewTypes";
import type { CodingSessionSummary } from "./codingTypes";

type CodingAuditPanelProps = {
  session: CodingSessionSummary;
  report: WorkCodingAuditReport | null;
  fallbackBlocked: boolean;
};

export function CodingAuditPanel({
  session,
  report,
  fallbackBlocked,
}: CodingAuditPanelProps) {
  const [currentReport, setCurrentReport] = useState<WorkCodingAuditReport | null>(report);
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCurrentReport(report);
    setError(null);
  }, [report, session.id]);

  const summary = currentReport?.quality_summary;
  const prSummary = currentReport?.pr_summary;
  const blockingGates = useMemo(
    () => (currentReport?.quality_gates || []).filter((gate) => gate.blocking),
    [currentReport],
  );

  async function evaluate() {
    setEvaluating(true);
    setError(null);
    try {
      const nextReport = await evaluateCodingQualityGates(session.id, {
        evidence: { source: "coding_audit_panel", session_id: session.id },
      });
      setCurrentReport(nextReport);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to evaluate quality gates");
    } finally {
      setEvaluating(false);
    }
  }

  if (!currentReport) {
    return <AuditEmpty fallbackBlocked={fallbackBlocked} evaluating={evaluating} error={error} evaluate={evaluate} />;
  }

  return (
    <div className="coding-audit">
      <AuditHero summary={summary} evaluating={evaluating} evaluate={evaluate} />

      {error ? <p className="coding-review__error">{error}</p> : null}

      <AuditMetrics report={currentReport} />

      <GateEvidence gates={currentReport.quality_gates} blockingCount={blockingGates.length} />

      {prSummary ? <PrSummarySection prSummary={prSummary} /> : null}

      <AuditTimeline report={currentReport} />
    </div>
  );
}

function GateCard({ gate }: { gate: WorkCodingQualityGate }) {
  return (
    <article className={`coding-audit-gate is-${gate.status}`}>
      <div>
        <strong>{gate.label}</strong>
        <span>{gate.status}</span>
      </div>
      <p>{gate.reason}</p>
    </article>
  );
}

function AuditMetric({ label, value }: { label: string; value: string }) {
  return (
    <dl className="coding-audit-metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </dl>
  );
}

function AuditList({ label, values }: { label: string; values: string[] }) {
  return (
    <dl className="coding-audit-list">
      <dt>{label}</dt>
      <dd>{values.length ? values.join(", ") : "Not captured"}</dd>
    </dl>
  );
}

function AuditMetrics({ report }: { report: WorkCodingAuditReport }) {
  const summary = report.quality_summary;
  return (
    <section className="coding-audit__grid">
      <AuditMetric label="Blocking" value={String(summary?.blocking || 0)} />
      <AuditMetric label="Timeline" value={String(report.timeline.length)} />
      <AuditMetric label="Reviews" value={String(report.evidence.review_event_count || 0)} />
      <AuditMetric label="Pipeline stages" value={String(report.evidence.pipeline_stage_count || 0)} />
    </section>
  );
}

function AuditHero({ summary, evaluating, evaluate }: {
  summary: WorkCodingAuditReport["quality_summary"] | undefined;
  evaluating: boolean;
  evaluate: () => Promise<void>;
}) {
  return (
    <section className={`coding-audit__hero is-${summary?.status || "unknown"}`}>
      <div>
        <div className="work-area__eyebrow">PR quality gates</div>
        <h3>{summary?.status || "Unknown"}</h3>
        <p>
          {summary?.blocking || 0} blocking gates · {summary?.total || 0} total checks
        </p>
      </div>
      <button type="button" onClick={() => void evaluate()} disabled={evaluating}>
        {evaluating ? "Evaluating..." : "Evaluate gates"}
      </button>
    </section>
  );
}

function GateEvidence({ gates, blockingCount }: { gates: WorkCodingQualityGate[]; blockingCount: number }) {
  return (
    <section className="coding-audit__section">
      <div className="coding-review__section-heading">
        <strong>Gate evidence</strong>
        <span>{blockingCount ? `${blockingCount} blocking` : "no blocking gate"}</span>
      </div>
      <div className="coding-audit__gates">
        {gates.map((gate) => (
          <GateCard key={gate.key} gate={gate} />
        ))}
      </div>
    </section>
  );
}

function AuditEmpty({ fallbackBlocked, evaluating, error, evaluate }: {
  fallbackBlocked: boolean;
  evaluating: boolean;
  error: string | null;
  evaluate: () => Promise<void>;
}) {
  return (
    <section className="coding-audit coding-audit--empty">
      <div>
        <div className="work-area__eyebrow">Policy & audit</div>
        <h3>No audit report captured yet.</h3>
        <p>Run a quality-gate evaluation to capture reviewable evidence for this Coding Session.</p>
      </div>
      {fallbackBlocked ? (
        <p className="coding-detail__warning">Imported evidence already indicates a blocking condition.</p>
      ) : null}
      <button type="button" onClick={() => void evaluate()} disabled={evaluating}>
        {evaluating ? "Evaluating..." : "Evaluate gates"}
      </button>
      {error ? <p className="coding-review__error">{error}</p> : null}
    </section>
  );
}

function PrSummarySection({ prSummary }: { prSummary: NonNullable<WorkCodingAuditReport["pr_summary"]> }) {
  return (
    <section className="coding-audit__section">
      <div className="coding-review__section-heading">
        <strong>Reviewer PR summary</strong>
        <span>{prSummary.ready_to_open_pr ? "ready" : "not ready"}</span>
      </div>
      <div className="coding-audit__pr">
        <h3>{prSummary.title}</h3>
        <p>{prSummary.request}</p>
        <AuditList label="Repositories" values={prSummary.repositories} />
        <AuditList label="Branches" values={prSummary.branches} />
        <AuditList label="Files" values={prSummary.files} />
        <AuditList label="Reviewers" values={prSummary.reviewers} />
        <AuditList label="Risks" values={prSummary.risks.map((risk) => `${risk.label}: ${risk.reason}`)} />
      </div>
    </section>
  );
}

function AuditTimeline({ report }: { report: WorkCodingAuditReport }) {
  return (
    <section className="coding-audit__section">
      <div className="coding-review__section-heading">
        <strong>Audit timeline</strong>
        <span>{report.source_key}</span>
      </div>
      <ol className="coding-audit__timeline">
        {report.timeline.map((event) => (
          <li key={event.id} className={`is-${event.status || "recorded"}`}>
            <div>
              <strong>{event.title}</strong>
              <small>
                {event.kind} · {event.status || "recorded"} · {event.created_at || "no timestamp"}
              </small>
            </div>
            {event.summary ? <p>{event.summary}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
