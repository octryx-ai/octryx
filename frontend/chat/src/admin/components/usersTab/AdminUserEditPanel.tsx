// Admin user edit panel: profile, roles, groups, password, linked accounts, SSO identities and API keys of one user.
import type { FormEvent } from "react";
import { AdminUserApiKeysSection } from "./AdminUserApiKeysSection";
import { AdminUserGroupsSection } from "./AdminUserGroupsSection";
import { AdminUserOidcIdentitiesPanel } from "./AdminUserOidcIdentitiesPanel";
import { AdminUserProfileSection } from "./AdminUserProfileSection";
import { LinkedAccountsPanel } from "../../../chat/profile/LinkedAccountsPanel";
import type {
  AdminIdentityGroupRow,
  AdminUserApiKeyRow,
  AdminUserOidcIdentityRow,
  AdminUserRow,
} from "./identityTypes";
import { AdminUserPasswordSection, AdminUserRolesSection } from "./adminUserEditSections";
import { createAdminUserEditHandlers, useAdminUserEditState } from "./adminUserEditState";
import { CloseIcon } from "./userEditPanelParts";

/* ── Main panel ─────────────────────────────────────────────── */

export type AdminUserEditPanelProps = {
  user: AdminUserRow | null;
  roleNames: string[];
  groups: AdminIdentityGroupRow[];
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
  userActionLoading: string | null;
  setApiKeyName: (v: string) => void;
  setApiKeyScopes: (v: string) => void;
  setApiKeyExpiresAt: (v: string) => void;
  onClose: () => void;
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
  onCreateApiKey: (event: FormEvent) => void;
  onRevokeApiKey: (key: AdminUserApiKeyRow) => void;
};

function apiKeySectionProps(props: AdminUserEditPanelProps) {
  const { apiKeys, apiKeyName, apiKeyScopes, apiKeyExpiresAt, apiKeyCreatedSecret, apiKeyError, apiKeyLoading,
    setApiKeyName, setApiKeyScopes, setApiKeyExpiresAt, onCreateApiKey, onRevokeApiKey } = props;
  return { apiKeys, apiKeyName, apiKeyScopes, apiKeyExpiresAt, apiKeyCreatedSecret, apiKeyError, apiKeyLoading,
    setApiKeyName, setApiKeyScopes, setApiKeyExpiresAt, onCreateApiKey, onRevokeApiKey };
}

export function AdminUserEditPanel(props: AdminUserEditPanelProps) {
  const { user, roleNames, groups, oidcIdentities, oidcIdentityError, oidcIdentityLoading, onClose } = props;
  const s = useAdminUserEditState(user);

  if (!user) return null;

  const roleOptions = Array.from(new Set([...roleNames, ...s.selectedRoles])).map(
    (name) => ({ id: name, name }),
  );
  const { handleSaveProfile, handleSaveRole, handleSaveGroups, handleResetPassword } = createAdminUserEditHandlers(user, s, props);

  return (
    <div
      className="user-edit-panel__backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="user-edit-panel">
        <div className="user-edit-panel__header">
          <div>
            <p className="user-edit-panel__header-label">Edit user</p>
            <h2 className="user-edit-panel__header-name">{user.username}</h2>
          </div>
          <button type="button" className="user-edit-panel__close" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>

        <div className="user-edit-panel__body">
          <AdminUserProfileSection
            username={s.username} setUsername={s.setUsername} email={s.email} setEmail={s.setEmail}
            displayName={s.displayName} setDisplayName={s.setDisplayName}
            accountType={s.accountType} setAccountType={s.setAccountType}
            profileOk={s.profileOk} profileSaving={s.profileSaving} handleSaveProfile={handleSaveProfile}
          />
          <AdminUserRolesSection roleOptions={roleOptions} selectedRoles={s.selectedRoles} setSelectedRoles={s.setSelectedRoles}
            roleSaving={s.roleSaving} onSave={() => void handleSaveRole()} />
          <AdminUserGroupsSection
            groups={groups} selectedGroupIds={s.selectedGroupIds} setSelectedGroupIds={s.setSelectedGroupIds}
            groupsSaving={s.groupsSaving} handleSaveGroups={handleSaveGroups}
          />
          <AdminUserPasswordSection newPassword={s.newPassword} setNewPassword={s.setNewPassword} pwOk={s.pwOk}
            pwSaving={s.pwSaving} onSubmit={(e) => void handleResetPassword(e)} />
          <LinkedAccountsPanel key={user.id} userId={user.id} ownAccounts={false} />
          <AdminUserOidcIdentitiesPanel
            identities={oidcIdentities}
            loading={oidcIdentityLoading}
            error={oidcIdentityError}
          />
          <AdminUserApiKeysSection {...apiKeySectionProps(props)} />
        </div>
      </aside>
    </div>
  );
}
