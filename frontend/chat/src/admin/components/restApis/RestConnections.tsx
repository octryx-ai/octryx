import { useCallback, useEffect, useState } from "react";

import { StatusLabel } from "../../../layout/StatusLabel";
import { AdminDetailFacts } from "../AdminDetailFacts";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { ConnectionForm } from "./RestConnectionForm";
import {
  deleteConnection,
  listConnections,
  type PublicField,
  type RestConnection,
  type RestDefinition,
  type SecretField,
} from "./restApisApi";
import { WORKSPACE_WINS } from "./restOperationsModel";
import { connectionAuthFields, schemeLabel, type ConnectionField } from "./restAuthModel";
import { connectionOwnerText, missingText } from "./restConnectionsModel";
import { restErrorView } from "./restErrorsModel";
import { FormError, Mono } from "./restApisParts";
import type { Workspace } from "./RestApisPage";

// The connections of one API: the platform one and Workspace ones, each with its base URL and the technical account
// for the API's authentication. Secrets are write-only: the page shows Set / Not set, Replace and Clear.
export function RestConnections({ definition, workspaces }: { definition: RestDefinition; workspaces: Workspace[] }) {
  const [connections, setConnections] = useState<RestConnection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<RestConnection | "new" | null>(null);
  const [removing, setRemoving] = useState<RestConnection | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const workspaceName = (id: string) => workspaces.find((workspace) => workspace.id === id)?.name ?? id;

  const load = useCallback(async () => {
    try {
      setConnections(await listConnections(definition.id));
      setError(null);
    } catch (failure) {
      setConnections([]);
      setError(restErrorView(failure).text);
    }
  }, [definition.id]);
  useEffect(() => { void load(); }, [load]);

  const remove = async () => {
    if (!removing) return;
    try {
      await deleteConnection(definition.id, removing.id);
      setRemoving(null);
      void load();
    } catch (failure) {
      setRemoveError(restErrorView(failure).text);
    }
  };

  if (editing) {
    return (
      <ConnectionForm definition={definition} workspaces={workspaces} existing={editing === "new" ? null : editing}
        taken={(connections ?? []).map((connection) => connection.project_id ?? "")}
        onDone={() => { setEditing(null); void load(); }} onCancel={() => setEditing(null)} />
    );
  }

  const fields = connectionAuthFields(definition.auth.scheme);
  return (
    <div className="rst-stack" data-testid="rest-connections">
      <p className="rst-note">{WORKSPACE_WINS}</p>
      <FormError text={error} />
      {connections && !connections.length ? (
        <p className="rst-muted" data-testid="rest-connections-empty">No connection yet: calls are refused until the platform or a Workspace has one.</p>
      ) : null}
      {(connections ?? []).map((connection) => (
        <ConnectionCard key={connection.id} connection={connection} definition={definition} fields={fields} workspaceName={workspaceName}
          onRemove={() => { setRemoveError(null); setRemoving(connection); }} onEdit={() => setEditing(connection)} />
      ))}
      <button type="button" className="ds-btn rst-back" onClick={() => setEditing("new")} data-testid="rest-connection-add">Add connection</button>
      {removing ? (
        <ConfirmDialog title={`Delete the ${connectionOwnerText(removing, workspaceName)} connection?`} confirmLabel="Delete connection"
          error={removeError} onConfirm={() => void remove()} onCancel={() => setRemoving(null)}>
          <p>Its stored secrets are released. Calls that used it are refused until another connection applies.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

// One connection: owner, state, its facts (secrets only as Set / Not set), what is missing, Delete and Edit.
function ConnectionCard({ connection, definition, fields, workspaceName, onRemove, onEdit }: {
  connection: RestConnection;
  definition: RestDefinition;
  fields: ConnectionField[];
  workspaceName: (id: string) => string;
  onRemove: () => void;
  onEdit: () => void;
}) {
  const missing = missingText(connection);
  return (
    <section className="rst-card" data-testid={`rest-connection-${connection.owner}`}>
      <div className="rst-card__head">
        <h3 className="rst-card__title">{connectionOwnerText(connection, workspaceName)}</h3>
        <span className="rst-row">
          {connection.is_active ? null : <StatusLabel label="Inactive" tone="neutral" />}
          {missing ? <StatusLabel label="Needs configuration" tone="attention" title={missing} /> : null}
        </span>
      </div>
      <AdminDetailFacts facts={[
        { label: "Name", value: connection.name },
        { label: "Base URL", value: <Mono>{connection.base_url}</Mono> },
        { label: "Authentication", value: schemeLabel(definition.auth.scheme) },
        ...fields.map((field) => ({
          label: field.label,
          value: field.secret
            ? (connection.secret_status[field.name as SecretField] ? "Set" : "Not set")
            : connection.fields[field.name as PublicField] ?? "Not set",
        })),
      ]} />
      {missing ? <p className="rst-field__error">{missing}</p> : null}
      <div className="rst-row rst-row--end">
        <button type="button" className="ds-btn ds-btn--sm ds-btn--ghost" onClick={onRemove}>Delete…</button>
        <button type="button" className="ds-btn ds-btn--sm" onClick={onEdit} data-testid="rest-connection-edit">Edit</button>
      </div>
    </section>
  );
}
