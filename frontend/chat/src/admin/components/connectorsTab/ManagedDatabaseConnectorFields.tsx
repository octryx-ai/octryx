type ManagedDatabaseConnectorFieldsProps = {
  connector: any;
  draft: Record<string, any>;
  setDatabaseConnectorDraftField: (
    connectorId: string,
    field: string,
    value: string,
  ) => void;
};

export function ManagedDatabaseConnectorFields({
  connector,
  draft,
  setDatabaseConnectorDraftField,
}: ManagedDatabaseConnectorFieldsProps) {
  const set = (field: string) => (value: string) => setDatabaseConnectorDraftField(connector.id, field, value);
  const sqlite = draft.db_type === "sqlite";
  return (
    <div className="connector-card__fields">
      <DraftField label="Description" value={draft.description} onChange={set("description")} placeholder="Read-only reporting database" />
      <div className="connector-field">
        <label className="connector-field__label">Type</label>
        <select
          className="connector-field__input"
          value={draft.db_type}
          onChange={(e) => set("db_type")(e.target.value)}
        >
          <option value="postgresql">PostgreSQL</option>
          <option value="mysql">MySQL</option>
          <option value="mssql">MSSQL</option>
          <option value="sqlite">SQLite</option>
        </select>
      </div>
      <DraftField label="Host" value={draft.host} onChange={set("host")} placeholder="db.internal" />
      <DraftField label="Port" value={draft.port} onChange={set("port")} placeholder="5432" />
      <DraftField label="Database" value={draft.database} onChange={set("database")} placeholder="app" />
      <DraftField label="Username" value={draft.username} onChange={set("username")} placeholder="readonly_user" />
      <DraftField
        label="Password"
        type="password"
        value={draft.password}
        onChange={set("password")}
        placeholder={connector.secret_status.password ? "••••••• (stored — leave blank to keep)" : "Stored securely"}
      />
      <DraftField
        label="DSN override"
        value={draft.dsn}
        onChange={set("dsn")}
        placeholder={connector.secret_status.dsn ? "Stored — leave blank to keep" : "Optional full SQLAlchemy URL"}
      />
      <DraftField
        label={sqlite ? "File path" : "Driver"}
        value={sqlite ? draft.file_path : draft.driver}
        onChange={set(sqlite ? "file_path" : "driver")}
        placeholder={sqlite ? "/tmp/example.db" : "Optional DB driver"}
      />
    </div>
  );
}

function DraftField({
  label,
  type,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  type?: "password";
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className="connector-field">
      <label className="connector-field__label">{label}</label>
      <input
        type={type}
        className="connector-field__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
