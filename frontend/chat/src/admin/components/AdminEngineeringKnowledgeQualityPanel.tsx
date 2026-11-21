import { useCallback, useEffect, useState } from "react";
import { readJson } from "../utils/adminPanelHelpers";

type GateReport = {
  node_id: string;
  node_key: string;
  passed: boolean;
  status: string;
  quality_score: number;
  blocking_count: number;
  warning_count: number;
  blockers: Array<{ key: string; label: string; message: string; severity: string }>;
  warnings: Array<{ key: string; label: string; message: string; severity: string }>;
};

type QualityPayload = {
  status_counts: Record<string, number>;
  trust_counts: Record<string, number>;
  usage: {
    retrieval_miss_count: number | null;
    retrieval_miss_instrumented: boolean;
    retrieval_miss_note: string;
  };
  quality: {
    evaluated_count: number;
    passed_count: number;
    failed_count: number;
    failures_by_gate: Record<string, number>;
  };
  evaluation_scenarios: Array<{ key: string; label: string; required_signals: string[] }>;
  sample_reports: GateReport[];
};

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="admin-panel__empty-state">
      <span className="admin-panel__eyebrow">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function countRows(values: Record<string, number>) {
  return Object.entries(values).sort(([left], [right]) => left.localeCompare(right));
}

export function AdminEngineeringKnowledgeQualityPanel() {
  const [payload, setPayload] = useState<QualityPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => loadQuality(setPayload, setLoading, setError), []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="admin-panel__section">
      <div className="admin-panel__section-header">
        <div>
          <div className="admin-panel__eyebrow">Engineering Knowledge Quality</div>
          <h3>Quality gates</h3>
        </div>
        <button type="button" className="admin-panel__action-btn" onClick={() => void load()} disabled={loading}>
          Reload
        </button>
      </div>
      {error ? <div className="admin-panel__error">{error}</div> : null}
      {payload ? (
        <>
          <QualityTiles payload={payload} />
          <QualityCounts payload={payload} />
          <SampleReports reports={payload.sample_reports} />
        </>
      ) : loading ? (
        <div className="admin-panel__empty-state">Loading quality gates...</div>
      ) : null}
    </div>
  );
}

async function loadQuality(
  setPayload: (payload: QualityPayload) => void,
  setLoading: (loading: boolean) => void,
  setError: (error: string | null) => void,
) {
  setLoading(true);
  setError(null);
  try {
    setPayload(await readJson<QualityPayload>("/admin/chat/api/panel/engineering-knowledge/quality?limit=50"));
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
  } finally {
    setLoading(false);
  }
}

function QualityTiles({ payload }: { payload: QualityPayload }) {
  return (
    <>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: "0.65rem",
        }}
      >
        <StatTile label="Evaluated" value={payload.quality.evaluated_count} />
        <StatTile label="Passed" value={payload.quality.passed_count} />
        <StatTile label="Failed" value={payload.quality.failed_count} />
        <StatTile
          label="Retrieval misses"
          value={
            payload.usage.retrieval_miss_instrumented
              ? (payload.usage.retrieval_miss_count ?? 0)
              : "not instrumented"
          }
        />
      </div>
      {!payload.usage.retrieval_miss_instrumented ? (
        <div className="admin-panel__hint" style={{ marginTop: "0.5rem" }}>
          {payload.usage.retrieval_miss_note}
        </div>
      ) : null}
    </>
  );
}

function CountList({ values }: { values: Record<string, number> }) {
  return (
    <>
      {countRows(values).map(([key, value]) => (
        <div key={key} className="admin-panel__hint">
          {key}: {value}
        </div>
      ))}
    </>
  );
}

function QualityCounts({ payload }: { payload: QualityPayload }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: "0.8rem",
        marginTop: "0.9rem",
      }}
    >
      <div className="admin-panel__form">
        <h4>Graph state</h4>
        <div className="admin-panel__stack">
          <CountList values={payload.status_counts} />
        </div>
        <h4>Trust levels</h4>
        <div className="admin-panel__stack">
          <CountList values={payload.trust_counts} />
        </div>
      </div>
      <div className="admin-panel__form">
        <h4>Gate failures</h4>
        <div className="admin-panel__stack">
          <CountList values={payload.quality.failures_by_gate} />
          {Object.keys(payload.quality.failures_by_gate).length === 0 ? (
            <div className="admin-panel__empty-state">No blocking failures in the evaluated sample.</div>
          ) : null}
        </div>
        <h4>Evaluation scenarios</h4>
        <div className="admin-panel__stack">
          {payload.evaluation_scenarios.map((scenario) => (
            <div key={scenario.key} className="admin-panel__hint">
              <strong>{scenario.label}</strong>: {scenario.required_signals.join(", ")}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SampleReports({ reports }: { reports: GateReport[] }) {
  return (
    <>
      <h4 style={{ marginTop: "0.9rem" }}>Sample reports</h4>
      <div className="admin-panel__table-wrap">
        <table className="admin-panel__table">
          <thead>
            <tr>
              <th>Fact</th>
              <th>Status</th>
              <th>Score</th>
              <th>Blockers</th>
              <th>Warnings</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((report) => (
              <tr key={report.node_id}>
                <td>
                  <strong>{report.node_key}</strong>
                  {report.blockers[0] ? <div className="admin-panel__hint">{report.blockers[0].message}</div> : null}
                </td>
                <td>{report.status}</td>
                <td>{Math.round(report.quality_score * 100)}%</td>
                <td>{report.blocking_count}</td>
                <td>{report.warning_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {reports.length === 0 ? (
          <div className="admin-panel__empty-state">No Engineering Knowledge facts available for evaluation.</div>
        ) : null}
      </div>
    </>
  );
}
