// Build the deterministic structured graph per layer and read "Handbook vs. reality".
// No model is called: builds run in the knowledge worker; a completed source sync refreshes them.
import { useCallback, useEffect, useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";
import { HandbookReportView } from "./HandbookReportView";
import { STRUCTURED_LAYERS, structuredGraphApi } from "./structuredGraphApi";
import type { HandbookReport, StructuredLayer, StructuredStatus } from "./structuredGraphApi";
import {
  buildSummary, LAYER_LABELS, layerRows, reportNotice, runnerSummary, toggleLayer,
} from "./structuredGraphModel";

export function StructuredGraphPanel({ workspaceId }: { workspaceId: string }) {
  const [status, setStatus] = useState<StructuredStatus | null>(null);
  const [report, setReport] = useState<HandbookReport | null>(null);
  const [layers, setLayers] = useState<StructuredLayer[]>([...STRUCTURED_LAYERS]);
  const [filters, setFilters] = useState({ parameter: "", file: "", section: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (wanted = { parameter: "", file: "", section: "" }) => {
    try {
      const [nextStatus, nextReport] = await Promise.all([
        structuredGraphApi.status(workspaceId), structuredGraphApi.report(workspaceId, wanted),
      ]);
      setStatus(nextStatus);
      setReport(nextReport);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [workspaceId]);

  useEffect(() => { void load(); }, [load]);

  const build = async () => {
    setBusy(true);
    try {
      await structuredGraphApi.build(workspaceId, layers);
      await load(filters);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const filter = (event: FormEvent) => {
    event.preventDefault();
    void load(filters);
  };

  const notice = reportNotice(report);
  return (
    <div className="admin-panel__stack">
      <BuildSection status={status} layers={layers} setLayers={setLayers} busy={busy} onBuild={() => void build()}
        onRefresh={() => void load(filters)} />
      {error ? <div className="admin-panel__error" role="alert">{error}</div> : null}
      <HandbookSection workspaceId={workspaceId} filters={filters} setFilters={setFilters} onFilter={filter} notice={notice}
        report={report} />
    </div>
  );
}

type Filters = { parameter: string; file: string; section: string };

// The layers with their counts, the latest build and runner report, and the layers to build.
function BuildSection({ status, layers, setLayers, busy, onBuild, onRefresh }: {
  status: StructuredStatus | null;
  layers: StructuredLayer[];
  setLayers: Dispatch<SetStateAction<StructuredLayer[]>>;
  busy: boolean;
  onBuild: () => void;
  onRefresh: () => void;
}) {
  return (
    <section aria-label="Build structured graph">
      <h3>Structured graph</h3>
      <p className="admin-panel__note">
        Rule-based, cited and without model calls: manual structure and parameters, repository configuration and
        operations records. Builds run in the knowledge worker; completed source syncs refresh a built workspace.
      </p>
      <ul>{layerRows(status).map((row) => <li key={row.layer}>{row.label}: {row.text}</li>)}</ul>
      <p className="admin-panel__note" role="status">{buildSummary(status?.builds[0])}</p>
      {status ? <p className="admin-panel__note">{runnerSummary(status.runner)}</p> : null}
      <fieldset style={{ border: "none", padding: 0, display: "flex", gap: "0.8rem", flexWrap: "wrap" }}>
        <legend className="admin-panel__note">Layers to build</legend>
        {STRUCTURED_LAYERS.map((layer) => (
          <label key={layer}>
            <input type="checkbox" checked={layers.includes(layer)}
              onChange={() => setLayers((previous) => toggleLayer(previous, layer))} /> {LAYER_LABELS[layer]}
          </label>
        ))}
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy || !layers.length} onClick={onBuild}>Build structured graph</button>
        <button type="button" className="admin-panel__action-btn" disabled={busy}
          onClick={onRefresh}>Refresh</button>
      </fieldset>
    </section>
  );
}

// "Handbook vs. reality": the filters and the report, or why there is none yet.
function HandbookSection({ workspaceId, filters, setFilters, onFilter, notice, report }: {
  workspaceId: string;
  filters: Filters;
  setFilters: (next: Filters) => void;
  onFilter: (event: FormEvent) => void;
  notice: string | null;
  report: HandbookReport | null;
}) {
  return (
    <section aria-label="Handbook vs. reality">
      <h3>Handbook vs. reality</h3>
      <form onSubmit={onFilter} style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        {(["parameter", "file", "section"] as const).map((key) => (
          <input key={key} className="connector-field__input" aria-label={`Filter by ${key}`}
            placeholder={key === "parameter" ? "Parameter, e.g. MaxConnections" : key === "file" ? "File, e.g. conf/server.ini"
              : "Manual section, e.g. 4.4.12"}
            value={filters[key]} onChange={(event) => setFilters({ ...filters, [key]: event.target.value })} />
        ))}
        <button type="submit" className="admin-panel__action-btn">Filter</button>
      </form>
      {notice ? <p className="admin-panel__note" role="status">{notice}</p> : null}
      {report && !notice ? <HandbookReportView report={report} workspaceId={workspaceId} /> : null}
    </section>
  );
}
