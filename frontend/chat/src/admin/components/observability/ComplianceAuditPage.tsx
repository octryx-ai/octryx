import { useCallback, useEffect, useRef, useState } from "react";

import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { formatDateTime } from "../../utils/dateTime";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import {
  EMPTY_FILTERS, complianceQuery, detailEntries, eventTypeLabel, hiddenFieldsText, outcomeTone, resourceLabel,
  type ComplianceFilterOptions, type ComplianceFilters, type ComplianceRecord, type ComplianceRecordPage,
} from "./complianceAuditModel";
import { formatTime, readErrorMessage } from "./obFormat";
import { Badge, WorkspaceSelect } from "./obUi";
import "./observability.css";

const BASE = "/api/v1/admin/compliance-audit";

export function ComplianceAuditPage({ readJson }: { readJson: ReadJsonFn }) {
  const [options, setOptions] = useState<ComplianceFilterOptions | null>(null);
  const [filters, setFilters] = useState<ComplianceFilters>(EMPTY_FILTERS);
  const [records, setRecords] = useState<ComplianceRecord[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<ComplianceRecord | null>(null);

  useEffect(() => {
    readJson<ComplianceFilterOptions>(`${BASE}/kinds`).then(setOptions)
      .catch((failure) => setError(readErrorMessage(failure, "The compliance audit could not be loaded.")));
  }, [readJson]);

  // Every filter change starts a new generation; a response of an older one (a slow first page, a pending
  // "Load more") is dropped instead of replacing or extending the rows of the current filters.
  const generation = useRef(0);
  const fetchPage = useCallback(async (cursor: string | null) => {
    const mine = generation.current;
    setBusy(true);
    try {
      const page = await readJson<ComplianceRecordPage>(`${BASE}/records?${complianceQuery(filters, cursor)}`);
      if (mine !== generation.current) return;
      setRecords((current) => (cursor && current ? [...current, ...page.records] : page.records));
      setNext(page.next_cursor);
      setError(null);
    } catch (failure) {
      if (mine !== generation.current) return;
      setRecords((current) => current ?? []);
      setError(readErrorMessage(failure, "The compliance audit could not be loaded."));
    } finally {
      if (mine === generation.current) setBusy(false);
    }
  }, [readJson, filters]);

  useEffect(() => {
    if (!options) return;
    generation.current += 1;
    setRecords(null);
    setNext(null);
    setOpen(null);
    void fetchPage(null);
  }, [options, fetchPage]);

  const update = (patch: Partial<ComplianceFilters>) => setFilters((current) => ({ ...current, ...patch }));

  return (
    <div className="ob-page" data-testid="compliance-audit">
      <div className="ob-toolbar ob-toolbar--filters">
        <WorkspaceSelect projects={options?.workspaces ?? []} value={filters.workspaceId}
          onChange={(workspaceId) => update({ workspaceId })} />
        <select className="admin-users__toolbar-select" aria-label="Kind" value={filters.eventType}
          onChange={(event) => update({ eventType: event.target.value })}>
          <option value="">All kinds</option>
          {(options?.event_types ?? []).map((type) => <option key={type} value={type}>{eventTypeLabel(type)}</option>)}
        </select>
        <input className="admin-users__toolbar-input" type="date" aria-label="From" value={filters.from}
          max={filters.to || undefined} onChange={(event) => update({ from: event.target.value })} />
        <input className="admin-users__toolbar-input" type="date" aria-label="To" value={filters.to}
          min={filters.from || undefined} onChange={(event) => update({ to: event.target.value })} />
      </div>
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      <table className="admin-panel__table ob-cards">
        <thead><tr><th>Time</th><th>Kind</th><th>Outcome</th><th>Workspace</th><th>Actor</th><th>Resource</th></tr></thead>
        <tbody>
          {(records ?? []).map((record) => <RecordRow key={record.id} record={record} onOpen={() => setOpen(record)} />)}
          {records && !records.length ? (
            <tr><td colSpan={6} className="admin-panel__cell--muted">No compliance records match these filters.</td></tr>
          ) : null}
          {records === null && !error ? (
            <tr><td colSpan={6} className="admin-panel__cell--muted">Loading records…</td></tr>
          ) : null}
        </tbody>
      </table>
      {next ? (
        <div className="ob-between">
          <span />
          <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid="compliance-more"
            onClick={() => void fetchPage(next)}>{busy ? "Loading…" : "Load more"}</button>
        </div>
      ) : null}
      {open ? <RecordDrawer record={open} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}

function RecordRow({ record, onOpen }: { record: ComplianceRecord; onOpen: () => void }) {
  return (
    <tr className="ob-row-button" tabIndex={0} onClick={onOpen}
      onKeyDown={(event) => { if (event.key === "Enter") onOpen(); }}>
      <td data-label="Time" className="ob-nowrap">{formatTime(record.created_at)}</td>
      <td data-label="Kind">{eventTypeLabel(record.event_type)}</td>
      <td data-label="Outcome">{record.outcome ? <Badge tone={outcomeTone(record.outcome)}>{record.outcome}</Badge> : "–"}</td>
      <td data-label="Workspace">{record.workspace?.name ?? <span className="ob-muted">Platform</span>}</td>
      <td data-label="Actor">{record.actor?.display_name ?? <span className="ob-muted">System</span>}</td>
      <td data-label="Resource"><span className="ob-object">{record.resource_type}
        <span className="ob-muted ob-clip" title={resourceLabel(record)}>{resourceLabel(record)}</span></span></td>
    </tr>
  );
}

function RecordDrawer({ record, onClose }: { record: ComplianceRecord; onClose: () => void }) {
  const details = detailEntries(record.details);
  const hidden = hiddenFieldsText(record.hidden_field_count);
  return (
    <SettingsDrawer eyebrow={`Compliance audit · ${formatTime(record.created_at)}`}
      title={`${eventTypeLabel(record.event_type)} · ${resourceLabel(record)}`} size="detail" onClose={onClose}
      footer={<button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>}>
      <div className="ob-kv">
        <div><b>When</b>{record.created_at ? formatDateTime(record.created_at) : "–"}</div>
        <div><b>Outcome</b>{record.outcome ?? "–"}</div>
        <div><b>Workspace</b>{record.workspace?.name ?? "Platform"}</div>
        <div><b>Actor</b>{record.actor?.display_name ?? "System"}{record.actor_role ? ` (${record.actor_role})` : ""}</div>
        <div><b>Resource</b>{record.resource_type}{record.resource_id ? ` · ${record.resource_id}` : ""}</div>
        <div><b>Classification</b>{record.classification_level ?? "–"}</div>
        <div><b>Request</b>{record.request_id ?? "–"}</div>
        <div><b>Session</b>{record.session_id ?? "–"}</div>
      </div>
      <section className="work-detail__section">
        <h3>Details</h3>
        {details.length ? (
          <div className="ob-kv" data-testid="compliance-details">
            {details.map((entry) => (
              <div key={entry.key}><b>{entry.key}</b><code className="ob-mono">{entry.value}</code></div>
            ))}
          </div>
        ) : null}
        {hidden ? <p className="ob-muted" data-testid="compliance-hidden">{hidden}</p> : null}
        {!details.length && !hidden ? <p className="ob-muted">No details recorded.</p> : null}
      </section>
    </SettingsDrawer>
  );
}
