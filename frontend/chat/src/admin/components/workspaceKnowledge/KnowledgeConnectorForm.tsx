import { useState } from "react";
import type { FormEvent } from "react";
import { MAX_SCHEDULE_INTERVAL_MINUTES, MIN_SCHEDULE_INTERVAL_MINUTES } from "./connectorTypes";
import { accessModeOf } from "./connectorConfig";
import { intervalText } from "./connectorDisplay";
import type { ConnectorConfig, ConnectorKind, SourceConnector } from "./connectorTypes";
import { SCHEDULE_PRESETS, resetScope, schedulePresetOf } from "./connectorFormModel";
import type { FormState } from "./connectorFormModel";
import { KnowledgeConnectorScopeFields } from "./KnowledgeConnectorScopeFields";
import { KnowledgeFormField } from "./KnowledgeFormField";
import { KnowledgeConnectionRepositoryForm } from "./KnowledgeConnectionRepositoryForm";
import { KnowledgeGitConnectionSelect } from "./KnowledgeGitConnectionSelect";
import { instanceSchedulerText } from "./connectorFreshness";
import type { InstanceScheduler } from "./connectorFreshness";
import { KnowledgeRestSourceFields } from "./rest/KnowledgeRestSourceFields";
import { RestSourceDryRun } from "./rest/RestSourceDryRun";
import { ConnectorAdvancedFields, ConnectorKindAndName, RepositoryFromChoice } from "./KnowledgeConnectorFormParts";
import { restDryRunDraft, restFieldErrors, submitConnectorForm, useConnectorForm } from "./useConnectorForm";

const CHECKBOX_LABEL = { display: "flex", alignItems: "center", gap: "0.35rem" } as const;

// A connector's schedule: off by default. Editing always sends it back, so a save never switches a schedule off.
// The interval is chosen from presets; a stored interval that is not a preset stays as "custom" minutes.
function ScheduleFields({ form, set, instance }: {
  form: FormState;
  set: (patch: Partial<FormState>) => void;
  instance: InstanceScheduler;
}) {
  const minutes = Number(form.scheduleInterval);
  const [customChosen, setCustomChosen] = useState(false);
  const preset = customChosen ? "custom" : schedulePresetOf(form.scheduleInterval);
  return (
    <>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
        <label className="admin-panel__muted" style={CHECKBOX_LABEL}>
          <input type="checkbox" checked={form.scheduleEnabled}
            onChange={(event) => set({ scheduleEnabled: event.target.checked })} />
          Run on a schedule
        </label>
        <select className="admin-panel__input" style={{ width: "auto" }} aria-label="Schedule interval"
          value={preset} disabled={!form.scheduleEnabled}
          onChange={(event) => {
            const value = event.target.value;
            setCustomChosen(value === "custom");
            if (value !== "custom") set({ scheduleInterval: value });
          }}>
          {SCHEDULE_PRESETS.map((option) => <option key={option.minutes} value={String(option.minutes)}>{option.label}</option>)}
          <option value="custom">Custom interval…</option>
        </select>
        {preset === "custom" ? (
          <>
            <input className="admin-panel__input" type="number" style={{ width: "7rem" }} aria-label="Schedule interval in minutes"
              min={MIN_SCHEDULE_INTERVAL_MINUTES} max={MAX_SCHEDULE_INTERVAL_MINUTES} step={15} disabled={!form.scheduleEnabled}
              value={form.scheduleInterval} onChange={(event) => set({ scheduleInterval: event.target.value })} />
            <span className="admin-panel__muted">
              minutes{Number.isInteger(minutes) && minutes > 0 ? ` (${intervalText(minutes)})` : ""} · 15 minutes to 7 days
            </span>
          </>
        ) : null}
      </div>
      {/* Only the state that changes what a schedule does is said here (automatic sync off); the rest is in the help. */}
      {instance === "off" ? (
        <div className="admin-panel__hint" style={{ margin: 0 }} data-testid="schedule-instance-hint">{instanceSchedulerText(instance)}</div>
      ) : null}
    </>
  );
}

/** The id of the source form: its submit button sits in the side panel's footer (form attribute). */
export const CONNECTOR_FORM_ID = "knowledge-connector-form";

