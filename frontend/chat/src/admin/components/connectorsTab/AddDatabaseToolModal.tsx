import { SidePanel } from "../../../layout/SidePanel";

type AddDatabaseToolModalProps = {
  ctx: Record<string, unknown>;
};

type DatabaseToolForm = {
  connector_id: string;
  tool_name: string;
  display_name: string;
  allowed_roles: string;
  max_rows: string;
  timeout_seconds: string;
  description: string;
  sql_template: string;
  parameters_schema: string;
  row_level_security_rules: string;
};

type DatabaseConnectorOption = {
  id: string;
  name: string;
  db_type: string;
};

type TextField = Exclude<keyof DatabaseToolForm, "connector_id">;

// The text fields after the connector choice, in order: `rows` makes a monospace text area, `full` spans the grid.
const TOOL_FIELDS: Array<{ field: TextField; label: string; placeholder?: string; full?: boolean; rows?: number }> = [
  { field: "tool_name", label: "Tool name", placeholder: "database_tool_customer_orders" },
  { field: "display_name", label: "Display name", placeholder: "Customer orders" },
  { field: "allowed_roles", label: "Allowed roles", placeholder: "admin, analyst" },
  { field: "max_rows", label: "Max rows", placeholder: "100" },
  { field: "timeout_seconds", label: "Timeout seconds", placeholder: "30" },
  { field: "description", label: "Description", placeholder: "Returns approved customer order rows", full: true },
  {
    field: "sql_template", label: "SQL template", full: true, rows: 5,
    placeholder: "select id, tenant_id, status from orders where status = :status",
  },
  { field: "parameters_schema", label: "Parameter schema JSON", full: true, rows: 6 },
  {
    field: "row_level_security_rules", label: "RLS rules (one per line)", full: true, rows: 3,
    placeholder: "tenant_id = $user.id\nteam_name in $groups\ntenantid = $group.rls.tenantid",
  },
];

type FormProps = {
  form: DatabaseToolForm;
  setForm: (update: (prev: DatabaseToolForm) => DatabaseToolForm) => void;
};

function ToolTextField({ form, setForm, field, label, placeholder, full, rows }: FormProps & (typeof TOOL_FIELDS)[number]) {
  const onChange = (e: { target: { value: string } }) =>
    setForm((prev: DatabaseToolForm) => ({ ...prev, [field]: e.target.value }));
  return (
    <label className={full ? "admin-form-field admin-form-grid__full" : "admin-form-field"}>
      <span className="admin-form-field__label">{label}</span>
      {rows ? (
        <textarea
          className="admin-panel__form-input connector-form__textarea"
          rows={rows}
          value={form[field]}
          onChange={onChange}
          placeholder={placeholder}
        />
      ) : (
        <input className="admin-panel__form-input" value={form[field]} onChange={onChange} placeholder={placeholder} />
      )}
    </label>
  );
}

function DatabaseToolFields({ form, setForm, connectors }: FormProps & { connectors: DatabaseConnectorOption[] }) {
  return (
    <div className="admin-form-grid">
      <label className="admin-form-field">
        <span className="admin-form-field__label">Connector</span>
        <select
          className="admin-panel__form-input"
          value={form.connector_id}
          onChange={(e) =>
            setForm((prev: DatabaseToolForm) => ({
              ...prev,
              connector_id: e.target.value,
            }))
          }
        >
          <option value="">Select connector</option>
          {connectors.map(
            (connector: DatabaseConnectorOption) => (
              <option key={connector.id} value={connector.id}>
                {connector.name} ({connector.db_type})
              </option>
            ),
          )}
        </select>
      </label>
      {TOOL_FIELDS.map((entry) => (
        <ToolTextField key={entry.field} form={form} setForm={setForm} {...entry} />
      ))}
    </div>
  );
}

export function AddDatabaseToolModal({ ctx }: AddDatabaseToolModalProps) {
  const {
    databaseConnectors,
    databaseToolError,
    databaseToolForm,
    databaseToolSaving,
    handleCreateDatabaseTool,
    setDatabaseToolForm,
    setShowAddDatabaseTool,
    showAddDatabaseTool,
  } = ctx as Record<string, any>;

  return (
    <>
      {/* Opened from a database's drawer: the layer keeps the side panel above that drawer. */}
      {showAddDatabaseTool && (
        <div className="automation-panel-layer">
        <SidePanel
          title="Add query tool"
          onClose={() => setShowAddDatabaseTool(false)}
          testId="database-tool-add-panel"
          footer={(
            <>
              <button
                type="button"
                className="admin-panel__action-btn"
                onClick={() => setShowAddDatabaseTool(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="admin-panel__action-btn admin-panel__action-btn--primary"
                disabled={databaseToolSaving || !databaseToolForm.connector_id}
                onClick={() => void handleCreateDatabaseTool()}
              >
                {databaseToolSaving ? "Creating…" : "Add query tool"}
              </button>
            </>
          )}
        >
              <div className="admin-modal__stack">
                <DatabaseToolFields form={databaseToolForm} setForm={setDatabaseToolForm} connectors={databaseConnectors} />
                {databaseToolError ? (
                  <div className="admin-panel__error">{databaseToolError}</div>
                ) : null}
              </div>
        </SidePanel>
        </div>
      )}
    </>
  );
}
