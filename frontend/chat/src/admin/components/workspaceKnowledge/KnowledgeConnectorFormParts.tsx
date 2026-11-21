// The parts of the knowledge source form: system and name, where a new repository comes from, and the advanced fields.
import { KIND_LABEL } from "./connectorDisplay";
import type { ConnectorKind, SourceConnector } from "./connectorTypes";
import { CONNECTOR_KINDS, pinnable } from "./connectorFormModel";
import type { FormState } from "./connectorFormModel";
import { KnowledgeFormField } from "./KnowledgeFormField";

type FieldsProps = {
  form: FormState;
  set: (patch: Partial<FormState>) => void;
};

// The source system (fixed when editing) and, unless the repository comes from a connection, the name.
export function ConnectorKindAndName({ form, set, editing, fromConnection, changeKind }: FieldsProps & {
  editing: SourceConnector | null;
  fromConnection: boolean;
  changeKind: (kind: ConnectorKind) => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "0.5rem" }}>
      <KnowledgeFormField label="Source system">
        <select className="admin-panel__input" value={form.kind} aria-label="Source system" disabled={Boolean(editing)}
          onChange={(event) => changeKind(event.target.value as ConnectorKind)}>
          {CONNECTOR_KINDS.map((kind) => <option key={kind} value={kind}>{KIND_LABEL[kind]}</option>)}
        </select>
      </KnowledgeFormField>
      {fromConnection ? null : (
        <KnowledgeFormField label="Name">
          <input className="admin-panel__input" placeholder="e.g. team-wiki (lowercase letters, digits and dashes)" aria-label="Connector name"
            value={form.key} disabled={Boolean(editing)} onChange={(event) => set({ key: event.target.value.trim() })} />
        </KnowledgeFormField>
      )}
    </div>
  );
}

export function RepositoryFromChoice({ repositoryFrom, setRepositoryFrom }: {
  repositoryFrom: "url" | "connection";
  setRepositoryFrom: (from: "url" | "connection") => void;
}) {
  return (
    <div role="radiogroup" aria-label="Repository from" style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}
      data-testid="repository-from">
      <label className="admin-panel__checkbox" style={{ gridColumn: "auto" }}>
        <input type="radio" name="repository-from" checked={repositoryFrom === "url"} data-testid="repository-from-url"
          onChange={() => setRepositoryFrom("url")} />
        Repository URL
      </label>
      <label className="admin-panel__checkbox" style={{ gridColumn: "auto" }}>
        <input type="radio" name="repository-from" checked={repositoryFrom === "connection"} data-testid="repository-from-connection"
          onChange={() => setRepositoryFrom("connection")} />
        From a connection
      </label>
    </div>
  );
}

// The pinned connection (where the kind allows one), products, version and items per run.
export function ConnectorAdvancedFields({ form, set }: FieldsProps) {
  return (
    <details className="area-disclosure" data-testid="connector-advanced">
      <summary className="area-disclosure__summary">Advanced</summary>
      <div className="area-disclosure__body admin-panel__stack admin-panel__stack--compact">
        {pinnable(form.kind) ? (
          <KnowledgeFormField label="Connection id (empty: the connection that binds each scope)">
            <input className="admin-panel__input" aria-label="Connection id"
              value={form.connectionId} onChange={(event) => set({ connectionId: event.target.value.trim() })} />
          </KnowledgeFormField>
        ) : null}
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr)", gap: "0.5rem" }}>
          <KnowledgeFormField label="Products">
            <input className="admin-panel__input" aria-label="Products"
              value={form.products} onChange={(event) => set({ products: event.target.value })} />
          </KnowledgeFormField>
          <KnowledgeFormField label="Version">
            <input className="admin-panel__input" aria-label="Version"
              value={form.version} onChange={(event) => set({ version: event.target.value })} />
          </KnowledgeFormField>
          <KnowledgeFormField label="Items per run">
            <input className="admin-panel__input" type="number" min={1} max={500} aria-label="Items per run"
              value={form.limit} onChange={(event) => set({ limit: event.target.value })} />
          </KnowledgeFormField>
        </div>
      </div>
    </details>
  );
}
