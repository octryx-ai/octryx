import type { FormEvent } from "react";

import { AdminHeaderActions } from "../AdminHeaderSlot";
import { AdminUserEditPanel } from "./AdminUserEditPanel";
import { AdminUserAccountsTable } from "./AdminUserAccountsTable";
import { AdminUserCreateForm } from "./AdminUserCreateForm";
import type {
  AdminIdentityGroupRow,
  AdminUserApiKeyRow,
  AdminUserOidcIdentityRow,
  AdminUserRow,
} from "./identityTypes";

type AdminUserAccountsPanelProps = {
  users: AdminUserRow[];
  totalUsers: number;
  roleNames: string[];
  groups: AdminIdentityGroupRow[];
  currentUserId?: string;
  userQuery: string;
  userStatusFilter: "all" | "active" | "inactive";
  userActionError: string | null;
  userActionLoading: string | null;
  showCreateUser: boolean;
  newUsername: string;
  newEmail: string;
  newPassword: string;
  newDisplayName: string;
  newAccountType: string;
  newRole: string;
  formError: string | null;
  formLoading: boolean;
  editingUser: AdminUserRow | null;
  apiKeys: AdminUserApiKeyRow[];
  apiKeyName: string;
  apiKeyScopes: string;
  apiKeyExpiresAt: string;
  apiKeyCreatedSecret: string | null;
  apiKeyError: string | null;
  apiKeyLoading: string | null;
  oidcIdentities: AdminUserOidcIdentityRow[];
  oidcIdentityError: string | null;
  oidcIdentityLoading: boolean;
  setShowCreateUser: (value: boolean | ((value: boolean) => boolean)) => void;
  setUserQuery: (value: string) => void;
  setUserStatusFilter: (value: "all" | "active" | "inactive") => void;
  setNewUsername: (value: string) => void;
  setNewEmail: (value: string) => void;
  setNewPassword: (value: string) => void;
  setNewDisplayName: (value: string) => void;
  setNewAccountType: (value: string) => void;
  setNewRoles: (value: string) => void;
  setApiKeyName: (value: string) => void;
  setApiKeyScopes: (value: string) => void;
  setApiKeyExpiresAt: (value: string) => void;
  onCreateUser: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onEditUser: (user: AdminUserRow) => void;
  onCloseEditPanel: () => void;
  onSaveProfile: (
    userId: string,
    payload: {
      username: string;
      email: string;
      display_name: string;
      account_type: string;
    },
  ) => Promise<void>;
  onSaveRole: (userId: string, roles: string[]) => void | Promise<void>;
  onSaveGroups: (
    user: AdminUserRow,
    groupIds: string[],
  ) => void | Promise<void>;
  onResetPassword: (userId: string, password: string) => Promise<void>;
  onToggleUserStatus: (user: AdminUserRow) => void | Promise<void>;
  onCreateApiKey: (event: FormEvent) => void;
  onRevokeApiKey: (key: AdminUserApiKeyRow) => void;
};

// Search and the status filter above the table.
function UserAccountsToolbar({ userQuery, userStatusFilter, setUserQuery, setUserStatusFilter }: Pick<
  AdminUserAccountsPanelProps, "userQuery" | "userStatusFilter" | "setUserQuery" | "setUserStatusFilter"
>) {
  return (
    <section className="admin-users__toolbar">
      <input
        className="admin-users__toolbar-input"
        value={userQuery}
        onChange={(e) => setUserQuery(e.target.value)}
        placeholder="Search users..."
        aria-label="Search users"
      />
      <select
        className="admin-users__toolbar-select"
        value={userStatusFilter}
        onChange={(e) =>
          setUserStatusFilter(e.target.value as "all" | "active" | "inactive")
        }
        aria-label="Filter user status"
      >
        <option value="all">All users</option>
        <option value="active">Active users</option>
        <option value="inactive">Inactive users</option>
      </select>
    </section>
  );
}

