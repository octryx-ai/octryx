// State hooks, loaders and action wiring behind useAdminUsersTabModel, split by concern; the hooks run in the
// model in the same order.
import { useCallback, useMemo, useState } from "react";

import { createAdminGroupActions } from "./adminGroupActions";
import { createAdminRoleActions } from "./adminRoleActions";
import { createAdminUserActions } from "./adminUserActions";
import { DEFAULT_ROLE_PERMISSION_CATALOG } from "./rolePermissionCatalog";
import { normalizeRoleRow } from "./rolePayload";
import type { useConfirmAction } from "../confirm/useConfirmAction";
import type {
  AdminIdentityGroupRow,
  AdminReadJsonFn,
  AdminRolePermission,
  AdminRoleRow,
  AdminUserOidcIdentityRow,
  AdminUsersTabCtx,
  AdminUserRow,
} from "./identityTypes";

export function useIdentityCatalogState() {
  const [roles, setRoles] = useState<AdminRoleRow[]>([]);
  const [rolePermissionCatalog, setRolePermissionCatalog] = useState<
    AdminRolePermission[]
  >([]);
  const [editingRole, setEditingRole] = useState<AdminRoleRow | null>(null);
  const [showCreateRole, setShowCreateRole] = useState(false);
  const [editingGroup, setEditingGroup] =
    useState<AdminIdentityGroupRow | null>(null);
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [groups, setGroups] = useState<AdminIdentityGroupRow[]>([]);
  const [roleName, setRoleName] = useState("");
  const [roleDescription, setRoleDescription] = useState("");
  const [groupName, setGroupName] = useState("");
  const [groupDescription, setGroupDescription] = useState("");
  const [roleLoading, setRoleLoading] = useState<string | null>(null);
  const [roleError, setRoleError] = useState<string | null>(null);
  const [groupLoading, setGroupLoading] = useState<string | null>(null);
  const [groupError, setGroupError] = useState<string | null>(null);
  return {
    roles, setRoles, rolePermissionCatalog, setRolePermissionCatalog, editingRole, setEditingRole,
    showCreateRole, setShowCreateRole, editingGroup, setEditingGroup, showCreateGroup, setShowCreateGroup,
    groups, setGroups, roleName, setRoleName, roleDescription, setRoleDescription, groupName, setGroupName,
    groupDescription, setGroupDescription, roleLoading, setRoleLoading, roleError, setRoleError,
    groupLoading, setGroupLoading, groupError, setGroupError,
  };
}

export function useUserAccountsState() {
  const [userQuery, setUserQuery] = useState("");
  const [userStatusFilter, setUserStatusFilter] = useState<
    "all" | "active" | "inactive"
  >("all");
  const [editingUser, setEditingUser] = useState<AdminUserRow | null>(null);
  const [userActionLoading, setUserActionLoading] = useState<string | null>(
    null,
  );
  const [userActionError, setUserActionError] = useState<string | null>(null);
  const [oidcIdentities, setOidcIdentities] = useState<
    AdminUserOidcIdentityRow[]
  >([]);
  const [oidcIdentityLoading, setOidcIdentityLoading] = useState(false);
  const [oidcIdentityError, setOidcIdentityError] = useState<string | null>(
    null,
  );
  return {
    userQuery, setUserQuery, userStatusFilter, setUserStatusFilter, editingUser, setEditingUser,
    userActionLoading, setUserActionLoading, userActionError, setUserActionError,
    oidcIdentities, setOidcIdentities, oidcIdentityLoading, setOidcIdentityLoading, oidcIdentityError, setOidcIdentityError,
  };
}

export type IdentityCatalogState = ReturnType<typeof useIdentityCatalogState>;
export type UserAccountsState = ReturnType<typeof useUserAccountsState>;

export function useUsersTabDerived(roles: AdminRoleRow[], users: AdminUserRow[], userQuery: string, userStatusFilter: string) {
  const roleNames = useMemo(() => roles.map((role) => role.name), [roles]);
  const filteredUsers = useMemo(() => {
    const query = userQuery.trim().toLowerCase();
    return users.filter((user) => {
      const matchesQuery =
        !query ||
        user.username.toLowerCase().includes(query) ||
        user.email.toLowerCase().includes(query) ||
        (user.display_name || "").toLowerCase().includes(query);
      const matchesStatus =
        userStatusFilter === "all" ||
        (userStatusFilter === "active" && user.is_active) ||
        (userStatusFilter === "inactive" && !user.is_active);
      return matchesQuery && matchesStatus;
    });
  }, [userQuery, userStatusFilter, users]);
  return { roleNames, filteredUsers };
}

const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

