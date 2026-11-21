import { useEffect, useState } from "react";

import { readJson } from "../../chatApiClient";
import { startableWorkflowsPath } from "../../workflowRun/workflowRunRequests";
import { type StartableWorkflow } from "../../workflowRun/workflowRunTypes";
import {
  NO_FOLLOW_UP,
  readTriageRouting,
  triageRoutingError,
  triageRoutingPath,
  triageRoutingPayload,
  type RouteRow,
  type TriageRouting,
} from "./triageRoutingModel";

type Message = { ok: boolean; text: string };

// Which workflow a triaged Work item continues with, per type (spec B/C §1). The triage's
// confirmed Definition of Ready names the type; its follow-up run starts once, for the same item, requester and
// responsible person. A type without a workflow starts nothing (the triage run says "No route for type …").
export function TriageRoutingSettingsCard({ projectId }: { projectId: string }) {
  const [routing, setRouting] = useState<TriageRouting | null>(null);
  const [workflows, setWorkflows] = useState<StartableWorkflow[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);

  useEffect(() => {
    let current = true;
    setRouting(null); setProblem(null); setMessage(null);
    readJson<unknown>(triageRoutingPath(projectId)).then((payload) => {
      if (!current) return;
      const read = readTriageRouting(payload);
      if (read) setRouting(read);
      else setProblem("The server's answer was not the triage routing.");
    }).catch((error) => { if (current) setProblem(error instanceof Error ? error.message : "The triage routing could not be loaded."); });
    readJson<{ workflows: StartableWorkflow[] }>(startableWorkflowsPath(projectId))
      .then((payload) => { if (current) setWorkflows(payload.workflows ?? []); })
      .catch(() => { if (current) setWorkflows([]); });
    return () => { current = false; };
  }, [projectId]);

  if (problem) return <p className="work-area__error" role="alert" data-testid="triage-routing-error">{problem}</p>;
  if (!routing) return <p className="work-detail__empty" role="status">Loading the triage routing…</p>;

  const rows = routing.rows;
  const error = triageRoutingError(rows);
  const readOnly = !routing.canEdit;
  const setRows = (next: RouteRow[]) => { setRouting({ ...routing, rows: next }); setMessage(null); };
  const change = (index: number, patch: Partial<RouteRow>) => setRows(rows.map((row, at) => (at === index ? { ...row, ...patch } : row)));
  const options = workflows.filter((workflow) => workflow.key !== "jira-intake-triage");
  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const payload = await readJson<unknown>(triageRoutingPath(projectId), {
        method: "PUT", body: JSON.stringify(triageRoutingPayload(rows, routing.defaults)),
      });
      const read = readTriageRouting(payload);
      if (read) setRouting(read);
      setMessage({ ok: true, text: "Saved. Triage runs that complete from now on use these routes." });
    } catch (failure) {
      setMessage({ ok: false, text: failure instanceof Error ? failure.message : "The triage routing could not be saved." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="work-config__section" aria-label="Triage routing" data-testid="triage-routing">
      <header className="work-config__header">
        <div>
          <div className="work-area__eyebrow">Triage routing</div>
          <h2>After the triage, by type</h2>
        </div>
      </header>
      <p className="work-detail__empty">
        When a triage is confirmed ready, its type starts one follow-up run for the same item, requester and
        responsible person. Incidents skip the triage and start with the incident route.
      </p>
      <div className="work-intake__map" data-testid="triage-routing-rows">
        {rows.map((row, index) => (
          <div key={index}>
            <input className="admin-panel__input" aria-label="Type" value={row.type} disabled={readOnly} data-testid={`triage-route-type-${index}`}
              onChange={(event) => change(index, { type: event.target.value })} />
            <span className="work-intake__arrow">→</span>
            <select aria-label={`Follow-up for ${row.type || "this type"}`} value={row.workflowKey} disabled={readOnly}
              data-testid={`triage-route-workflow-${index}`} onChange={(event) => change(index, { workflowKey: event.target.value })}>
              <option value={NO_FOLLOW_UP}>No follow-up</option>
              {row.workflowKey && !options.some((workflow) => workflow.key === row.workflowKey)
                ? <option value={row.workflowKey}>{`${row.workflowKey} (not published here)`}</option> : null}
              {options.map((workflow) => <option key={workflow.key} value={workflow.key}>{workflow.title}</option>)}
            </select>
            {readOnly ? <span /> : (
              <button type="button" className="work-badge work-badge--neutral" onClick={() => setRows(rows.filter((_, at) => at !== index))}>
                remove
              </button>
            )}
          </div>
        ))}
      </div>
      {error ? <p className="work-area__error" role="alert" data-testid="triage-routing-invalid">{error}</p> : null}
      {readOnly ? <p className="work-detail__empty">Read-only: Workspace admins and owners change the routing.</p> : (
        <div>
          <button type="button" className="work-area__button" onClick={() => setRows([...rows, { type: "", workflowKey: NO_FOLLOW_UP }])}>
            Add a type
          </button>{" "}
          <button type="button" className="work-area__button is-active" disabled={busy || Boolean(error)} onClick={() => void save()}
            data-testid="triage-routing-save">
            {busy ? "Saving…" : "Save triage routing"}
          </button>
        </div>
      )}
      {message ? <p className={message.ok ? "work-area__notice" : "work-area__error"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
    </section>
  );
}
