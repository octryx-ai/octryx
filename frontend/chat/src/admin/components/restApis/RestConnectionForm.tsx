import { useState, type Dispatch, type SetStateAction } from "react";

import { StatusLabel } from "../../../layout/StatusLabel";
import {
  createConnection,
  updateConnection,
  type PublicField,
  type RestConnection,
  type RestDefinition,
  type SecretField,
} from "./restApisApi";
import { SECRET_STATE_WORDS, connectionBody, connectionDraft, secretState, type ConnectionDraft } from "./restConnectionsModel";
import { connectionAuthFields, schemeLabel, type ConnectionField } from "./restAuthModel";
import { restErrorView, type RestErrorView } from "./restErrorsModel";
import { Field, FormError } from "./restApisParts";
import type { Workspace } from "./RestApisPage";

type Replacing = Partial<Record<SecretField, boolean>>;

// Adds or edits one connection: its owner (fixed once created), name, base URL and the technical account's fields.
export function ConnectionForm({ definition, workspaces, existing, taken, onDone, onCancel }: {
  definition: RestDefinition;
  workspaces: Workspace[];
  existing: RestConnection | null;
  taken: string[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ConnectionDraft>(() => connectionDraft(existing, definition));
  const [replacing, setReplacing] = useState<Replacing>({});
  const [error, setError] = useState<RestErrorView | null>(null);
  const [busy, setBusy] = useState(false);
  const fields = connectionAuthFields(definition.auth.scheme);
  const at = (field: string) => (error?.field === field ? error.text : null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = connectionBody(draft, definition.auth.scheme, existing);
      if (existing) await updateConnection(definition.id, existing.id, body);
      else await createConnection(definition.id, body);
      onDone();
    } catch (failure) {
      setError(restErrorView(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="rst-stack" data-testid="rest-connection-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <h3 className="rst-card__title">{existing ? "Edit connection" : "Add connection"}</h3>
      <ConnectionTarget definition={definition} workspaces={workspaces} existing={existing} taken={taken} draft={draft}
        setDraft={setDraft} at={at} />
      <h4 className="rst-subhead">{`Technical account · ${schemeLabel(definition.auth.scheme)}`}</h4>
      {fields.length ? null : <p className="rst-muted">The API needs no credentials.</p>}
      {fields.map((field) => (field.secret ? (
        <SecretFieldRow key={field.name} field={field} existing={existing} draft={draft} setDraft={setDraft}
          replacing={replacing} setReplacing={setReplacing} />
      ) : (
        <PublicFieldRow key={field.name} field={field} draft={draft} setDraft={setDraft} />
      )))}
      <FormError text={error && !["workspace", "base_url"].includes(error.field ?? "") ? error.text : null} />
      <div className="rst-row rst-row--end">
        <button type="button" className="ds-btn" onClick={onCancel}>Cancel</button>
        <button type="submit" className="ds-btn ds-btn--primary" disabled={busy} data-testid="rest-connection-save">
          {busy ? "Saving…" : existing ? "Save connection" : "Add connection"}
        </button>
      </div>
    </form>
  );
}

// Who uses the connection, its name and its base URL.
function ConnectionTarget({ definition, workspaces, existing, taken, draft, setDraft, at }: {
  definition: RestDefinition;
  workspaces: Workspace[];
  existing: RestConnection | null;
  taken: string[];
  draft: ConnectionDraft;
  setDraft: Dispatch<SetStateAction<ConnectionDraft>>;
  at: (field: string) => string | null;
}) {
  return (
    <>
      <div className="rst-grid">
        <Field label="Used by" error={at("workspace")} hint={existing ? "The owner of a connection does not change." : undefined}>
          <select className="admin-panel__input" value={draft.workspaceId} disabled={Boolean(existing)} onChange={(event) => setDraft({ ...draft, workspaceId: event.target.value })}
            data-testid="rest-connection-owner">
            <option value="" disabled={!existing && taken.includes("")}>Platform (every Workspace without its own)</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id} disabled={!existing && taken.includes(workspace.id)}>{`Workspace ${workspace.name}`}</option>
            ))}
          </select>
        </Field>
        <Field label="Name (optional)">
          <input className="admin-panel__input" value={draft.name} placeholder={draft.workspaceId ? "Workspace" : "Platform"} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </Field>
      </div>
      <Field label="Base URL" hint={definition.servers.length ? `The API's first server is ${definition.servers[0]}.` : undefined} error={at("base_url")}>
        <input className="admin-panel__input" type="url" value={draft.baseUrl} onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })}
          placeholder="https://api.example.com" data-testid="rest-connection-base-url" />
      </Field>
    </>
  );
}

function PublicFieldRow({ field, draft, setDraft }: {
  field: ConnectionField; draft: ConnectionDraft; setDraft: Dispatch<SetStateAction<ConnectionDraft>>;
}) {
  const name = field.name as PublicField;
  return (
    <Field label={field.required ? field.label : `${field.label} (optional)`}>
      <input className="admin-panel__input" value={draft.fields[name]} onChange={(event) => setDraft({ ...draft, fields: { ...draft.fields, [name]: event.target.value } })}
        autoComplete="off" />
    </Field>
  );
}

// A write-only secret: its state, Replace / Clear for a stored one (or Keep the stored one), and the input.
function SecretFieldRow({ field, existing, draft, setDraft, replacing, setReplacing }: {
  field: ConnectionField;
  existing: RestConnection | null;
  draft: ConnectionDraft;
  setDraft: Dispatch<SetStateAction<ConnectionDraft>>;
  replacing: Replacing;
  setReplacing: Dispatch<SetStateAction<Replacing>>;
}) {
  const name = field.name as SecretField;
  const state = secretState(existing, draft, name);
  const stored = Boolean(existing?.secret_status[name]);
  const showInput = !stored || replacing[name];
  return (
    <Field label={field.label} hint="Write-only: stored encrypted, never shown again." group>
      <span className="rst-secret">
        <StatusLabel label={SECRET_STATE_WORDS[state]} tone={state === "not_set" ? "attention" : "neutral"} testId={`rest-secret-${name}`} />
        {stored && !replacing[name] && !draft.clear[name] ? (
          <>
            <button type="button" className="ds-btn ds-btn--sm" onClick={() => setReplacing({ ...replacing, [name]: true })}>Replace</button>
            <button type="button" className="ds-btn ds-btn--sm ds-btn--ghost" onClick={() => setDraft({ ...draft, clear: { ...draft.clear, [name]: true } })}>Clear</button>
          </>
        ) : null}
        {stored && (replacing[name] || draft.clear[name]) ? (
          <button type="button" className="ds-btn ds-btn--sm ds-btn--ghost"
            onClick={() => { setReplacing({ ...replacing, [name]: false }); setDraft({ ...draft, secrets: { ...draft.secrets, [name]: "" }, clear: { ...draft.clear, [name]: false } }); }}>
            Keep the stored one
          </button>
        ) : null}
      </span>
      {showInput ? (
        <input className="admin-panel__input" type="password" autoComplete="new-password" value={draft.secrets[name]} placeholder={stored ? "New value" : "Not set"}
          onChange={(event) => setDraft({ ...draft, secrets: { ...draft.secrets, [name]: event.target.value } })} data-testid={`rest-secret-input-${name}`} />
      ) : null}
    </Field>
  );
}
