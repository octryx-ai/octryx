import { healthPhrase, healthTone } from "../../utils/healthPhrase";
import { ManagedDatabaseConnectorFields } from "./ManagedDatabaseConnectorFields";

type ManagedDatabaseConnectorCardProps = {
  connector: any;
  ctx: Record<string, unknown>;
  // Rendered in the Databases drawer (no header; the grid card opens the drawer).
  inDrawer?: boolean;
};

function getDatabaseColor(dbType: string) {
  if (dbType === "postgresql") return "#2563eb";
  if (dbType === "mysql") return "#0f766e";
  if (dbType === "mssql") return "#7c3aed";
  return "#475569";
}

type PartProps = { connector: any; ctx: Record<string, unknown> };

export function ManagedDatabaseConnectorCard({
  connector,
  ctx,
  inDrawer = false,
}: ManagedDatabaseConnectorCardProps) {
  const { expandedDatabaseConnector } = ctx as Record<string, any>;
  const isOpen = expandedDatabaseConnector === connector.id;
  if (inDrawer) return <DatabaseConnectorBody connector={connector} ctx={ctx} />;

  return (
    <div
      className={`connector-card ${isOpen ? "connector-card--open" : ""} connector-card--configured`}
    >
      <DatabaseConnectorHeader connector={connector} ctx={ctx} isOpen={isOpen} />
      {isOpen && <DatabaseConnectorBody connector={connector} ctx={ctx} />}
    </div>
  );
}

function DatabaseConnectorBody({ connector, ctx }: PartProps) {
  const {
    databaseConnectorError, databaseConnectorSaving, databaseConnectorTestBusy, databaseTools, getDatabaseConnectorDraft,
    handleDeleteDatabaseTool, handleSaveDatabaseConnector, handleTestDatabaseConnector, openCreateDatabaseTool,
    setDatabaseConnectorDraftField,
  } = ctx as Record<string, any>;
  const draft = getDatabaseConnectorDraft(connector);
  const connectorTools = databaseTools.filter(
    (tool: any) => tool.connector_id === connector.id,
  );
  return (
    <div className="connector-card__body">
      <p className="connector-card__description">
        Register predefined query tools with row-level rules such as{" "}
        <code>tenant_id = $user.id</code> or{" "}
        <code>tenantid = $group.rls.tenantid</code>.
      </p>
      <ManagedDatabaseConnectorFields
        connector={connector}
        draft={draft}
        setDatabaseConnectorDraftField={setDatabaseConnectorDraftField}
      />
      <DatabaseToolList connectorTools={connectorTools} onDelete={handleDeleteDatabaseTool} />
      {databaseConnectorError ? (
        <div className="admin-panel__error">{databaseConnectorError}</div>
      ) : null}
      <div className="connector-card__actions">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={databaseConnectorSaving}
          onClick={() => void handleSaveDatabaseConnector(connector)}
        >
          {databaseConnectorSaving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={databaseConnectorTestBusy === connector.id}
          onClick={() => void handleTestDatabaseConnector(connector.id)}
        >
          {databaseConnectorTestBusy === connector.id
            ? "Testing…"
            : "Test Connection"}
        </button>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => openCreateDatabaseTool(connector.id)}
        >
          Add Query Tool
        </button>
      </div>
    </div>
  );
}

function DatabaseToolList({ connectorTools, onDelete }: { connectorTools: any[]; onDelete: (id: string, name: string) => unknown }) {
  const handleDeleteDatabaseTool = onDelete;
  return (
    <div className="connector-card__tools">
      <div className="connector-card__tools-label">Database tools</div>
      {connectorTools.length === 0 ? (
        <div className="connector-card__health-empty">
          No query tools registered yet.
        </div>
      ) : (
        <div className="connector-card__tools-list">
          {connectorTools.map((tool: any) => (
            <div key={tool.id} className="connector-tool">
              <span className="connector-tool__name">
                {tool.tool_name}
              </span>
              <span className="connector-tool__desc">
                {tool.description || "No description"} · rows{" "}
                {tool.max_rows} · timeout {tool.timeout_seconds}s
              </span>
              <span className="connector-tool__desc">
                RLS:{" "}
                {tool.row_level_security_rules.length
                  ? tool.row_level_security_rules.join(" | ")
                  : "none"}
              </span>
              <button
                type="button"
                className="admin-panel__danger-btn"
                onClick={() =>
                  void handleDeleteDatabaseTool(tool.id, tool.tool_name)
                }
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DatabaseConnectorHeader({ connector, ctx, isOpen }: PartProps & { isOpen: boolean }) {
  const { databaseConnectorTestResult, handleExpandDatabaseConnector } = ctx as Record<string, any>;
  const testResult = databaseConnectorTestResult[connector.id];
  const dbColor = getDatabaseColor(connector.db_type);
  return (
    <div
      className="connector-card__header"
      onClick={() => handleExpandDatabaseConnector(connector)}
    >
      <div className="connector-card__icon" style={{ background: dbColor }}>
        <span className="connector-card__icon-fallback">DB</span>
      </div>
      <div className="connector-card__info">
        <div className="connector-card__name-row">
          <div className="connector-card__name">{connector.name}</div>
          <span className="connector-card__meta-badge">
            {connector.db_type}
          </span>
          <span className="connector-card__meta-badge">
            {connector.tool_count} tool{connector.tool_count === 1 ? "" : "s"}
          </span>
        </div>
        <div
          className={`connector-card__status ${connector.is_active && healthTone(connector.health) === "ok" ? "connector-card__status--ok" : ""}`}
        >
          {healthPhrase(connector.health, connector.is_active)}
        </div>
        <div className="connector-card__meta">
          {connector.description || "Managed read-only database connector."}
        </div>
        <div className="connector-card__meta">
          Host:{" "}
          {String(connector.public_fields.host || connector.public_fields.file_path || "configured")}{" "}
          · password {connector.secret_status.password ? " stored" : " empty"}{" "}
          · dsn {connector.secret_status.dsn ? " stored" : " empty"}
        </div>
        {testResult ? (
          <div className="connector-card__meta">
            {testResult.ok ? "Healthy" : "Failed"} · {testResult.summary}
            {testResult.details ? ` · ${testResult.details}` : ""}
          </div>
        ) : null}
      </div>
      <div
        className="connector-card__header-right"
        onClick={(e) => e.stopPropagation()}
      >
        <svg
          className={`provider-card__chevron ${isOpen ? "provider-card__chevron--open" : ""}`}
          viewBox="0 0 20 20"
          aria-hidden="true"
        >
          <path d="M5 8l5 5 5-5" />
        </svg>
      </div>
    </div>
  );
}
