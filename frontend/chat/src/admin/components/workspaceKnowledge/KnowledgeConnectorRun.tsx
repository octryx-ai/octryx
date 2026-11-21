import { formatApiClock } from "./apiTime";
import { completedWithFailures } from "./connectorFreshness";
import { formatTime } from "./connectorDisplay";
import { reasonText } from "./connectorReasons";
import { KnowledgeReasonNotice } from "./KnowledgeReasonNotice";
import { runReasonNotice } from "./runReasonNotice";
import { gitRunCountsText, gitRunRevision } from "./gitRepositoryReport";
import type { ItemOutcome, OutcomeKind, RunReport, RunState, SyncRun } from "./connectorTypes";

const RUN_BADGE: Record<RunState, string> = {
  completed: "admin-panel__badge--active",
  budget_exhausted: "admin-panel__badge--warning",
  needs_configuration: "admin-panel__badge--warning",
  running: "admin-panel__badge--inactive",
  failed: "admin-panel__badge--danger",
};
const RUN_LABEL: Record<RunState, string> = {
  completed: "completed",
  budget_exhausted: "more to sync",
  needs_configuration: "needs configuration",
  running: "running",
  failed: "failed",
};
const OUTCOME_BADGE: Record<OutcomeKind, string> = {
  created: "admin-panel__badge--active",
  updated: "admin-panel__badge--active",
  unchanged: "admin-panel__badge--inactive",
  retired: "admin-panel__badge--inactive",
  skipped: "admin-panel__badge--warning",
  failed: "admin-panel__badge--danger",
  deferred: "admin-panel__badge--warning",
};
const COUNT_KEYS: OutcomeKind[] = ["created", "updated", "unchanged", "retired", "skipped", "failed", "deferred"];
// The runner records at most this many per-item outcomes per run (sync/runner.py MAX_RECORDED_OUTCOMES).
const MAX_RECORDED_OUTCOMES = 200;

// The ref a Git repository run asked for and the commit it read; nothing before a ref was resolved.
export function RunRevision({ report }: { report: RunReport }) {
  const revision = gitRunRevision(report);
  if (!revision) return null;
  return (
    <span className="admin-panel__muted" style={{ overflowWrap: "anywhere" }}>
      commit <code>{revision.commit}</code>{revision.ref ? <> (ref <code>{revision.ref}</code>)</> : null}
    </span>
  );
}

export function RunBadge({ run }: { run: SyncRun }) {
  // Failed or deferred items keep a completed run from counting as a clean pass, so it is not green.
  if (completedWithFailures(run)) {
    return <span className="admin-panel__badge admin-panel__badge--warning">completed with failures</span>;
  }
  return (
    <span className={`admin-panel__badge ${RUN_BADGE[run.state] ?? "admin-panel__badge--inactive"}`}>
      {RUN_LABEL[run.state] ?? run.state}
    </span>
  );
}

// "3 created · 1 skipped (withheld) · 2 failed": only the non-zero counts, in a fixed order. A Git repository run
// shows its per-file outcomes instead, with every main count also when zero.
export function RunCounts({ report, kind }: { report: RunReport; kind?: string }) {
  if (kind === "git_repository") return <span>{gitRunCountsText(report)}</span>;
  const parts = COUNT_KEYS.filter((key) => (report[key] ?? 0) > 0).map((key) => `${report[key]} ${key}`);
  if (!parts.length) return <span className="admin-panel__muted">{report.listed ? `${report.listed} listed, nothing changed` : "no items"}</span>;
  return <span>{parts.join(" · ")}</span>;
}

function OutcomeTable({ outcomes }: { outcomes: ItemOutcome[] }) {
  return (
    <div className="admin-panel__table-wrap" style={{ maxHeight: "22rem", overflowY: "auto" }}>
      <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
        <thead><tr><th>Item</th><th>Outcome</th><th>Reason</th></tr></thead>
        <tbody>
          {outcomes.map((item, index) => (
            <tr key={`${item.external_id ?? "item"}-${index}`}>
              <td style={{ minWidth: "14rem", overflowWrap: "anywhere" }}>
                {item.title ?? <span className="admin-panel__muted">{item.reason === "restricted_acl" ? "Title withheld" : "—"}</span>}
                {item.external_id ? <div className="admin-panel__muted"><code>{item.external_id}</code></div> : null}
              </td>
              <td><span className={`admin-panel__badge ${OUTCOME_BADGE[item.outcome] ?? "admin-panel__badge--inactive"}`}>{item.outcome}</span></td>
              <td className="admin-panel__muted">{reasonText(item.reason) || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {outcomes.length >= MAX_RECORDED_OUTCOMES ? (
        <div className="admin-panel__hint" style={{ margin: "0.4rem" }}>
          Only the first {MAX_RECORDED_OUTCOMES} items of a run are recorded; the counts above cover all of them.
        </div>
      ) : null}
    </div>
  );
}

// One run's report: its state and fixed reason, the counts, and (for the last run) the per-item outcomes.
// A launcher snapshot (m4) completes its passes by upload, without a sync run: it says so instead of "not run yet".
// It is a tab of the source's side panel, whose title names the source: no heading, no extra indent.
export function KnowledgeConnectorRun({ connectorKey, kind, run, snapshot = false }: {
  connectorKey: string; kind?: string; run: SyncRun | null; snapshot?: boolean;
}) {
  if (!run) {
    return (
      <div data-testid="source-last-run" data-source-name={connectorKey}>
        <div className="admin-panel__hint" style={{ margin: 0 }}>
          {snapshot ? "Snapshots arrive by launcher upload, so this source has no sync runs." : "This source has not synced yet."}
        </div>
      </div>
    );
  }
  const outcomes = run.outcomes ?? [];
  const notice = runReasonNotice(run.reason, outcomes.map((item) => item.reason));
  return (
    <div data-testid="source-last-run" data-source-name={connectorKey}>
      <div className="admin-users__row-actions" style={{ flexWrap: "wrap", marginBottom: "0.5rem" }}>
        <RunBadge run={run} />
        <RunCounts report={run.report} kind={kind} />
        <RunRevision report={run.report} />
        {run.report.listed ? <span className="admin-panel__muted">{run.report.listed} listed</span> : null}
        <span className="admin-panel__muted">
          {formatTime(run.started_at)} – {run.finished_at ? formatApiClock(run.finished_at) : "running"}
        </span>
      </div>
      {notice ? <KnowledgeReasonNotice notice={notice} /> : null}
      {run.reason && notice?.code !== run.reason ? <div className="admin-panel__hint">{reasonText(run.reason)}.</div> : null}
      {run.state === "budget_exhausted" ? (
        <div className="admin-panel__hint">The run reached its item budget; the next run resumes where this one stopped.</div>
      ) : null}
      {outcomes.length ? (
        // The per-item log can hold 200 rows: closed by default, the counts above say what happened.
        <details className="area-disclosure" data-testid="run-outcomes">
          <summary className="area-disclosure__summary">Items of this run ({outcomes.length})</summary>
          <div className="area-disclosure__body">
            <OutcomeTable outcomes={outcomes} />
          </div>
        </details>
      ) : (
        <div className="admin-panel__hint" style={{ margin: 0 }}>No items were handled in this run.</div>
      )}
    </div>
  );
}
