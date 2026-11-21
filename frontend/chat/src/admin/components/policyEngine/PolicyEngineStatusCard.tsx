import { useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { saveEngineMode, saveEngineSettings } from "./policyEngineApi";
import { MODES, OUTCOME_LABELS, POINT_LABELS, enforceBlockers, outcomeTotals, readStatus, readinessLine, serverDate } from "./policyEngineStatus";
import { refusalText } from "./policyEngineVersions";
import type { EngineStatus, PolicyMode } from "./policyEngineStatus";
import "./policyDrawers.css";
import { formatDateTime } from "../../utils/dateTime";

const MODE_TITLES: Record<PolicyMode, { title: string; text: string }> = {
  off: { title: "Off", text: "Cedar is not evaluated." },
  shadow: { title: "Shadow", text: "Evaluated and compared, never enforced." },
  enforce: { title: "Enforce", text: "Cedar denials become the answer." },
};
const COLUMNS = ["match", "custom_policy", "mismatch", "error"];

// The engine status in one line for the page header: mode, disagreements in the enforce window,
// the published version and the enforce readiness. A click opens the status drawer.
export function PolicyEngineStatusCard({ status, onOpen }: { status: EngineStatus; onOpen: () => void }) {
  const alert = !status.customValid || !status.engineAvailable || status.enforce.mismatches > 0 || status.enforce.errors > 0;
  const dot = alert ? "alert" : status.mode;
  return (
    <button type="button" className="policies__status-card" title="Policy engine status" data-testid="policy-engine-card" onClick={onOpen}>
      <span className={`policies__status-dot policies__status-dot--${dot}`} />
      <b data-testid="policy-engine-mode">{MODE_TITLES[status.mode].title}</b>
      <span className="policies__status-sep" />
      <span>{status.enforce.mismatches} mismatches · {status.enforce.windowHours} h</span>
      <span className="policies__status-sep" />
      <span>{status.customVersion !== null ? `v${status.customVersion} published` : "Nothing published"}</span>
      <span className="policies__status-sep" />
      <span data-testid="policy-engine-readiness">{readinessLine(status)}</span>
    </button>
  );
}

// The status drawer: mode Off / Shadow / Enforce with the readiness reasons, the decisions per check since the
// server started, latency, and the window and retention settings. Enforce stays guarded by the server.
export function PolicyEngineStatusDrawer({ status, onChanged, onClose }: {
  status: EngineStatus; onChanged: (next: EngineStatus) => void; onClose: () => void;
}) {
  const [mode, setMode] = useState<PolicyMode>(status.mode);
  const [windowHours, setWindowHours] = useState(String(status.enforce.windowHours || 24));
  const [retention, setRetention] = useState(String(status.retentionDays || 365));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const totals = outcomeTotals(status.counters);
  const blockers = enforceBlockers(status);
  const enforceBlocked = status.mode !== "enforce" && !status.enforce.ready;
  const settingsChanged = Number(windowHours) !== status.enforce.windowHours || Number(retention) !== status.retentionDays;

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      if (settingsChanged) {
        await saveEngineSettings({ enforce_window_hours: Number(windowHours), decision_log_retention_days: Number(retention) });
      }
      const next = mode !== status.mode ? readStatus(await saveEngineMode(mode)) : null;
      if (next) onChanged(next);
      setMessage({ ok: true, text: "Saved." });
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsDrawer eyebrow="Policy engine" title="Status & mode" size="detail" onClose={onClose}
      footer={<>
        <span className="policies__spacer" />
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="policy-engine-mode-save"
          disabled={saving || (mode === status.mode && !settingsChanged)} onClick={() => void save()}>{saving ? "Saving…" : "Save"}</button>
      </>}>
      <EngineKpis status={status} />
      <ModeChoice status={status} mode={mode} setMode={setMode} saving={saving} enforceBlocked={enforceBlocked} blockers={blockers} />
      <DecisionCounters status={status} totals={totals} />
      <EngineSettings windowHours={windowHours} setWindowHours={setWindowHours} retention={retention} setRetention={setRetention} />
      {message ? <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"} data-testid="policy-engine-message">{message.text}</p> : null}
    </SettingsDrawer>
  );
}

// Mode, mismatches in the window and latency, then what keeps the engine from working as published.
function EngineKpis({ status }: { status: EngineStatus }) {
  return (
    <>
      <div className="policies__kpis" data-testid="policy-engine-status">
        <div className="policies__kpi"><div className="policies__kpi-label">Mode</div><div className="policies__kpi-value">{MODE_TITLES[status.mode].title}</div>
          <div className="policies__kpi-meta">{status.enforce.shadowSince ? `shadow since ${formatDateTime(status.enforce.shadowSince)}` : `schema ${status.schemaVersion || "unknown"}`}</div></div>
        <div className="policies__kpi"><div className="policies__kpi-label">Mismatches</div><div className="policies__kpi-value">{status.enforce.mismatches}</div>
          <div className="policies__kpi-meta">in the {status.enforce.windowHours} h window</div></div>
        <div className="policies__kpi"><div className="policies__kpi-label">p95 latency</div><div className="policies__kpi-value">{status.p95Ms.toFixed(1)} ms</div>
          <div className="policies__kpi-meta" data-testid="policy-engine-latency">over {status.samples} decisions{status.draftSamples ? ` · draft shadow +${status.draftP95Ms.toFixed(1)} ms` : ""}</div></div>
      </div>
      {!status.engineAvailable ? <div className="policies__warn" role="alert">The Cedar engine is not available on this server.</div> : null}
      {!status.customValid ? <div className="policies__warn" role="alert" data-testid="policy-engine-invalid">The published custom policies do not load, so they are not applied (they fall back to shadow) and only the baseline decides until a valid version is published. {status.customFallbacks} decisions evaluated without them since the server started.</div> : null}
    </>
  );
}

// Off / Shadow / Enforce; Enforce stays locked until the server reports it ready, with the reasons.
function ModeChoice({ status, mode, setMode, saving, enforceBlocked, blockers }: {
  status: EngineStatus;
  mode: PolicyMode;
  setMode: (mode: PolicyMode) => void;
  saving: boolean;
  enforceBlocked: boolean;
  blockers: string[];
}) {
  return (
    <section className="work-detail__section">
      <h3>Mode</h3>
      <div className="policies__modes" role="radiogroup" aria-label="Mode">
        {MODES.map((value) => (
          <button key={value} type="button" role="radio" aria-checked={mode === value} data-testid={`policy-engine-mode-${value}`}
            className={`policies__choice${mode === value ? " policies__choice--selected" : ""}`}
            disabled={saving || (value === "enforce" && enforceBlocked)} onClick={() => setMode(value)}>
            <b>{MODE_TITLES[value].title}</b><span>{MODE_TITLES[value].text}</span>
          </button>
        ))}
      </div>
      {enforceBlocked ? (
        <div className="policies__warn" data-testid="policy-engine-blockers">
          Enforce is not ready: {blockers.join(" ")} Enforcement unlocks after {status.enforce.windowHours} hours in shadow without a disagreement or error.
        </div>
      ) : null}
    </section>
  );
}

function DecisionCounters({ status, totals }: { status: EngineStatus; totals: Record<string, number> }) {
  return (
    <section className="work-detail__section">
      <h3>Decisions per check (since the server started)</h3>
      <table className="admin-panel__table" data-testid="policy-engine-counters">
        <thead><tr><th scope="col">Check</th>{COLUMNS.map((key) => <th key={key} scope="col">{OUTCOME_LABELS[key]}</th>)}</tr></thead>
        <tbody>
          {Object.entries(status.counters).map(([point, outcomes]) => (
            <tr key={point}><td>{POINT_LABELS[point] ?? point}</td>{COLUMNS.map((key) => <td key={key}>{outcomes[key] ?? 0}</td>)}</tr>
          ))}
        </tbody>
      </table>
      <p className="admin-panel__hint" data-testid="policy-engine-summary">
        {totals.match ?? 0} agreements, {totals.mismatch ?? 0} disagreements, {totals.error ?? 0} errors. Decision log kept {status.retentionDays} days.
      </p>
    </section>
  );
}

function EngineSettings({ windowHours, setWindowHours, retention, setRetention }: {
  windowHours: string; setWindowHours: (value: string) => void; retention: string; setRetention: (value: string) => void;
}) {
  return (
    <section className="work-detail__section">
      <h3>Settings</h3>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field"><span>Enforce window (hours)</span>
          <input type="number" min={1} max={720} value={windowHours} data-testid="policy-engine-window" onChange={(event) => setWindowHours(event.target.value)} /></label>
        <label className="admin-panel__field"><span>Decision log retention (days)</span>
          <input type="number" min={1} max={365} value={retention} data-testid="policy-engine-retention" onChange={(event) => setRetention(event.target.value)} /></label>
      </div>
    </section>
  );
}
