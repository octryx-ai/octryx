import type { ReactNode } from "react";
import { SidePanel } from "../../../layout/SidePanel";

type AddDatabaseConnectorModalProps = {
  ctx: Record<string, unknown>;
};

type DatabaseConnectorForm = {
  name: string;
  db_type: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  dsn: string;
  file_path: string;
  driver: string;
  description: string;
};

type SetDatabaseConnectorForm = (update: (prev: DatabaseConnectorForm) => DatabaseConnectorForm) => void;

// The plain text fields of the form, in display order (Type, File path/Driver and Description are rendered apart).
const TEXT_FIELDS_BEFORE_TYPE: Array<{ field: keyof DatabaseConnectorForm; label: string; placeholder: string }> = [
  { field: "name", label: "Name", placeholder: "customer-postgres" },
];
const TEXT_FIELDS_AFTER_TYPE: Array<{ field: keyof DatabaseConnectorForm; label: string; placeholder: string; type?: string }> = [
  { field: "host", label: "Host", placeholder: "db.internal" },
  { field: "port", label: "Port", placeholder: "5432" },
  { field: "database", label: "Database", placeholder: "app" },
  { field: "username", label: "Username", placeholder: "readonly_user" },
  { field: "password", label: "Password", placeholder: "Stored securely", type: "password" },
  { field: "dsn", label: "DSN override", placeholder: "Optional full SQLAlchemy URL" },
];

type FieldProps = { form: DatabaseConnectorForm; setForm: SetDatabaseConnectorForm };

function DatabaseTextField({ form, setForm, field, label, placeholder, type, className = "admin-form-field" }: FieldProps & {
  field: keyof DatabaseConnectorForm; label: string; placeholder: string; type?: string; className?: string;
}) {
  return (
    <label className={className}>
      <span className="admin-form-field__label">{label}</span>
      <input
        type={type}
        className="admin-panel__form-input"
        value={form[field]}
        onChange={(e) =>
          setForm(
            (prev: DatabaseConnectorForm) => ({
              ...prev,
              [field]: e.target.value,
            }),
          )
        }
        placeholder={placeholder}
      />
    </label>
  );
}

function DatabaseTypeField({ form, setForm }: FieldProps) {
  return (
    <label className="admin-form-field">
      <span className="admin-form-field__label">Type</span>
      <select
        className="admin-panel__form-input"
        value={form.db_type}
        onChange={(e) =>
          setForm(
            (prev: DatabaseConnectorForm) => ({
              ...prev,
              db_type: e.target.value,
            }),
          )
        }
      >
        <option value="postgresql">PostgreSQL</option>
        <option value="mysql">MySQL</option>
        <option value="mssql">MSSQL</option>
        <option value="sqlite">SQLite</option>
      </select>
    </label>
  );
}

// SQLite takes a file path; every other type an optional driver, in the same place.
function DatabaseFileOrDriverField({ form, setForm }: FieldProps) {
  const sqlite = form.db_type === "sqlite";
  return (
    <label className="admin-form-field">
      <span className="admin-form-field__label">
        {sqlite
          ? "File path"
          : "Driver"}
      </span>
      <input
        className="admin-panel__form-input"
        value={
          sqlite
            ? form.file_path
            : form.driver
        }
        onChange={(e) =>
          setForm(
            (prev: DatabaseConnectorForm) =>
              prev.db_type === "sqlite"
                ? { ...prev, file_path: e.target.value }
                : { ...prev, driver: e.target.value },
          )
        }
        placeholder={
          sqlite
            ? "/tmp/example.db"
            : "Optional DB driver"
        }
      />
    </label>
  );
}

function DatabaseConnectorFields({ form, setForm, error }: FieldProps & { error: ReactNode }) {
  const shared = { form, setForm };
  return (
    <div className="admin-modal__stack">
      <div className="admin-form-grid">
        {TEXT_FIELDS_BEFORE_TYPE.map((entry) => <DatabaseTextField key={entry.field} {...shared} {...entry} />)}
        <DatabaseTypeField {...shared} />
        {TEXT_FIELDS_AFTER_TYPE.map((entry) => <DatabaseTextField key={entry.field} {...shared} {...entry} />)}
        <DatabaseFileOrDriverField {...shared} />
        <DatabaseTextField {...shared} field="description" label="Description" placeholder="Read-only reporting database"
          className="admin-form-field admin-form-grid__full" />
      </div>
      {error ? (
        <div className="admin-panel__error">
          {error}
        </div>
      ) : null}
    </div>
  );
}

export function AddDatabaseConnectorModal({
  ctx,
}: AddDatabaseConnectorModalProps) {
  const {
    databaseConnectorError,
    databaseConnectorForm,
    databaseConnectorSaving,
    handleCreateDatabaseConnector,
    setDatabaseConnectorForm,
    setShowAddDatabaseConnector,
    showAddDatabaseConnector,
  } = ctx as Record<string, any>;

  return (
    <>
      {showAddDatabaseConnector && (
        <SidePanel
          title="Add database"
          onClose={() => setShowAddDatabaseConnector(false)}
          testId="database-add-panel"
          footer={(
            <>
              <button
                type="button"
                className="admin-panel__action-btn"
                onClick={() => setShowAddDatabaseConnector(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="admin-panel__action-btn admin-panel__action-btn--primary"
                disabled={databaseConnectorSaving}
                onClick={() => void handleCreateDatabaseConnector()}
              >
                {databaseConnectorSaving ? "Creating…" : "Add database"}
              </button>
            </>
          )}
        >
          <DatabaseConnectorFields
            form={databaseConnectorForm}
            setForm={setDatabaseConnectorForm}
            error={databaseConnectorError}
          />
        </SidePanel>
      )}
    </>
  );
}
