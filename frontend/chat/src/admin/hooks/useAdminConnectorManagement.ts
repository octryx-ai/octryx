import { useAdminConnectorCoreActions } from "./useAdminConnectorCoreActions";
import { useAdminConnectorDatabaseActions } from "./useAdminConnectorDatabaseActions";
import type { UseAdminConnectorManagementArgs } from "./useAdminConnectorManagement.types";

export function useAdminConnectorManagement(
  args: UseAdminConnectorManagementArgs,
) {
  const coreActions = useAdminConnectorCoreActions(args);
  const databaseActions = useAdminConnectorDatabaseActions(args);

  return {
    ...coreActions,
    ...databaseActions,
  };
}
