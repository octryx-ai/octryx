import { useState, type ReactNode } from "react";

import { ConnectorBrandIcon } from "../../../admin/components/ConnectorBrandIcon";

import type { IntakeConnection } from "./workIntakeTypes";
import { AUTOMATION_CHOICES, SCHEDULE_CHOICES, jqlPreview, previewFacts, toggled } from "./workIntakeDraft";
import type { IntakeDiscovery, IntakeDraft } from "./workIntakeDraft";
import { connectionLabel, scheduleLabel } from "./workIntakeModel";
import { IncidentAnalysisSettingsCard } from "../incident/IncidentAnalysisSettingsCard";
import { TriageRoutingSettingsCard } from "./TriageRoutingSettingsCard";
import { neutralLabel } from "../syncNames";
import { IntakeSyncField } from "./IntakeSyncField";

// The five panes of the intake setup drawer (§3.2): Source, What, When, How, Preview. Each edits one part of the
// draft through `update`; nothing here talks to the server except the analysis card of a ServiceNow intake and the
// Workspace's triage routing card (spec B/C §1).

type Update = (patch: Partial<IntakeDraft>) => void;
type Choice = { key: string; title: string; hint: string; selected: boolean; onPick: () => void; icon?: ReactNode };

const csv = (value: string) => value.split(",").map((entry) => entry.trim()).filter(Boolean);
const list = (value: string[] | string | undefined) => (Array.isArray(value) ? value : []);

function Choices({ items, columns = 3 }: { items: Choice[]; columns?: number }) {
  return (
    <div className="work-intake__choices" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
      {items.map((item) => (
        <button key={item.key} type="button" className={`work-intake__choice ${item.selected ? "is-selected" : ""}`}
          aria-pressed={item.selected} onClick={item.onPick}>
          <b className={item.icon ? "work-intake__source" : undefined}>{item.icon}{item.title}</b><span>{item.hint}</span>
        </button>
      ))}
    </div>
  );
}

function Chips({ values, selected, onToggle, label }: { values: string[]; selected: string[]; onToggle: (value: string) => void; label: string }) {
  return (
    <div className="work-intake__chips" role="group" aria-label={label}>
      {values.map((value) => (
        <button key={value} type="button" className={`work-intake__chip ${selected.includes(value) ? "is-on" : ""}`}
          aria-pressed={selected.includes(value)} onClick={() => onToggle(value)}>{value}</button>
      ))}
    </div>
  );
}

