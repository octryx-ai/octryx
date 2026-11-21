import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";

import { StatusLabel } from "../../../layout/StatusLabel";
import { readJson } from "../../utils/adminPanelHelpers";
import {
  changeText,
  deviationOf,
  deviationPath,
  draftOf,
  draftProblem,
  fieldState,
  LEVEL_LABELS,
  levelOptions,
  SCOPED_USES,
  scopeOf,
  scopeTitle,
  USE_LABELS,
  type NarrowDraft,
  type ScopedUse,
  type WorkspaceConnection,
} from "./workspaceNarrowModel";

type Props = { workspaceId: string; workspaceName?: string; connection: WorkspaceConnection; onSaved: (next: WorkspaceConnection) => void };

// One connection in a workspace: what the global connection allows, what this workspace narrowed, and the fields to
// narrow it further. Only narrower values can be saved (the server refuses anything wider); Reset drops the deviation.
export function WorkspaceConnectionNarrow({ workspaceId, workspaceName, connection, onSaved }: Props) {
  const [draft, setDraft] = useState<NarrowDraft>(() => draftOf(connection));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => setDraft(draftOf(connection)), [connection]);

  const base = connection.base ?? null;
  const next = useMemo(() => deviationOf(base, draft), [base, draft]);
  const dirty = JSON.stringify(next) !== JSON.stringify(connection.deviation ?? null);
  const problem = draftProblem(draft, base);

  const send = async (method: "PUT" | "DELETE") => {
    setBusy(true);
    setMessage("");
    try {
      const answer = await readJson<Pick<WorkspaceConnection, "effective" | "deviation" | "base">>(
        deviationPath(workspaceId, connection.id),
        method === "PUT" ? { method, body: JSON.stringify(next ?? {}) } : { method },
      );
      onSaved({ ...connection, ...answer });
      setMessage(method === "PUT" ? "Saved." : "Reset to global.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Not saved.");
    } finally {
      setBusy(false);
    }
  };

  const toggleItem = (use: (typeof SCOPED_USES)[number], item: string, on: boolean) =>
    setDraft((current) => {
      const values = current[use];
      if (!values) return current;
      const items = on ? [...values.items, item] : values.items.filter((value) => value.toUpperCase() !== item.toUpperCase());
      return { ...current, [use]: { ...values, items } };
    });

  return (
    <details className="workspace-narrow" data-testid={`workspace-narrow-${connection.id}`} open={Boolean(connection.deviation) || undefined}>
      <summary className="workspace-narrow__head">
        <span className="workspace-narrow__title">{connection.name}</span>
        <StatusLabel label={changeText(connection.deviation)} tone={connection.deviation ? "attention" : "neutral"} />
      </summary>
      <p className="workspace-narrow__sub">Uses the global connection in {workspaceName || "this workspace"}. You can narrow it for this team, never widen it.</p>

      {SCOPED_USES.map((use) => (
        <ScopedUseFieldset key={use} use={use} connection={connection} draft={draft} busy={busy} setDraft={setDraft} onToggleItem={toggleItem} />
      ))}

      {base?.agent_tools?.level ? (
        <AgentToolsFieldset level={base.agent_tools.level} connection={connection} draft={draft} busy={busy} setDraft={setDraft} />
      ) : null}

      {connection.can_edit ? (
        <NarrowFooter status={problem || message} isProblem={Boolean(problem)} canReset={Boolean(connection.deviation)} busy={busy}
          canSave={dirty && !problem} workspaceName={workspaceName} onReset={() => void send("DELETE")}
          onSave={() => void send(next ? "PUT" : "DELETE")} />
      ) : <p className="workspace-narrow__sub">Only a workspace admin can narrow it.</p>}
    </details>
  );
}

function NarrowFooter({ status, isProblem, canReset, busy, canSave, workspaceName, onReset, onSave }: {
  status: string;
  isProblem: boolean;
  canReset: boolean;
  busy: boolean;
  canSave: boolean;
  workspaceName?: string;
  onReset: () => void;
  onSave: () => void;
}) {
  return (
    <footer className="workspace-narrow__foot">
      <span className={isProblem ? "workspace-narrow__problem" : "workspace-narrow__sub"} role="status">{status}</span>
      {canReset ? (
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onReset}>Reset to global</button>
      ) : null}
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !canSave}
        onClick={onSave}>
        Save for {workspaceName || "this workspace"}
      </button>
    </footer>
  );
}

