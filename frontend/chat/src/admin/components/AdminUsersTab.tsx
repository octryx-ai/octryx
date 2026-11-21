import type { ComponentProps, ReactNode } from "react";

import { AdminEffectiveAccessPanel } from "./usersTab/AdminEffectiveAccessPanel";
import { AdminGroupsPanel } from "./usersTab/AdminGroupsPanel";
import { AdminIdentityProvidersPanel } from "./usersTab/AdminIdentityProvidersPanel";
import { AdminUserAccountsPanel } from "./usersTab/AdminUserAccountsPanel";
import { AdminRolesPanel } from "./usersTab/AdminRolesPanel";
import { useAdminUsersTabModel, type AdminUsersSection } from "./usersTab/useAdminUsersTabModel";
import { useConfirmAction } from "./confirm/useConfirmAction";
import type { AdminUsersTabCtx } from "./usersTab/identityTypes";

type AdminUsersTabProps = {
  ctx: Record<string, unknown>;
  section?: AdminUsersSection;
};

type Model = ReturnType<typeof useAdminUsersTabModel>;

export function AdminUsersTab({ ctx, section = "users" }: AdminUsersTabProps) {
  const { users, readJson, onRoleChange, onDeactivateUser, onUpdateUser, onResetUserPassword } = ctx as AdminUsersTabCtx;
  const confirmAction = useConfirmAction();
  const model = useAdminUsersTabModel({
    users, readJson, onRoleChange, onDeactivateUser, onUpdateUser, onResetUserPassword, section, ask: confirmAction.ask,
  });
  const withConfirm = (node: ReactNode) => <>{confirmAction.notice}{node}{confirmAction.dialog}</>;

  if (section === "roles") {
    return withConfirm(<UsersRolesPanel model={model} />);
  }

  if (section === "groups") {
    return withConfirm(<UsersGroupsPanel model={model} />);
  }

  if (section === "access") {
    const { accessRows, accessLoading, accessError, loadAccessDiagnostics } = model;
    return (
      <AdminEffectiveAccessPanel
        rows={accessRows}
        loading={accessLoading}
        error={accessError}
        onRefresh={() => void loadAccessDiagnostics()}
      />
    );
  }

  if (section === "providers") {
    return <UsersProvidersPanel model={model} />;
  }

  return withConfirm(<UsersAccountsPanel model={model} ctx={ctx as AdminUsersTabCtx} />);
}

function UsersRolesPanel({ model }: { model: Model }) {
  const {
    roles, rolePermissionCatalog, roleName, roleDescription, roleLoading, roleError, editingRole, showCreateRole, setRoleName,
    setRoleDescription, setShowCreateRole, handleCreateRole, loadRoles, setEditingRole, handleDeleteRole,
    handleUpdateRoleDescription, handleUpdateRolePermissions,
  } = model;
  return (
    <AdminRolesPanel
      roles={roles}
      permissionCatalog={rolePermissionCatalog}
      roleName={roleName}
      roleDescription={roleDescription}
      roleLoading={roleLoading}
      roleError={roleError}
      editingRole={editingRole}
      showCreateRole={showCreateRole}
      setRoleName={setRoleName}
      setRoleDescription={setRoleDescription}
      setShowCreateRole={setShowCreateRole}
      onCreateRole={(e) => void handleCreateRole(e)}
      onLoadRoles={() => void loadRoles()}
      onEditRole={setEditingRole}
      onCloseEditPanel={() => setEditingRole(null)}
      onDeleteRole={handleDeleteRole}
      onUpdateRoleDescription={(role, description) =>
        void handleUpdateRoleDescription(role, description)
      }
      onUpdateRolePermissions={(role, permissions) =>
        void handleUpdateRolePermissions(role, permissions)
      }
    />
  );
}

