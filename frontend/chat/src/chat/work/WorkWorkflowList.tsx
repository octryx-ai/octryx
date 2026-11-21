import { useState } from "react";

import type { ProjectOption } from "../../chatOptionTypes";
import { setWorkflowActive, updateWorkflow } from "./workflowLifecycleApi";
import {
  activationConfirmation,
  isStaleRefusal,
  mappingSummary,
  modeSwitchConfirmation,
  switchedPolicy,
  workflowGroups,
  workflowMode,
  workflowModeLabel,
  workflowRefusalText,
} from "./workflowLifecycleModel";
import type { Confirmation } from "./workflowLifecycleModel";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { neutralLabel } from "./syncNames";
import "./workTransition.css";

type Pending = { workflowId: string; kind: "mode" | "activation" };

// The workflows per Workspace (work-settings-workflows-ui): name, mode (a warning badge when it executes in
// Jira), active state and what each mapped state writes. Activate/deactivate and the mode switch each ask first, listing
// exactly what will (or will no longer) be written to Jira; refusals show the server's message.
export function WorkWorkflowList({
  workflows,
  projects = [],
  onChanged,
}: {
  workflows: WorkWorkflowDefinition[];
  projects?: ProjectOption[];
  onChanged: () => Promise<void> | void;
}) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ workflowId: string; ok: boolean; text: string } | null>(null);

  const confirm = async (workflow: WorkWorkflowDefinition, kind: Pending["kind"]) => {
    setBusy(true);
    setMessage(null);
    try {
      if (kind === "mode") {
        const saved = await updateWorkflow(workflow.id, { sync_policy: switchedPolicy(workflow) }, workflow.updated_at);
        setMessage({ workflowId: workflow.id, ok: true, text: `“${saved.name || workflow.name}” now: ${workflowModeLabel(workflowMode(saved))}.` });
      } else {
        const saved = await setWorkflowActive(workflow.id, !workflow.is_active, workflow.updated_at);
        setMessage({ workflowId: workflow.id, ok: true, text: `“${saved.name || workflow.name}” is now ${saved.is_active ? "active" : "inactive"}.` });
      }
      setPending(null);
      await onChanged();
    } catch (error) {
      setMessage({ workflowId: workflow.id, ok: false, text: workflowRefusalText(error) });
      // r8: a newer version was saved elsewhere: reload it and close this confirmation, which describes the old one.
      if (isStaleRefusal(error)) {
        setPending(null);
        await Promise.resolve(onChanged()).catch(() => undefined);
      }
    } finally {
      setBusy(false);
    }
  };

  if (!workflows.length) return null;
  return (
    <div className="work-transition__block" data-testid="workflow-list">
      {workflowGroups(workflows, projects).map((group) => (
        <section key={group.key || "global"} aria-label={`Workflows of ${group.title}`} className="work-transition__block">
          <div className="work-area__eyebrow">{group.title}</div>
          {group.workflows.map((workflow) => {
            const mode = workflowMode(workflow);
            const rows = mappingSummary(workflow);
            const open = pending?.workflowId === workflow.id ? pending.kind : null;
            const confirmation = open === "mode" ? modeSwitchConfirmation(workflow) : open === "activation" ? activationConfirmation(workflow) : null;
            const shown = message?.workflowId === workflow.id ? message : null;
            return (
              <article key={workflow.id} className="work-dry-run" data-testid="workflow-card" data-workflow={workflow.id}>
                <div className="work-card__topline">
                  <strong>{workflow.name}</strong>
                  <span>
                    <span className="work-transition__caption">{neutralLabel("sync_mode")}</span>{" "}
                    <span className={`work-badge work-badge--${mode === "execute" ? "attention" : "neutral"}`} data-testid="workflow-mode">
                      {workflowModeLabel(mode)}
                    </span>{" "}
                    <span className={`work-badge work-badge--${workflow.is_active ? "active" : "neutral"}`} data-testid="workflow-active">
                      {workflow.is_active ? "active" : "inactive"}
                    </span>
                    {workflow.is_default ? <> <span className="work-badge work-badge--neutral">default</span></> : null}
                  </span>
                </div>
                {mode === "execute" ? (
                  <p className="work-area__notice" role="note" data-testid="workflow-execute-warning">
                    Applying a transition with this workflow writes to the source for every state that writes back.
                  </p>
                ) : null}
                {rows.length ? (
                  <table className="admin-panel__table" data-testid="workflow-mappings">
                    <thead><tr>
                      <th>Octryx state</th><th>{neutralLabel("source_status")}</th><th>{neutralLabel("source_transition")}</th>
                      <th>Also writes</th><th>Writes back</th>
                    </tr></thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.state}>
                          <td>{row.label}</td><td>{row.status || "–"}</td><td>{row.transition || "–"}</td>
                          <td>{row.extras || "–"}</td><td>{row.syncBack ? "yes" : "no"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="admin-panel__hint">No state is mapped to a status in the source.</p>
                )}
                <div className="work-sync-card__actions">
                  <button type="button" className="work-area__button" disabled={busy}
                    onClick={() => { setMessage(null); setPending({ workflowId: workflow.id, kind: "mode" }); }}>
                    {mode === "execute" ? "Switch to dry-run only…" : "Switch to execute…"}
                  </button>
                  <button type="button" className="work-area__button" disabled={busy}
                    onClick={() => { setMessage(null); setPending({ workflowId: workflow.id, kind: "activation" }); }}>
                    {workflow.is_active ? "Deactivate…" : "Activate…"}
                  </button>
                </div>
                {confirmation ? (
                  <ConfirmBox confirmation={confirmation} busy={busy}
                    onConfirm={() => void confirm(workflow, open!)} onCancel={() => setPending(null)} />
                ) : null}
                {shown ? (
                  <p className={shown.ok ? "work-area__notice" : "work-area__error"} role={shown.ok ? "status" : "alert"}
                    data-testid="workflow-message">
                    {shown.text}
                  </p>
                ) : null}
              </article>
            );
          })}
        </section>
      ))}
    </div>
  );
}

function ConfirmBox({ confirmation, busy, onConfirm, onCancel }: {
  confirmation: Confirmation;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="work-transition__block" role="group" aria-label={confirmation.title} data-testid="workflow-confirmation">
      <p className="work-transition__heading">{confirmation.title}</p>
      <ul className="work-detail__object-list">
        {confirmation.lines.map((line) => <li key={line}>{line}</li>)}
      </ul>
      <div>
        <button type="button" className={`work-area__button${confirmation.danger ? " is-active" : ""}`} disabled={busy} onClick={onConfirm}>
          {busy ? "Saving…" : confirmation.confirmLabel}
        </button>{" "}
        <button type="button" className="work-area__button" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
