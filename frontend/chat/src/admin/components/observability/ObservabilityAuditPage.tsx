import { useCallback, useEffect, useState } from "react";

import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { auditChangeLabel, auditDiffLines, auditObjectParts, auditQuery, type AuditItem, type AuditPage } from "./auditModel";
import { formatTime, readErrorMessage } from "./obFormat";
import { Badge, Segmented, type ProjectOption } from "./obUi";
import { Pager } from "./obPager";
import "./observability.css";
import { formatDateTime } from "../../utils/dateTime";

type Props = { projects: ProjectOption[]; readJson: ReadJsonFn };

const WINDOWS = [
  { value: 7, label: "7 d" },
  { value: 30, label: "30 d" },
  { value: 90, label: "90 d" },
];

// Observability → Audit log: administrative changes only. Runtime decisions are in Decisions.
export function ObservabilityAuditPage({ readJson }: Props) {
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [windowDays, setWindowDays] = useState(30);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AuditPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<AuditItem | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await readJson<AuditPage>(`/api/v1/observability/audit?${auditQuery({ category, query, page, windowDays })}`));
      setError(null);
    } catch (loadError) {
      setError(readErrorMessage(loadError, "The audit log could not be loaded."));
    }
  }, [readJson, category, query, page, windowDays]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query]);

  const exportCsv = () => exportAuditCsv(auditQuery({ category, query, page: 1, windowDays }), setError);

  const filter = (apply: () => void) => {
    apply();
    setPage(1);
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="ob-page" data-testid="observability-audit">
      <div className="ob-toolbar ob-toolbar--filters">
        <input className="admin-users__toolbar-input" type="search" aria-label="Search audit log"
          placeholder="Search actor or object" value={query} onChange={(event) => filter(() => setQuery(event.target.value))} />
        <Segmented label="Category" value={category} onChange={(value) => filter(() => setCategory(value))}
          options={["", ...(data?.categories ?? [])].map((item) => ({ value: item, label: item || "All" }))} />
        <Segmented label="Window" options={WINDOWS} value={windowDays} onChange={(value) => filter(() => setWindowDays(value))} />
        <button type="button" className="admin-panel__action-btn ob-toolbar__end" onClick={() => void exportCsv()}>Export</button>
      </div>
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      <table className="admin-panel__table ob-cards">
        <thead><tr><th>Time</th><th>Actor</th><th>Change</th><th>Object</th><th>Category</th></tr></thead>
        <tbody>
          {(data?.items ?? []).map((item) => <AuditRow key={item.id} item={item} onOpen={() => setOpen(item)} />)}
          {data && !data.items.length ? (
            <tr><td colSpan={5} className="admin-panel__cell--muted">No administrative changes match in this window.</td></tr>
          ) : null}
        </tbody>
      </table>
      <div className="ob-between">
        <span className="ob-muted">{data ? `${data.total} changes in the last ${data.window_days} days` : ""}</span>
        <Pager page={page} pages={pages} onPage={setPage} />
      </div>
      {open ? <AuditDrawer item={open} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}

// The CSV of the filtered log, downloaded as audit-log.csv.
async function exportAuditCsv(search: string, setError: (error: string) => void) {
  try {
    const response = await fetch(`/api/v1/observability/audit/export?${search}`,
      { method: "POST", credentials: "same-origin" });
    if (!response.ok) throw new Error(`Export failed (${response.status})`);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "audit-log.csv";
    link.click();
    URL.revokeObjectURL(url);
  } catch (exportError) {
    setError(readErrorMessage(exportError, "The export failed."));
  }
}

function AuditRow({ item, onOpen }: { item: AuditItem; onOpen: () => void }) {
  return (
    <tr className="ob-row-button" tabIndex={0} onClick={onOpen}
      onKeyDown={(event) => { if (event.key === "Enter") onOpen(); }}>
      <td data-label="Time" className="ob-nowrap">{formatTime(item.time)}</td>
      <td data-label="Actor">{item.actor}</td>
      <td data-label="Change"><AuditChange change={item.change} details={item.details} /></td>
      <td data-label="Object"><AuditObject object={item.object} /></td>
      <td data-label="Category"><Badge tone="neutral">{item.category}</Badge></td>
    </tr>
  );
}

function AuditDrawer({ item: open, onClose }: { item: AuditItem; onClose: () => void }) {
  return (
    <SettingsDrawer eyebrow={`Audit · ${formatTime(open.time)} · ${open.category}`} title={`${open.actor} · ${auditChangeLabel(open.change, open.details)}`}
      size="detail" onClose={onClose}
      footer={<button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>}>
      <div className="ob-kv">
        <div><b>Actor</b>{open.actor}</div>
        <div><b>When</b>{open.time ? formatDateTime(open.time) : "–"}</div>
        <div><b>From</b>{open.ip_address ?? "–"}</div>
        <div><b>Category</b>{open.category}</div>
      </div>
      <section className="work-detail__section"><h3>Object</h3><div>{open.object ?? "–"}</div></section>
      <section className="work-detail__section">
        <h3>Change</h3>
        <pre className="ob-diff">
          {auditDiffLines(open.details, open.change).map((line, index) => (
            <span key={index} className={line.kind === "same" ? undefined : line.kind}>{line.text}{"\n"}</span>
          ))}
        </pre>
      </section>
    </SettingsDrawer>
  );
}

// A request line is shown as code; an event name reads as words with the raw name as its tooltip.
function AuditChange({ change, details }: { change: string; details: Record<string, unknown> }) {
  const label = auditChangeLabel(change, details);
  if (/^(GET|POST|PUT|PATCH|DELETE) \//.test(change)) return <code className="ob-mono ob-clip" title={change}>{change}</code>;
  return <span title={label === change ? undefined : change}>{label}</span>;
}

function AuditObject({ object }: { object: string | null }) {
  const parts = auditObjectParts(object);
  if (!parts) return <span className="ob-muted">–</span>;
  return (
    <span className="ob-object" title={parts.full}>
      {parts.kind}
      {parts.id ? <code className="ob-mono ob-muted">{parts.id}</code> : null}
    </span>
  );
}
