import type { FormEvent } from "react";
import { loadLocalBootstrap, loadSetupGuideStatus, refreshBootstrap } from "./adminBootstrapRequests";
import type { UseAdminBootstrapUserApprovalArgs } from "./adminBootstrapUserTypes";
import { type AdminUserUpdate, changeUserRoles, createUser, resetUserPassword, updateUser } from "./adminUserRequests";

export function useAdminBootstrapUserApproval(args: UseAdminBootstrapUserApprovalArgs) {
  const { readJson, setUsers } = args;
  const loadSetupGuide = () => loadSetupGuideStatus(args);
  const loadLocalBootstrapState = () => loadLocalBootstrap(args);
  const refreshBootstrapContext = () => refreshBootstrap(args);

  // The User accounts page confirms in place before it calls this; a refusal is thrown so the
  // confirmation shows it, never an alert.
  const handleDeactivateUser = async (userId: string) => {
    await readJson(`/admin/chat/api/panel/users/${userId}`, {
      method: "DELETE",
    });
    setUsers((prev) =>
      prev.map((user) =>
        user.id === userId ? { ...user, is_active: false } : user,
      ),
    );
  };

  const handleRoleChange = (userId: string, roles: string[]) => changeUserRoles(args, userId, roles);
  const handleUpdateUser = (userId: string, payload: AdminUserUpdate) => updateUser(args, userId, payload);
  const handleResetUserPassword = (userId: string, password: string) => resetUserPassword(args, userId, password);
  const handleCreateUser = (event: FormEvent) => createUser(args, event);

  return {
    handleCreateUser,
    handleDeactivateUser,
    handleResetUserPassword,
    handleRoleChange,
    handleUpdateUser,
    loadLocalBootstrapState,
    loadSetupGuide,
    refreshBootstrapContext,
  };
}
