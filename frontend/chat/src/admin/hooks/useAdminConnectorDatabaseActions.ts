// Database connector actions: drafts, create, save, test and delete connectors; tool actions are composed in.
import type { AdminDatabaseConnector } from "../types/adminPanelTypes.usersProviders";
import type {
  DatabaseConnectorDraft,
  UseAdminConnectorManagementArgs,
} from "./useAdminConnectorManagement.types";
import { createDatabaseToolActions } from "./adminDatabaseToolActions";
import {
  createDatabaseConnector,
  databaseConnectorDraftFrom,
  deleteDatabaseConnector,
  emptyDatabaseConnectorDraft,
  emptyDatabaseConnectorForm,
  saveDatabaseConnector,
  testDatabaseConnector,
} from "./adminDatabaseConnectorActions";

export function useAdminConnectorDatabaseActions(args: UseAdminConnectorManagementArgs) {
  const { setDatabaseConnectorDrafts } = args;
  const resetDatabaseConnectorForm = () => {
    args.setDatabaseConnectorForm(emptyDatabaseConnectorForm());
  };

  const getDatabaseConnectorDraft = (connector: AdminDatabaseConnector): DatabaseConnectorDraft =>
    args.databaseConnectorDrafts[connector.id] || databaseConnectorDraftFrom(connector);

  const setDatabaseConnectorDraftField = (
    connectorId: string,
    field: keyof DatabaseConnectorDraft,
    value: string | boolean,
  ) => {
    setDatabaseConnectorDrafts((prev) => ({
      ...prev,
      [connectorId]: { ...(prev[connectorId] || emptyDatabaseConnectorDraft()), [field]: value },
    }));
  };

  const handleExpandDatabaseConnector = (connector: AdminDatabaseConnector) => {
    args.setExpandedDatabaseConnector((current) => (current === connector.id ? null : connector.id));
    setDatabaseConnectorDrafts((prev) => ({ ...prev, [connector.id]: getDatabaseConnectorDraft(connector) }));
  };

  const handleCreateDatabaseConnector = () => createDatabaseConnector(args, resetDatabaseConnectorForm);
  const handleSaveDatabaseConnector = (connector: AdminDatabaseConnector) =>
    saveDatabaseConnector(args, connector, getDatabaseConnectorDraft(connector));
  const handleTestDatabaseConnector = (connectorId: string) => testDatabaseConnector(args, connectorId);
  const handleDeleteDatabaseConnector = (connectorId: string) => deleteDatabaseConnector(args, connectorId);

  const { handleCreateDatabaseTool, handleDeleteDatabaseTool, openCreateDatabaseTool } =
    createDatabaseToolActions(args);

  return {
    getDatabaseConnectorDraft,
    handleCreateDatabaseConnector,
    handleCreateDatabaseTool,
    handleDeleteDatabaseConnector,
    handleDeleteDatabaseTool,
    handleExpandDatabaseConnector,
    handleSaveDatabaseConnector,
    handleTestDatabaseConnector,
    openCreateDatabaseTool,
    resetDatabaseConnectorForm,
    setDatabaseConnectorDraftField,
  };
}