function UsersGroupsPanel({ model }: { model: Model }) {
  const {
    groups, groupName, groupDescription, groupError, groupLoading, editingGroup, showCreateGroup, setGroupName,
    setGroupDescription, setShowCreateGroup, handleCreateGroup, loadGroups, setEditingGroup, handleUpdateGroup,
    handleToggleGroup, handleDeleteGroup,
  } = model;
  return (
    <AdminGroupsPanel
      groups={groups}
      groupName={groupName}
      groupDescription={groupDescription}
      groupError={groupError}
      groupLoading={groupLoading}
      editingGroup={editingGroup}
      showCreateGroup={showCreateGroup}
      setGroupName={setGroupName}
      setGroupDescription={setGroupDescription}
      setShowCreateGroup={setShowCreateGroup}
      onCreateGroup={(e) => void handleCreateGroup(e)}
      onRefresh={() => void loadGroups()}
      onEditGroup={setEditingGroup}
      onCloseEditPanel={() => setEditingGroup(null)}
      onUpdateGroup={(group, payload) =>
        void handleUpdateGroup(group, payload)
      }
      onToggleGroup={(group) => void handleToggleGroup(group)}
      onDeleteGroup={handleDeleteGroup}
    />
  );
}

function UsersProvidersPanel({ model }: { model: Model }) {
  const { identityProviders, roles, groups, loadIdentityProviders } = model;
  return (
    <AdminIdentityProvidersPanel
      providers={identityProviders.providers}
      drafts={identityProviders.providerDrafts}
      roles={roles}
      groups={groups}
      loading={identityProviders.providerLoading}
      error={identityProviders.providerError}
      onRefresh={() => void loadIdentityProviders()}
      onCreateProvider={(payload) =>
        void identityProviders.createIdentityProvider(payload)
      }
      onUpdateDraft={identityProviders.updateDraft}
      onSave={(provider) =>
        void identityProviders.saveIdentityProvider(provider, roles, groups)
      }
    />
  );
}

// The account list's props: the create form from the context, the list, the edit panel and the API keys from the model.
function accountsPanelProps(model: Model, ctx: AdminUsersTabCtx): ComponentProps<typeof AdminUserAccountsPanel> {
  const {
    users, currentUserId, showCreateUser, setShowCreateUser, newUsername, setNewUsername, newEmail, setNewEmail, newPassword,
    setNewPassword, newDisplayName, setNewDisplayName, newAccountType, setNewAccountType, newRoles, setNewRoles, formError,
    formLoading, onCreateUser,
  } = ctx;
  const {
    filteredUsers, roleNames, groups, userQuery, userStatusFilter, userActionError, userActionLoading, editingUser,
    userApiKeys, oidcIdentities, oidcIdentityError, oidcIdentityLoading, setUserQuery, setUserStatusFilter, openEditUser,
    setEditingUser, handleSaveProfile, handleSaveRole, handleGroupChange, handleResetPasswordDirect, handleToggleUserStatus,
  } = model;
  return {
    users: filteredUsers, totalUsers: users.length, roleNames, groups, currentUserId, userQuery, userStatusFilter,
    userActionError, userActionLoading, showCreateUser, newUsername, newEmail, newPassword, newDisplayName,
    newAccountType, newRole: newRoles, formError, formLoading, editingUser, apiKeys: userApiKeys.apiKeys,
    apiKeyName: userApiKeys.apiKeyName, apiKeyScopes: userApiKeys.apiKeyScopes,
    apiKeyExpiresAt: userApiKeys.apiKeyExpiresAt, apiKeyCreatedSecret: userApiKeys.apiKeyCreatedSecret,
    apiKeyError: userApiKeys.apiKeyError, apiKeyLoading: userApiKeys.apiKeyLoading, oidcIdentities, oidcIdentityError,
    oidcIdentityLoading, setShowCreateUser, setUserQuery, setUserStatusFilter, setNewUsername, setNewEmail,
    setNewPassword, setNewDisplayName, setNewAccountType, setNewRoles, setApiKeyName: userApiKeys.setApiKeyName,
    setApiKeyScopes: userApiKeys.setApiKeyScopes, setApiKeyExpiresAt: userApiKeys.setApiKeyExpiresAt, onCreateUser,
    onEditUser: openEditUser, onCloseEditPanel: () => setEditingUser(null), onSaveProfile: handleSaveProfile,
    onSaveRole: handleSaveRole, onSaveGroups: handleGroupChange, onResetPassword: handleResetPasswordDirect,
    onToggleUserStatus: handleToggleUserStatus, onCreateApiKey: userApiKeys.createApiKey,
    onRevokeApiKey: (key) => void userApiKeys.revokeApiKey(key),
  };
}

function UsersAccountsPanel({ model, ctx }: { model: Model; ctx: AdminUsersTabCtx }) {
  return <AdminUserAccountsPanel {...accountsPanelProps(model, ctx)} />;
}
