// Database tool actions: create, open the create form for a connector, and delete SQL tools.
import type { AdminDatabaseTool } from "../types/adminPanelTypes.usersProviders";
import type { UseAdminConnectorManagementArgs } from "./useAdminConnectorManagement.types";

type DatabaseToolActionArgs = Pick<
  UseAdminConnectorManagementArgs,
  | "readJson"
  | "databaseToolForm"
  | "setDatabaseToolForm"
  | "setDatabaseToolSaving"
  | "setDatabaseToolError"
  | "setShowAddDatabaseTool"
  | "setDatabaseTools"
>;

export function createDatabaseToolActions({
  readJson,
  databaseToolForm,
  setDatabaseToolForm,
  setDatabaseToolSaving,
  setDatabaseToolError,
  setShowAddDatabaseTool,
  setDatabaseTools,
}: DatabaseToolActionArgs) {
  const handleCreateDatabaseTool = async () => {
    setDatabaseToolSaving(true);
    setDatabaseToolError(null);
    try {
      const body = {
        connector_id: databaseToolForm.connector_id,
        tool_name: databaseToolForm.tool_name.trim(),
        display_name: databaseToolForm.display_name.trim(),
        description: databaseToolForm.description.trim(),
        sql_template: databaseToolForm.sql_template,
        parameters_schema: JSON.parse(
          databaseToolForm.parameters_schema || "{}",
        ),
        row_level_security_rules: databaseToolForm.row_level_security_rules
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
        allowed_roles: databaseToolForm.allowed_roles
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        max_rows: Number(databaseToolForm.max_rows || "100"),
        timeout_seconds: Number(databaseToolForm.timeout_seconds || "30"),
        is_active: databaseToolForm.is_active,
      };
      const created = await readJson<AdminDatabaseTool>(
        "/admin/chat/api/panel/database-tools",
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      setDatabaseTools((prev) =>
        [...prev, created].sort((a, b) =>
          a.tool_name.localeCompare(b.tool_name),
        ),
      );
      setDatabaseToolForm((prev) => ({
        ...prev,
        tool_name: "database_tool_",
        display_name: "",
        description: "",
        sql_template: "select 1 as example",
        parameters_schema:
          '{\n  "type": "object",\n  "properties": {},\n  "required": []\n}',
      }));
      setShowAddDatabaseTool(false);
    } catch (err) {
      setDatabaseToolError(
        err instanceof Error ? err.message : "Failed to create database tool",
      );
    } finally {
      setDatabaseToolSaving(false);
    }
  };

  const openCreateDatabaseTool = (connectorId: string) => {
    setDatabaseToolError(null);
    setDatabaseToolForm((prev) => ({
      ...prev,
      connector_id: connectorId || prev.connector_id,
    }));
    setShowAddDatabaseTool(true);
  };

  const handleDeleteDatabaseTool = async (toolId: string, toolName: string) => {
    if (!confirm(`Delete database tool "${toolName}"?`)) return;
    try {
      await readJson(`/admin/chat/api/panel/database-tools/${toolId}`, {
        method: "DELETE",
      });
      setDatabaseTools((prev) => prev.filter((item) => item.id !== toolId));
    } catch (err) {
      setDatabaseToolError(
        err instanceof Error ? err.message : "Failed to delete database tool",
      );
    }
  };

  return { handleCreateDatabaseTool, handleDeleteDatabaseTool, openCreateDatabaseTool };
}
