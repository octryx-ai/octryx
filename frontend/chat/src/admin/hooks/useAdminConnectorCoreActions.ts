import type { AdminConnector } from "../types/adminPanelTypes.usersProviders";
import type { UseAdminConnectorManagementArgs } from "./useAdminConnectorManagement.types";
import { buildConnectorSaveBody } from "./connectorSaveBody";
import { connectorDraftActions } from "./connectorDraftActions";
import { githubConnectorRepositoryActions } from "./githubConnectorRepositoryActions";
import { withSecretRebindConfirmation } from "../secretRebind/secretRebindModel";
import {
  deleteConnector,
  expandConnector,
  saveConnector,
  setConnectorActive,
  testConnector,
  type ConnectorSaveOutcome,
} from "./connectorCoreRequests";

export function useAdminConnectorCoreActions(args: UseAdminConnectorManagementArgs) {
  const {
    getConnectorDraft,
    getConnectorPolicyDraft,
    setConnectorField,
    setConnectorPolicyField,
    addConnectorExtraTool,
    removeConnectorExtraTool,
    toggleConnectorDisabledTool,
  } = connectorDraftActions(args);
  const { handleLoadGithubConnectorRepositories, handleCreateGithubConnectorRepository } =
    githubConnectorRepositoryActions(args);

  const handleExpandConnector = (toolName: string, connector: AdminConnector) =>
    expandConnector(args, toolName, connector, handleLoadGithubConnectorRepositories);

  // `confirmedBody`: the refused body, resent unchanged with confirm_secret_rebind=true (the explicit confirm step).
  const handleSaveConnector = (
    toolName: string,
    connector: AdminConnector,
    confirmedBody?: Record<string, unknown>,
  ): Promise<ConnectorSaveOutcome> =>
    saveConnector(args, toolName, connector, () =>
      confirmedBody
        ? withSecretRebindConfirmation(confirmedBody)
        : buildConnectorSaveBody(connector, getConnectorDraft(toolName), getConnectorPolicyDraft(toolName)));

  const handleTestConnector = (toolName: string) => testConnector(args, toolName);
  const handleDeleteConnector = (toolName: string, confirmName: string) =>
    deleteConnector(args, toolName, confirmName);
  const handleSetConnectorActive = (toolName: string, isActive: boolean) =>
    setConnectorActive(args, toolName, isActive);

  return {
    addConnectorExtraTool,
    getConnectorDraft,
    getConnectorPolicyDraft,
    handleCreateGithubConnectorRepository,
    handleDeleteConnector,
    handleExpandConnector,
    handleSetConnectorActive,
    handleLoadGithubConnectorRepositories,
    handleSaveConnector,
    handleTestConnector,
    removeConnectorExtraTool,
    setConnectorField,
    setConnectorPolicyField,
    toggleConnectorDisabledTool,
  };
}
