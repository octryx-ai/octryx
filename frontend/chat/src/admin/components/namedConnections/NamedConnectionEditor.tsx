import { AtlassianAuthFields } from "../connectorsTab/AtlassianAuthFields";
import type { atlassianAuthView } from "../connectorsTab/atlassianAuthView";
import type { serviceNowAuthView } from "../connectorsTab/serviceNowAuthModel";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import { NamedFieldsForm } from "./NamedFieldsForm";
import { NamedServiceNowAuthFields } from "./NamedServiceNowAuthFields";
import { KeyTagInput } from "../keyTags/KeyTagInput";
import { canonical, parseScopes, scopeLabel } from "./namedConnectionsForm";
import type { NamedConnection, NamedDescriptor } from "./namedConnectionsTypes";
import type { FieldsView } from "./namedFieldsModel";

export type Editing = { connection: NamedConnection | null; name: string; scopes: string; draft: Record<string, string> };

type Props = {
  descriptor: NamedDescriptor;
  editing: Editing;
  asConnector: AdminConnector;
  authView: ReturnType<typeof atlassianAuthView> | null;
  snView: ReturnType<typeof serviceNowAuthView> | null;
  genericView: FieldsView | null;
  problems: string[];
  attempted: boolean;
  busy: string | null;
  setEditing: (editing: Editing) => void;
  set: (field: string, value: string) => void;
  onTest: (connection: NamedConnection) => void;
  onSave: () => void;
  onCancel: () => void;
};

// The add/edit form of one named connection: name, bound keys and the sign-in form of the descriptor's form kind
// (Atlassian ServiceNow, or the generic fields of any other connector). The id is the server's.
export function NamedConnectionEditor({
  descriptor, editing, asConnector, authView, snView, genericView, problems, attempted, busy, setEditing, set,
  onTest, onSave, onCancel,
}: Props) {
  const connector = descriptor.connector;
  const scope = scopeLabel(descriptor);
  const draft = editing.draft;
  return (
    <div className="connector-card__fields" data-testid="named-connection-editor">
      {editing.connection ? (
        <div className="admin-panel__hint">
          Editing <code>{editing.connection.id}</code>. The id stays the same; what references it keeps working.
        </div>
      ) : null}
      <div className="connector-field">
        <label className="connector-field__label" htmlFor={connectorFieldInputId(`${connector}-named`, "name")}>
          Connection name
        </label>
        <input id={connectorFieldInputId(`${connector}-named`, "name")} className="connector-field__input"
          value={editing.name} autoComplete="off"
          onChange={(event) => setEditing({ ...editing, name: event.target.value })} />
      </div>
      <div className="connector-field">
        <label className="connector-field__label" htmlFor={connectorFieldInputId(`${connector}-named`, "scopes")}>
          {scope.plural} served by this connection
        </label>
        <KeyTagInput id={connectorFieldInputId(`${connector}-named`, "scopes")} noun={scope.one}
          keys={parseScopes(descriptor, editing.scopes)} placeholder={descriptor.binding.example}
          rule={{ pattern: descriptor.binding.pattern, canonical: (key) => canonical(descriptor, key) }}
          onChange={(keys) => setEditing({ ...editing, scopes: keys.join(", ") })} />
      </div>
      {snView ? (
        <NamedServiceNowAuthFields toolName={`${connector}-named`} draft={draft} view={snView} set={set}
          showAllErrors={attempted} />
      ) : authView ? (
        <AtlassianAuthFields product={connector as "confluence" | "jira"} connector={asConnector} draft={draft}
          view={authView} set={set} rebind={{ flow: null }} showAllErrors={attempted} />
      ) : genericView ? (
        <NamedFieldsForm descriptor={descriptor} draft={draft} view={genericView} set={set} showAllErrors={attempted} />
      ) : null}
      {problems.length > 0 && (attempted || editing.scopes) ? (
        <div className="workspace-connection__message" role="alert" data-testid="named-connection-problems">
          {problems.join(" ")}
        </div>
      ) : null}
      <div className="connector-card__actions">
        {editing.connection && descriptor.testable ? (
          <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
            onClick={() => editing.connection && onTest(editing.connection)}>Test connection</button>
        ) : null}
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy !== null} onClick={onSave}>
          {busy === "save" ? "Saving…" : "Save connection"}
        </button>
        <button type="button" className="admin-panel__action-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
