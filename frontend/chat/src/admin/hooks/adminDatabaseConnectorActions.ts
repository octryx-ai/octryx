// Database connector requests: draft defaults, request bodies, and create/save/test/delete calls.
import type { AdminDatabaseConnector } from "../types/adminPanelTypes.usersProviders";
import type {
  DatabaseConnectorDraft,
  UseAdminConnectorManagementArgs,
} from "./useAdminConnectorManagement.types";

type Args = UseAdminConnectorManagementArgs;
type ConnectionFields = Omit<DatabaseConnectorDraft, "description" | "db_type" | "is_active">;

export function emptyDatabaseConnectorForm() {
  return {
    name: "",
    description: "",
    db_type: "postgresql",
    host: "",
    port: "",
    database: "",
    username: "",
    password: "",
    dsn: "",
    driver: "",
    file_path: "",
    is_active: true,
  };
}

export function emptyDatabaseConnectorDraft(): DatabaseConnectorDraft {
  const { name: _name, ...draft } = emptyDatabaseConnectorForm();
  return draft;
}

export function databaseConnectorDraftFrom(connector: AdminDatabaseConnector): DatabaseConnectorDraft {
  return {
    description: connector.description || "",
    db_type: connector.db_type,
    host: String(connector.public_fields.host || ""),
    port: String(connector.public_fields.port || ""),
    database: String(connector.public_fields.database || ""),
    username: String(connector.public_fields.username || ""),
    password: "",
    dsn: "",
    driver: String(connector.public_fields.driver || ""),
    file_path: String(connector.public_fields.file_path || ""),
    is_active: connector.is_active,
  };
}

// Adds only the filled connection fields; the password is sent untrimmed.
function addConnectionFields(body: Record<string, unknown>, source: ConnectionFields) {
  if (source.host.trim()) body.host = source.host.trim();
  if (source.port.trim()) body.port = Number(source.port);
  if (source.database.trim()) body.database = source.database.trim();
  if (source.username.trim()) body.username = source.username.trim();
  if (source.password.trim()) body.password = source.password;
  if (source.dsn.trim()) body.dsn = source.dsn.trim();
  if (source.driver.trim()) body.driver = source.driver.trim();
  if (source.file_path.trim()) body.file_path = source.file_path.trim();
  return body;
}

const byName = (a: AdminDatabaseConnector, b: AdminDatabaseConnector) => a.name.localeCompare(b.name);

function withoutKey<T>(prev: Record<string, T>, key: string) {
  const next = { ...prev };
  delete next[key];
  return next;
}

export async function createDatabaseConnector(a: Args, resetForm: () => void) {
  a.setDatabaseConnectorSaving(true);
  a.setDatabaseConnectorError(null);
  try {
    const form = a.databaseConnectorForm;
    const body = addConnectionFields({
      name: form.name.trim(),
      description: form.description.trim(),
      db_type: form.db_type,
      is_active: form.is_active,
    }, form);
    const created = await a.readJson<AdminDatabaseConnector>(
      "/admin/chat/api/panel/database-connectors",
      { method: "POST", body: JSON.stringify(body) },
    );
    a.setDatabaseConnectors((prev) => [...prev, created].sort(byName));
    a.setDatabaseToolForm((prev) => ({ ...prev, connector_id: prev.connector_id || created.id }));
    resetForm();
    a.setShowAddDatabaseConnector(false);
  } catch (err) {
    a.setDatabaseConnectorError(err instanceof Error ? err.message : "Failed to create database connector");
  } finally {
    a.setDatabaseConnectorSaving(false);
  }
}

export async function saveDatabaseConnector(a: Args, connector: AdminDatabaseConnector, draft: DatabaseConnectorDraft) {
  a.setDatabaseConnectorSaving(true);
  a.setDatabaseConnectorError(null);
  try {
    const body = addConnectionFields({
      description: draft.description.trim(),
      db_type: draft.db_type,
      is_active: draft.is_active,
    }, draft);
    const updated = await a.readJson<AdminDatabaseConnector>(
      `/admin/chat/api/panel/database-connectors/${connector.id}`,
      { method: "PUT", body: JSON.stringify(body) },
    );
    a.setDatabaseConnectors((prev) =>
      prev.map((item) => (item.id === connector.id ? updated : item)).sort(byName),
    );
    a.setDatabaseConnectorDrafts((prev) => withoutKey(prev, connector.id));
  } catch (err) {
    a.setDatabaseConnectorError(err instanceof Error ? err.message : "Failed to save database connector");
  } finally {
    a.setDatabaseConnectorSaving(false);
  }
}

export async function testDatabaseConnector(a: Args, connectorId: string) {
  a.setDatabaseConnectorTestBusy(connectorId);
  try {
    const result = await a.readJson<{
      ok: boolean;
      summary: string;
      details?: string;
      health?: AdminDatabaseConnector["health"];
    }>(`/admin/chat/api/panel/database-connectors/${connectorId}/test`, { method: "POST" });
    a.setDatabaseConnectorTestResult((prev) => ({ ...prev, [connectorId]: result }));
    // The test is recorded as the database's health, so the card updates at once.
    if (result.health) {
      a.setDatabaseConnectors((prev) =>
        prev.map((item) => (item.id === connectorId ? { ...item, health: result.health } : item)),
      );
    }
  } catch (err) {
    a.setDatabaseConnectorTestResult((prev) => ({
      ...prev,
      [connectorId]: { ok: false, summary: err instanceof Error ? err.message : "Test failed" },
    }));
  } finally {
    a.setDatabaseConnectorTestBusy(null);
  }
}

export async function deleteDatabaseConnector(a: Args, connectorId: string) {
  // Confirmed in the shared ConfirmDialog (typed name); a refusal is thrown to the dialog.
  try {
    await a.readJson(`/admin/chat/api/panel/database-connectors/${connectorId}`, { method: "DELETE" });
    a.setDatabaseConnectors((prev) => prev.filter((item) => item.id !== connectorId));
    a.setDatabaseTools((prev) => prev.filter((item) => item.connector_id !== connectorId));
    a.setDatabaseConnectorTestResult((prev) => withoutKey(prev, connectorId));
    a.setDatabaseConnectorDrafts((prev) => withoutKey(prev, connectorId));
    a.setExpandedDatabaseConnector((current) => (current === connectorId ? null : current));
    a.setDatabaseToolForm((prev) => ({
      ...prev,
      connector_id:
        prev.connector_id === connectorId
          ? a.databaseConnectors.find((item) => item.id !== connectorId)?.id || ""
          : prev.connector_id,
    }));
  } catch (err) {
    a.setDatabaseConnectorError(err instanceof Error ? err.message : "Failed to delete database connector");
    throw err;
  }
}
