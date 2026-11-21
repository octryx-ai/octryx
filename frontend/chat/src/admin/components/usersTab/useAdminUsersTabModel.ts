// State, loading and actions behind the People pages: roles, groups, user accounts, access and identity providers.
import { useEffect } from "react";

import {
  createUsersTabActions,
  useIdentityCatalogLoaders,
  useIdentityCatalogState,
  useUserAccountsState,
  useUsersTabDerived,
} from "./adminUsersTabState";
import { useAdminEffectiveAccess } from "./useAdminEffectiveAccess";
import { useAdminIdentityProviders } from "./useAdminIdentityProviders";
import { useAdminUserApiKeys } from "./useAdminUserApiKeys";
import type { useConfirmAction } from "../confirm/useConfirmAction";
import type { AdminUsersTabCtx } from "./identityTypes";

export type AdminUsersSection = "users" | "roles" | "groups" | "providers" | "access";

type AdminUsersTabModelArgs = Pick<
  AdminUsersTabCtx,
  "users" | "readJson" | "onRoleChange" | "onDeactivateUser" | "onUpdateUser" | "onResetUserPassword"
> & {
  section: AdminUsersSection;
  ask: ReturnType<typeof useConfirmAction>["ask"];
};


function publicCatalogState(c: ReturnType<typeof useIdentityCatalogState>) {
  return {
    roles: c.roles, rolePermissionCatalog: c.rolePermissionCatalog, editingRole: c.editingRole, setEditingRole: c.setEditingRole,
    showCreateRole: c.showCreateRole, setShowCreateRole: c.setShowCreateRole, editingGroup: c.editingGroup,
    setEditingGroup: c.setEditingGroup, showCreateGroup: c.showCreateGroup, setShowCreateGroup: c.setShowCreateGroup,
    groups: c.groups, roleName: c.roleName, setRoleName: c.setRoleName, roleDescription: c.roleDescription,
    setRoleDescription: c.setRoleDescription, groupName: c.groupName, setGroupName: c.setGroupName,
    groupDescription: c.groupDescription, setGroupDescription: c.setGroupDescription, roleLoading: c.roleLoading,
    roleError: c.roleError, groupLoading: c.groupLoading, groupError: c.groupError,
  };
}

function publicAccountsState(a: ReturnType<typeof useUserAccountsState>) {
  return {
    userQuery: a.userQuery, setUserQuery: a.setUserQuery, userStatusFilter: a.userStatusFilter,
    setUserStatusFilter: a.setUserStatusFilter, editingUser: a.editingUser, setEditingUser: a.setEditingUser,
    userActionLoading: a.userActionLoading, userActionError: a.userActionError, oidcIdentities: a.oidcIdentities,
    oidcIdentityLoading: a.oidcIdentityLoading, oidcIdentityError: a.oidcIdentityError,
  };
}

export function useAdminUsersTabModel({
  users,
  readJson,
  onRoleChange,
  onDeactivateUser,
  onUpdateUser,
  onResetUserPassword,
  section,
  ask,
}: AdminUsersTabModelArgs) {
  const catalog = useIdentityCatalogState();
  const accounts = useUserAccountsState();
  const { accessRows, accessLoading, accessError, loadAccessDiagnostics } =
    useAdminEffectiveAccess(readJson);
  const userApiKeys = useAdminUserApiKeys(readJson);
  const identityProviders = useAdminIdentityProviders(readJson);
  const { loadIdentityProviders } = identityProviders;
  const { roleNames, filteredUsers } = useUsersTabDerived(catalog.roles, users, accounts.userQuery, accounts.userStatusFilter);
  const { loadRoles, loadRolePermissionCatalog, loadGroups } = useIdentityCatalogLoaders(readJson, catalog);

  useEffect(() => {
    void loadRoles();
    void loadRolePermissionCatalog();
    void loadGroups();
    if (section === "providers") {
      void loadIdentityProviders();
    }
    if (section === "access") {
      void loadAccessDiagnostics();
    }
  }, [
    loadIdentityProviders,
    loadAccessDiagnostics,
    loadGroups,
    loadRolePermissionCatalog,
    loadRoles,
    section,
  ]);

  const { roleActions, groupActions, userActions } = createUsersTabActions({
    readJson, ask, catalog, accounts, loadUserApiKeys: userApiKeys.loadUserApiKeys, loadGroups,
    onRoleChange, onDeactivateUser, onUpdateUser, onResetUserPassword,
  });

  return {
    ...publicCatalogState(catalog), ...publicAccountsState(accounts),
    accessRows, accessLoading, accessError, loadAccessDiagnostics, userApiKeys, identityProviders,
    loadIdentityProviders, roleNames, filteredUsers, loadRoles, loadGroups,
    ...roleActions, ...groupActions, ...userActions,
  };
}