function AddChip({ onAdd }: { onAdd: (value: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [value, setValue] = useState("");
  if (!adding) return <button type="button" className="work-intake__chip" onClick={() => setAdding(true)}>+ add</button>;
  const done = () => { if (value.trim()) onAdd(value.trim()); setValue(""); setAdding(false); };
  return <input className="work-intake__chip-input" aria-label="New label" autoFocus value={value}
    onChange={(event) => setValue(event.target.value)} onBlur={done}
    onKeyDown={(event) => { if (event.key === "Enter") done(); if (event.key === "Escape") setAdding(false); }} />;
}

export function SourceStep({ draft, connections, update, onOpenConnectors }: {
  draft: IntakeDraft; connections: Array<IntakeConnection & { kind: string; label: string; hint: string }>;
  update: Update; onOpenConnectors: () => void;
}) {
  return (
    <>
      <p className="admin-panel__hint">Pick one of this Workspace's connections.</p>
      {connections.length ? (
        <Choices columns={2} items={connections.map((connection) => ({
          key: `${connection.kind}:${connection.id}`,
          title: `${connection.label} – ${connectionLabel(connection)}`,
          hint: connection.hint,
          icon: <ConnectorBrandIcon kind={connection.kind} label={connection.label} />,
          selected: draft.source_type === connection.kind && draft.connection_id === connection.id,
          onPick: () => update({ source_type: connection.kind, connection_id: connection.id }),
        }))} />
      ) : <p className="admin-panel__hint">This Workspace has no work source connection yet (Jira, ServiceNow or a REST API).</p>}
      <p className="work-intake__muted">Missing a connection? <button type="button" className="work-link" onClick={onOpenConnectors}>Add it in Workspace → Connectors</button></p>
    </>
  );
}

export function WhatStep({ draft, found, count, update }: {
  draft: IntakeDraft; found: IntakeDiscovery | null; count: number | null; update: Update;
}) {
  const what = draft.what;
  const set = (patch: Record<string, string[] | string>) => update({ what: { ...what, ...patch } });
  if (draft.source_type === "servicenow") {
    const groups = Array.from(new Set([...(found?.assignment_groups ?? []), ...list(what.assignment_groups)]));
    const states = Array.from(new Set([...(found?.excluded_states ?? []), ...list(what.excluded_states)]));
    return (
      <>
        <label className="admin-panel__field"><span>Tables</span></label>
        <Chips label="Tables" values={found?.tables ?? ["incident", "change_request"]} selected={list(what.tables)}
          onToggle={(value) => set({ tables: toggled(list(what.tables), value) })} />
        <label className="admin-panel__field"><span>Assignment groups</span></label>
        {groups.length ? <Chips label="Assignment groups" values={groups} selected={list(what.assignment_groups)}
          onToggle={(value) => set({ assignment_groups: toggled(list(what.assignment_groups), value) })} />
          : <p className="work-intake__muted">All groups the connection may read.</p>}
        <label className="admin-panel__field"><span>Skip records in state</span></label>
        <Chips label="Skip records in state" values={states} selected={list(what.excluded_states)}
          onToggle={(value) => set({ excluded_states: toggled(list(what.excluded_states), value) })} />
        <details className="work-intake__adv"><summary>Advanced: encoded query</summary>
          <label className="admin-panel__field"><span>Encoded query</span>
            <input className="work-mono" value={typeof what.sysparm_query === "string" ? what.sysparm_query : ""}
              onChange={(event) => set({ sysparm_query: event.target.value })} /></label>
        </details>
      </>
    );
  }
  const projects = found?.projects ?? list(what.project_keys).map((key) => ({ key, name: key }));
  const types = list(what.issue_types);
  const typeValue = types.join(", ");
  const typeOptions = Array.from(new Set([...(found?.issue_types ?? []), ...(types.length > 1 ? [typeValue] : types)]));
  return (
    <>
      <label className="admin-panel__field"><span>Projects</span></label>
      <div className="work-intake__chips" role="group" aria-label="Projects">
        {projects.map((project) => {
          const on = list(what.project_keys).includes(project.key);
          return <button key={project.key} type="button" className={`work-intake__chip ${on ? "is-on" : ""}`} aria-pressed={on}
            onClick={() => set({ project_keys: toggled(list(what.project_keys), project.key) })}>
            {project.name && project.name !== project.key ? `${project.key} · ${project.name}` : project.key}</button>;
        })}
      </div>
      <p className="work-intake__muted">Only projects the connection may reach are offered.</p>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field"><span>Issue types</span>
          <select value={typeValue} onChange={(event) => set({ issue_types: csv(event.target.value) })}>
            <option value="">All</option>
            {typeOptions.map((option) => <option key={option} value={option}>{option}</option>)}
          </select></label>
        <label className="admin-panel__field"><span>Only with label</span>
          <input value={list(what.labels_include).join(", ")} onChange={(event) => set({ labels_include: csv(event.target.value) })} /></label>
        <label className="admin-panel__field"><span>Skip items with label</span>
          <input value={list(what.labels_exclude).join(", ")} onChange={(event) => set({ labels_exclude: csv(event.target.value) })} /></label>
        <label className="admin-panel__field"><span>Components</span>
          <input value={list(what.components_include).join(", ")} onChange={(event) => set({ components_include: csv(event.target.value) })} /></label>
      </div>
      {count !== null ? <div className="work-note" data-testid="intake-match-count">≈ <b>{count} items</b> match right now.</div> : null}
      <details className="work-intake__adv"><summary>Advanced: JQL</summary>
        <label className="admin-panel__field"><span>Additional JQL</span>
          <input className="work-mono" value={typeof what.jql === "string" ? what.jql : ""} onChange={(event) => set({ jql: event.target.value })} /></label>
        <pre className="work-intake__code"><span className="work-intake__code-comment">-- what is sent (the connection's projects always wrap your JQL)</span>{"\n"}{jqlPreview(what)}</pre>
      </details>
    </>
  );
}

export function WhenStep({ draft, update }: { draft: IntakeDraft; update: Update }) {
  const custom = draft.schedule.preset === "custom";
  return (
    <>
      <Choices items={SCHEDULE_CHOICES.map((choice) => ({ key: choice.preset, title: choice.label, hint: choice.hint,
        selected: draft.schedule.preset === choice.preset, onPick: () => update({ schedule: { preset: choice.preset, cron: null } }) }))} />
      <details className="work-intake__adv" open={custom}><summary>Advanced: custom cron</summary>
        <label className="admin-panel__field"><span>Cron</span>
          <input className="work-mono" value={draft.schedule.cron ?? ""} aria-label="Cron"
            onChange={(event) => update({ schedule: event.target.value.trim()
              ? { preset: "custom", cron: event.target.value } : { preset: "manual", cron: null } })} /></label>
      </details>
    </>
  );
}

// `sourceParts`: a source's own settings below the shared automation choice (Custom REST: mapping, write-back, dry run);
// they replace the discovered status table.
export function HowStep({ draft, found, workspaceId, update, sourceParts, workflowMode, syncError }: {
  draft: IntakeDraft; found: IntakeDiscovery | null; workspaceId: string; update: Update; sourceParts?: ReactNode;
  workflowMode?: string | null; syncError?: string;
}) {
  const how = draft.how;
  const setHow = (patch: Partial<IntakeDraft["how"]>) => update({ how: { ...how, ...patch } });
  const states = found?.work_states ?? [];
  const statuses = Array.from(new Set([...(found?.statuses ?? []).map((entry) => entry.name), ...Object.keys(how.status_mapping)]));
  const jira = draft.source_type === "jira";
  return (
    <>
      <label className="admin-panel__field"><span>When an item arrives</span></label>
      <Choices items={AUTOMATION_CHOICES.map((choice) => ({ key: choice.mode, title: choice.label, hint: choice.hint,
        selected: how.automation_mode === choice.mode, onPick: () => setHow({ automation_mode: choice.mode }) }))} />
      {jira ? (
        <>
          <label className="admin-panel__field"><span>Automation label</span></label>
          <div className="work-intake__chips">
            {how.automation_labels.map((label) => <button key={label} type="button" className="work-intake__chip is-on" aria-pressed="true"
              title="Remove" onClick={() => setHow({ automation_labels: how.automation_labels.filter((entry) => entry !== label) })}>{label}</button>)}
            <AddChip onAdd={(label) => setHow({ automation_labels: Array.from(new Set([...how.automation_labels, label])) })} />
          </div>
          <div className="admin-panel__section-header work-intake__subhead"><span>Fields (discovered from the connection)</span></div>
          <div className="work-intake__map">
            {(Array.isArray(found?.fields) ? found.fields : []).map((role) => {
              const mapped = Boolean(how.field_mapping[role.role]);
              const toggle = () => {
                const next = { ...how.field_mapping };
                if (mapped) delete next[role.role]; else if (role.field) next[role.role] = role.field.id;
                setHow({ field_mapping: next });
              };
              return (
                <div key={role.role} data-testid={`intake-field-${role.role}`}>
                  <span>{role.label}</span><span className="work-intake__arrow">→</span>
                  {role.field ? <span><abbr title={`Jira field id ${role.field.id}`}>{role.field.name}</abbr></span>
                    : <span className="work-intake__off">not found</span>}
                  <button type="button" className={`work-badge ${mapped ? "work-badge--active" : "work-badge--neutral"}`}
                    disabled={!role.field} onClick={toggle}>{mapped ? "mapped" : "off"}</button>
                </div>
              );
            })}
          </div>
        </>
      ) : null}
      {sourceParts ?? (<>
      <div className="admin-panel__section-header work-intake__subhead"><span>{neutralLabel("source_status")} → Octryx state (discovered)</span></div>
      <div className="work-intake__map">
        {statuses.map((status) => (
          <div key={status}>
            <span>{status}</span><span className="work-intake__arrow">→</span>
            <select aria-label={`Work state for ${status}`} value={how.status_mapping[status] ?? ""}
              onChange={(event) => setHow({ status_mapping: { ...how.status_mapping, [status]: event.target.value } })}>
              <option value="">By its category</option>
              {states.map((state) => <option key={state.key} value={state.key}>{state.label}</option>)}
            </select><span />
          </div>
        ))}
      </div>
      </>)}
      <IntakeSyncField mode={how.sync_mode} workflowMode={workflowMode} workspaceId={workspaceId} error={syncError}
        onChange={(mode) => setHow({ sync_mode: mode })} />
      {draft.source_type === "servicenow" && workspaceId ? <IncidentAnalysisSettingsCard projectId={workspaceId} /> : null}
      {workspaceId ? <TriageRoutingSettingsCard projectId={workspaceId} /> : null}
    </>
  );
}

export type PreviewResult = { summary: Record<string, unknown>; items: Array<Record<string, unknown>> };

export function PreviewStep({ draft, preview, found }: { draft: IntakeDraft; preview: PreviewResult | null; found: IntakeDiscovery | null }) {
  if (!preview) return <p className="admin-panel__hint">Running the preview…</p>;
  const facts = previewFacts(preview.summary);
  const label = (key: unknown) => found?.work_states.find((state) => state.key === key)?.label ?? String(key ?? "–");
  const show = (value: number | null) => (value === null ? "–" : String(value));
  const schedule = draft.schedule.preset === "manual" ? "" : ` and then ${scheduleLabel(draft.schedule).toLowerCase()}`;
  return (
    <>
      <div className="work-intake__kv" data-testid="intake-preview-facts">
        <div><b>Would import</b>{show(facts.wouldImport)}</div><div><b>Already in Work</b>{show(facts.already)}</div>
        {draft.source_type === "jira"
          ? <div><b>Pending next run</b>{facts.pending}</div>
          : <div><b>Skipped (closed)</b>{show(facts.skipped)}</div>}
        <div><b>Outside connection scope</b>{facts.outside}</div>
        {facts.automation ? <div><b>Automation label</b>{facts.automation}</div> : null}
      </div>
      <table className="admin-panel__table work-cards">
        <thead><tr><th>Key</th><th>Title</th><th>Status</th><th>Becomes</th></tr></thead>
        <tbody>
          {preview.items.map((item) => (
            <tr key={String(item.source_key)}>
              <td data-label="Key" className="work-mono">{String(item.source_key ?? "")}</td>
              <td data-label="Title">{String(item.title ?? "")}</td>
              <td data-label="Status">{String(item.source_status ?? "–")}</td>
              <td data-label="Becomes">{label(item.work_state)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="work-intake__muted">Preview only; nothing was written.{draft.is_active ? "" : ` Enable starts the first run now${schedule}.`}</p>
    </>
  );
}