type FieldsetProps = { connection: WorkspaceConnection; draft: NarrowDraft; busy: boolean; setDraft: Dispatch<SetStateAction<NarrowDraft>> };

// One use (Knowledge sync, Tickets): on or off here, and which of the global scope's items this workspace keeps.
function ScopedUseFieldset({ use, connection, draft, busy, setDraft, onToggleItem }: FieldsetProps & {
  use: ScopedUse;
  onToggleItem: (use: ScopedUse, item: string, on: boolean) => void;
}) {
  const global = connection.base?.[use];
  const values = draft[use];
  if (!global || !values) return null;
  const scope = scopeOf(global);
  return (
    <fieldset className="workspace-narrow__group" disabled={!connection.can_edit || busy}>
      <legend className="workspace-narrow__legend">
        {USE_LABELS[use]}
        <span className="workspace-narrow__state">{fieldState(connection.deviation, use, "enabled") === "Narrowed" || fieldState(connection.deviation, use, "scope") === "Narrowed" ? "Narrowed" : "Inherited"}</span>
      </legend>
      {global.enabled ? (
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={values.enabled}
            onChange={(event) => setDraft((current) => ({ ...current, [use]: { ...values, enabled: event.target.checked } }))} />
          <span>Use it in this workspace</span>
        </label>
      ) : <p className="workspace-narrow__sub">Switched off globally.</p>}
      {scope && values.enabled ? (
        <div className="workspace-narrow__items" role="group" aria-label={scopeTitle(scope.key)}>
          <span className="workspace-narrow__label">{scopeTitle(scope.key)}</span>
          {scope.items.map((item) => (
            <label className="admin-panel__checkbox" key={item}>
              <input type="checkbox" checked={values.items.some((value) => value.toUpperCase() === item.toUpperCase())}
                onChange={(event) => onToggleItem(use, item, event.target.checked)} />
              <span>{item}</span>
            </label>
          ))}
          <span className="workspace-narrow__sub">Only the {scope.items.length} the global connection allows are listed.</span>
        </div>
      ) : null}
    </fieldset>
  );
}

function AgentToolsFieldset({ level, connection, draft, busy, setDraft }: FieldsetProps & { level: string }) {
  return (
    <fieldset className="workspace-narrow__group" disabled={!connection.can_edit || busy}>
      <legend className="workspace-narrow__legend">
        Agent tools
        <span className="workspace-narrow__state">{fieldState(connection.deviation, "agent_tools", "level")}</span>
      </legend>
      <select className="admin-users__toolbar-select" aria-label="Agent tools" value={draft.level ?? level}
        onChange={(event) => setDraft((current) => ({ ...current, level: event.target.value }))}>
        {levelOptions(level).map((option) => <option key={option} value={option}>{LEVEL_LABELS[option] ?? option}</option>)}
      </select>
      {level === "write" ? (
        <p className="workspace-narrow__sub">Writing needs approval by the global rule. A workspace can switch writing off, not drop the approval.</p>
      ) : null}
    </fieldset>
  );
}

/** Every connection available in the workspace, each with its narrowing form. */
export function WorkspaceConnectionsNarrowing({ workspaceId, workspaceName }: { workspaceId: string; workspaceName?: string }) {
  const [rows, setRows] = useState<WorkspaceConnection[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    setRows(null);
    readJson<{ connections: WorkspaceConnection[] }>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/connections`)
      .then((payload) => current && setRows(payload.connections || []))
      .catch((reason: unknown) => current && setError(reason instanceof Error ? reason.message : "The connections could not be loaded."));
    return () => { current = false; };
  }, [workspaceId]);

  if (error) return <p className="admin-panel__error">{error}</p>;
  const narrowable = (rows ?? []).filter((row) => row.base && (row.base.knowledge || row.base.tickets || row.base.agent_tools));
  if (!narrowable.length) return null;
  return (
    <section className="workspace-data__section" aria-labelledby="workspace-narrow-title" data-testid="workspace-connections-narrow">
      <div className="workspace-data__head">
        <h3 id="workspace-narrow-title" className="workspace-data__title">Narrow for this workspace</h3>
      </div>
      <p className="workspace-narrow__sub">Connections are defined once in Admin › Connections. Open one to use less of it here.</p>
      {narrowable.map((row) => (
        <WorkspaceConnectionNarrow key={row.id} workspaceId={workspaceId} workspaceName={workspaceName} connection={row}
          onSaved={(next) => setRows((current) => (current ?? []).map((item) => (item.id === next.id ? next : item)))} />
      ))}
    </section>
  );
}