type KnowledgeConnectorFormProps = {
  editing: SourceConnector | null;
  busy: boolean;
  // The server's refusal of the last save when it concerns the scope (shown under the scope fields).
  scopeRefusal?: string | null;
  // Whether this instance runs schedules, as the connectors listing reports it.
  instance?: InstanceScheduler;
  onSave: (connectorKey: string, config: ConnectorConfig) => Promise<boolean>;
  onCancel: () => void;
  // The Workspace the form adds to: needed for "From a connection".
  workspaceId?: string;
  // After "From a connection" saved to at least one Workspace.
  onConnectionSaved?: () => void;
  // Whether the form shows its own buttons ("From a connection" has its own save), so the panel hides its footer.
  onOwnActions?: (own: boolean) => void;
  // Presentation only (the server decides, 403): whether the caller is a platform admin (REST visibility "workspace").
  isPlatformAdmin?: boolean;
  // The last refused save (any error); a REST source shows it at its field.
  saveRefusal?: unknown;
};

// Create or replace one connector's configuration. The kind and name of an existing connector are fixed.
// A new Git repository comes from a public URL, or from a Bitbucket connection (its own picker and save, which can
// add it to several Workspaces at once). The panel title names the form and its footer holds Cancel and the submit
// button, so the form itself has neither a title nor buttons and no extra indent.
export function KnowledgeConnectorForm({
  editing, busy, onSave, onCancel, instance = "unknown", scopeRefusal = null, workspaceId, onConnectionSaved,
  onOwnActions, isPlatformAdmin = false, saveRefusal = null,
}: KnowledgeConnectorFormProps) {
  const s = useConnectorForm({ editing, workspaceId, onOwnActions, isPlatformAdmin, saveRefusal });
  const { asked, form, set, repositoryFrom, setRepositoryFrom, connections, fromConnection, problem, gitByUrl, git, linked, setConnection, rest,
    catalog, restRefusal, setRestRefusal } = s;
  const { restProblems, restErrors } = restFieldErrors(s, isPlatformAdmin);
  const restDraft = () => restDryRunDraft(s, restProblems);
  const submit = (event: FormEvent) => submitConnectorForm(event, s, { editing, restProblems, onSave });

  const changeKind = (kind: ConnectorKind) => set(resetScope(kind));

  return (
    <form id={CONNECTOR_FORM_ID} className="knowledge-connector-form" onSubmit={(event) => void submit(event)}>
      <div className="admin-panel__stack admin-panel__stack--compact">
        <ConnectorKindAndName form={form} set={set} editing={editing} fromConnection={fromConnection} changeKind={changeKind} />
        {!editing && form.kind === "git_repository" && workspaceId && connections.length ? (
          <RepositoryFromChoice repositoryFrom={repositoryFrom} setRepositoryFrom={setRepositoryFrom} />
        ) : null}
        {fromConnection && workspaceId ? (
          <KnowledgeConnectionRepositoryForm workspaceId={workspaceId} connections={connections}
            preselectedConnectionId={asked?.connectionId || undefined}
            onSaved={() => onConnectionSaved?.()} onCancel={onCancel} />
        ) : (
          <>
            {rest ? (
              <KnowledgeRestSourceFields form={form.rest} set={(next) => { setRestRefusal(null); set({ rest: next }); }} catalog={catalog}
                errors={restErrors} isPlatformAdmin={isPlatformAdmin} editing={Boolean(editing)} />
            ) : <KnowledgeConnectorScopeFields form={form} set={set}
              lockedUrl={Boolean(editing && accessModeOf(editing))} urlProblem={git.urlRefused} />}
            {gitByUrl ? (
              <KnowledgeGitConnectionSelect candidates={git.candidates} connectionId={form.connectionId}
                onChange={setConnection} editing={Boolean(editing)} linked={linked} />
            ) : null}
            {rest && restRefusal && !restRefusal.field ? <p className="rst-error" role="alert">{restRefusal.text}</p> : null}
            {scopeRefusal ? (
              <div className="admin-panel__hint" role="alert" style={{ margin: 0 }} data-testid="scope-refusal">{scopeRefusal}</div>
            ) : null}
            <KnowledgeFormField label="State">
              <select className="admin-panel__input" style={{ width: "auto" }} value={form.state} aria-label="State"
                onChange={(event) => set({ state: event.target.value as FormState["state"] })}>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
              </select>
            </KnowledgeFormField>
            <ScheduleFields form={form} set={set} instance={instance} />
            <ConnectorAdvancedFields form={form} set={set} />
            {problem ? <div className="admin-panel__hint" role="alert" style={{ margin: 0 }}>{problem}</div> : null}
            {rest && workspaceId ? (
              <RestSourceDryRun workspaceId={workspaceId} isPlatformAdmin={isPlatformAdmin} draft={restDraft} onRefused={setRestRefusal}
                draftKey={JSON.stringify(form.rest)} />
            ) : null}
          </>
        )}
      </div>
    </form>
  );
}