async function loadRolesInto(readJson: AdminReadJsonFn, catalog: Pick<IdentityCatalogState, "setRoles" | "setRoleError">) {
  try {
    const data = await readJson<AdminRoleRow[]>("/admin/chat/api/panel/roles");
    catalog.setRoles(Array.isArray(data) ? data.map(normalizeRoleRow) : []);
    catalog.setRoleError(null);
  } catch (error) {
    catalog.setRoleError(errorText(error, "Failed to load roles"));
  }
}

async function loadRolePermissionCatalogInto(
  readJson: AdminReadJsonFn,
  catalog: Pick<IdentityCatalogState, "setRolePermissionCatalog" | "setRoleError">,
) {
  try {
    const data = await readJson<AdminRolePermission[]>("/admin/chat/api/panel/role-permission-catalog");
    catalog.setRolePermissionCatalog(Array.isArray(data) ? data : DEFAULT_ROLE_PERMISSION_CATALOG);
    catalog.setRoleError(null);
  } catch (error) {
    catalog.setRolePermissionCatalog(DEFAULT_ROLE_PERMISSION_CATALOG);
    catalog.setRoleError(
      error instanceof Error
        ? `${error.message}. Using local permission catalog fallback.`
        : "Failed to load role permissions. Using local permission catalog fallback.",
    );
  }
}

async function loadGroupsInto(readJson: AdminReadJsonFn, catalog: Pick<IdentityCatalogState, "setGroups" | "setGroupError">) {
  try {
    const data = await readJson<AdminIdentityGroupRow[]>("/admin/chat/api/panel/identity-groups");
    catalog.setGroups(data);
    catalog.setGroupError(null);
  } catch (error) {
    catalog.setGroupError(errorText(error, "Failed to load groups"));
  }
}

// The catalog setters are stable state setters, so the loaders keep one identity per readJson.
export function useIdentityCatalogLoaders(readJson: AdminReadJsonFn, catalog: IdentityCatalogState) {
  const { setRoles, setRoleError, setRolePermissionCatalog, setGroups, setGroupError } = catalog;
  const loadRoles = useCallback(
    () => loadRolesInto(readJson, { setRoles, setRoleError }),
    [readJson, setRoles, setRoleError],
  );
  const loadRolePermissionCatalog = useCallback(
    () => loadRolePermissionCatalogInto(readJson, { setRolePermissionCatalog, setRoleError }),
    [readJson, setRolePermissionCatalog, setRoleError],
  );
  const loadGroups = useCallback(
    () => loadGroupsInto(readJson, { setGroups, setGroupError }),
    [readJson, setGroups, setGroupError],
  );
  return { loadRoles, loadRolePermissionCatalog, loadGroups };
}

type UsersTabActionArgs = Pick<
  AdminUsersTabCtx,
  "readJson" | "onRoleChange" | "onDeactivateUser" | "onUpdateUser" | "onResetUserPassword"
> & {
  ask: ReturnType<typeof useConfirmAction>["ask"];
  catalog: IdentityCatalogState;
  accounts: UserAccountsState;
  loadUserApiKeys: Parameters<typeof createAdminUserActions>[0]["loadUserApiKeys"];
  loadGroups: () => Promise<void>;
};

export function createUsersTabActions({ readJson, ask, catalog, accounts, loadUserApiKeys, loadGroups, ...callbacks }: UsersTabActionArgs) {
  const roleActions = createAdminRoleActions({
    readJson, ask, roleName: catalog.roleName, roleDescription: catalog.roleDescription, setRoles: catalog.setRoles,
    setRoleName: catalog.setRoleName, setRoleDescription: catalog.setRoleDescription, setRoleLoading: catalog.setRoleLoading,
    setRoleError: catalog.setRoleError, setShowCreateRole: catalog.setShowCreateRole,
  });
  const groupActions = createAdminGroupActions({
    readJson, ask, groupName: catalog.groupName, groupDescription: catalog.groupDescription, setGroups: catalog.setGroups,
    setGroupName: catalog.setGroupName, setGroupDescription: catalog.setGroupDescription,
    setGroupLoading: catalog.setGroupLoading, setGroupError: catalog.setGroupError, setShowCreateGroup: catalog.setShowCreateGroup,
  });
  const userActions = createAdminUserActions({
    readJson, ask, loadUserApiKeys, loadGroups, ...callbacks,
    setEditingUser: accounts.setEditingUser, setUserActionLoading: accounts.setUserActionLoading,
    setUserActionError: accounts.setUserActionError, setOidcIdentities: accounts.setOidcIdentities,
    setOidcIdentityLoading: accounts.setOidcIdentityLoading, setOidcIdentityError: accounts.setOidcIdentityError,
  });
  return { roleActions, groupActions, userActions };
}