// The create form, with the panel's drafts and setters.
function UserCreateSection({
  roleNames,
  newUsername,
  newEmail,
  newPassword,
  newDisplayName,
  newAccountType,
  newRole,
  formError,
  formLoading,
  setNewUsername,
  setNewEmail,
  setNewPassword,
  setNewDisplayName,
  setNewAccountType,
  setNewRoles,
  onCreateUser,
  setShowCreateUser,
}: AdminUserAccountsPanelProps) {
  return (
    <AdminUserCreateForm
      roleNames={roleNames}
      newUsername={newUsername}
      newEmail={newEmail}
      newPassword={newPassword}
      newDisplayName={newDisplayName}
      newAccountType={newAccountType}
      newRole={newRole}
      formError={formError}
      formLoading={formLoading}
      setNewUsername={setNewUsername}
      setNewEmail={setNewEmail}
      setNewPassword={setNewPassword}
      setNewDisplayName={setNewDisplayName}
      setNewAccountType={setNewAccountType}
      setNewRoles={setNewRoles}
      onCreateUser={onCreateUser}
      onClose={() => setShowCreateUser(false)}
    />
  );
}

// The edit panel of one user: profile, roles, groups, password, API keys and sign-in identities.
function UserEditSection({
  editingUser,
  roleNames,
  groups,
  apiKeys,
  apiKeyName,
  apiKeyScopes,
  apiKeyExpiresAt,
  apiKeyCreatedSecret,
  apiKeyError,
  apiKeyLoading,
  oidcIdentities,
  oidcIdentityError,
  oidcIdentityLoading,
  userActionLoading,
  setApiKeyName,
  setApiKeyScopes,
  setApiKeyExpiresAt,
  onCloseEditPanel,
  onSaveProfile,
  onSaveRole,
  onSaveGroups,
  onResetPassword,
  onCreateApiKey,
  onRevokeApiKey,
}: AdminUserAccountsPanelProps & { editingUser: AdminUserRow }) {
  return (
    <AdminUserEditPanel
      user={editingUser}
      roleNames={roleNames}
      groups={groups}
      apiKeys={apiKeys}
      apiKeyName={apiKeyName}
      apiKeyScopes={apiKeyScopes}
      apiKeyExpiresAt={apiKeyExpiresAt}
      apiKeyCreatedSecret={apiKeyCreatedSecret}
      apiKeyError={apiKeyError}
      apiKeyLoading={apiKeyLoading}
      oidcIdentities={oidcIdentities}
      oidcIdentityError={oidcIdentityError}
      oidcIdentityLoading={oidcIdentityLoading}
      userActionLoading={userActionLoading}
      setApiKeyName={setApiKeyName}
      setApiKeyScopes={setApiKeyScopes}
      setApiKeyExpiresAt={setApiKeyExpiresAt}
      onClose={onCloseEditPanel}
      onSaveProfile={onSaveProfile}
      onSaveRole={onSaveRole}
      onSaveGroups={onSaveGroups}
      onResetPassword={onResetPassword}
      onCreateApiKey={onCreateApiKey}
      onRevokeApiKey={onRevokeApiKey}
    />
  );
}

export function AdminUserAccountsPanel(props: AdminUserAccountsPanelProps) {
  const {
    users,
    totalUsers,
    groups,
    currentUserId,
    userActionError,
    userActionLoading,
    showCreateUser,
    editingUser,
    setShowCreateUser,
    onEditUser,
    onToggleUserStatus,
  } = props;
  return (
    <div className="admin-users">
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => setShowCreateUser(true)}
          data-testid="user-create-open"
        >
          {"New user"}
        </button>
      </AdminHeaderActions>
      <div className="admin-panel__section-header">
        <span>
          User accounts ({users.length}/{totalUsers})
        </span>
      </div>

      <UserAccountsToolbar {...props} />

      {userActionError ? (
        <div className="admin-panel__error">{userActionError}</div>
      ) : null}

      {showCreateUser ? <UserCreateSection {...props} /> : null}

      <AdminUserAccountsTable
        users={users}
        groups={groups}
        currentUserId={currentUserId}
        userActionLoading={userActionLoading}
        onEditUser={onEditUser}
        onToggleUserStatus={onToggleUserStatus}
      />

      {editingUser ? <UserEditSection {...props} editingUser={editingUser} /> : null}
    </div>
  );
}
