// User account actions of the users tab: open the edit panel, save profile/roles/groups/password, (de)activate.
import type { Dispatch, SetStateAction } from "react";

import type { ConfirmRequest } from "../confirm/useConfirmAction";
import type { AdminReadJsonFn, AdminUserOidcIdentityRow, AdminUserRow, AdminUsersTabCtx } from "./identityTypes";
import { userDisplayName } from "./userDisplayName";

export type AdminUserActionsDeps = Pick<
  AdminUsersTabCtx,
  "onRoleChange" | "onDeactivateUser" | "onUpdateUser" | "onResetUserPassword"
> & {
  readJson: AdminReadJsonFn;
  ask: (request: ConfirmRequest) => void;
  loadUserApiKeys: (user: AdminUserRow) => unknown;
  loadGroups: () => Promise<void>;
  setEditingUser: Dispatch<SetStateAction<AdminUserRow | null>>;
  setUserActionLoading: Dispatch<SetStateAction<string | null>>;
  setUserActionError: Dispatch<SetStateAction<string | null>>;
  setOidcIdentities: Dispatch<SetStateAction<AdminUserOidcIdentityRow[]>>;
  setOidcIdentityLoading: Dispatch<SetStateAction<boolean>>;
  setOidcIdentityError: Dispatch<SetStateAction<string | null>>;
};

export function createAdminUserActions(deps: AdminUserActionsDeps) {
  const {
    loadUserApiKeys, onRoleChange, onUpdateUser, onResetUserPassword, setEditingUser, setUserActionError, setOidcIdentities, setOidcIdentityError,
  } = deps;
  const loadUserOidcIdentities = oidcIdentityLoader(deps);
  const openEditUser = (user: AdminUserRow) => {
    setEditingUser(user);
    setUserActionError(null);
    setOidcIdentities([]);
    setOidcIdentityError(null);
    void loadUserApiKeys(user);
    void loadUserOidcIdentities(user.id);
  };

  const handleSaveProfile = async (
    userId: string,
    payload: {
      username: string;
      email: string;
      display_name: string;
      account_type: string;
    },
  ) => {
    const updated = await onUpdateUser(userId, payload);
    setEditingUser(updated);
  };

  const handleSaveRole = async (userId: string, roles: string[]) => {
    await onRoleChange(userId, roles);
  };

  const handleResetPasswordDirect = async (
    userId: string,
    password: string,
  ) => {
    await onResetUserPassword(userId, password);
  };

  return {
    openEditUser,
    handleSaveProfile,
    handleSaveRole,
    handleResetPasswordDirect,
    handleToggleUserStatus: userStatusToggler(deps),
    handleGroupChange: userGroupChanger(deps),
  };
}

function oidcIdentityLoader({ readJson, setOidcIdentities, setOidcIdentityLoading, setOidcIdentityError }: AdminUserActionsDeps) {
  return async (userId: string) => {
    setOidcIdentityLoading(true);
    try {
      const data = await readJson<AdminUserOidcIdentityRow[]>(
        `/admin/chat/api/panel/users/${userId}/oidc-identities`,
      );
      setOidcIdentities(Array.isArray(data) ? data : []);
      setOidcIdentityError(null);
    } catch (error) {
      setOidcIdentityError(
        error instanceof Error
          ? error.message
          : "Failed to load OIDC identities",
      );
    } finally {
      setOidcIdentityLoading(false);
    }
  };
}

// Deactivating confirms naming the person; reactivating is not destructive and happens at once, with a notice.
function userStatusToggler({ ask, onDeactivateUser, onUpdateUser, setUserActionLoading, setUserActionError }: AdminUserActionsDeps) {
  return async (user: AdminUserRow) => {
    const name = userDisplayName(user);
    if (user.is_active) {
      ask({
        title: `Deactivate ${name}?`, confirmLabel: `Deactivate ${name}`, done: `${name} deactivated.`,
        body: <p>{name} can no longer sign in. Their history stays; you can reactivate the account later.</p>,
        run: async () => { await onDeactivateUser(user.id); setUserActionError(null); },
      });
      return;
    }
    setUserActionLoading(`status:${user.id}`);
    try {
      await onUpdateUser(user.id, { is_active: true });
      setUserActionError(null);
    } catch (error) {
      setUserActionError(error instanceof Error ? error.message : "Failed to reactivate user");
    } finally {
      setUserActionLoading(null);
    }
  };
}

function userGroupChanger({ onUpdateUser, loadGroups, setUserActionLoading, setUserActionError }: AdminUserActionsDeps) {
  return async (user: AdminUserRow, groupIds: string[]) => {
    setUserActionLoading(`groups:${user.id}`);
    try {
      await onUpdateUser(user.id, { group_ids: groupIds });
      await loadGroups();
      setUserActionError(null);
    } catch (error) {
      setUserActionError(
        error instanceof Error ? error.message : "Failed to update user groups",
      );
    } finally {
      setUserActionLoading(null);
    }
  };
}
