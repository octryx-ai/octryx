// User account requests of the admin panel: roles, profile update, password reset and creation.
import type { FormEvent } from "react";
import type { AdminUser } from "../types/adminPanelTypes.usersProviders";
import type { UseAdminBootstrapUserApprovalArgs } from "./adminBootstrapUserTypes";

type Args = UseAdminBootstrapUserApprovalArgs;
export type AdminUserUpdate = {
  username?: string;
  email?: string;
  display_name?: string;
  group_ids?: string[];
  is_active?: boolean;
};

export async function changeUserRoles(args: Args, userId: string, roles: string[]) {
  try {
    await args.readJson(`/admin/chat/api/panel/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ roles }),
    });
    args.setUsers((prev) =>
      prev.map((user) => (user.id === userId ? { ...user, roles } : user)),
    );
  } catch (err) {
    alert(err instanceof Error ? err.message : "Failed");
  }
}

export async function updateUser(args: Args, userId: string, payload: AdminUserUpdate) {
  try {
    const updated = await args.readJson<AdminUser>(`/admin/chat/api/panel/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    args.setUsers((prev) => prev.map((user) => (user.id === userId ? updated : user)));
    return updated;
  } catch (err) {
    alert(err instanceof Error ? err.message : "Failed");
    throw err;
  }
}

export async function resetUserPassword(args: Args, userId: string, password: string) {
  try {
    await args.readJson(`/admin/chat/api/panel/users/${userId}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    });
  } catch (err) {
    alert(err instanceof Error ? err.message : "Failed");
    throw err;
  }
}

function resetCreateUserForm(args: Args) {
  args.setShowCreateUser(false);
  args.setNewUsername("");
  args.setNewEmail("");
  args.setNewPassword("");
  args.setNewDisplayName("");
  args.setNewAccountType("human");
  args.setNewRoles("viewer");
}

export async function createUser(args: Args, event: FormEvent) {
  event.preventDefault();
  args.setFormError(null);
  args.setFormLoading(true);
  try {
    const created = await args.readJson<AdminUser>("/admin/chat/api/panel/users", {
      method: "POST",
      body: JSON.stringify({
        username: args.newUsername,
        email: args.newEmail,
        password: args.newPassword,
        display_name: args.newDisplayName || args.newUsername,
        account_type: args.newAccountType,
        roles: [
          args.newRoles.trim() ||
            (args.newAccountType === "technical" ? "technical" : "viewer"),
        ],
      }),
    });
    args.setUsers((prev) => [...prev, created]);
    resetCreateUserForm(args);
  } catch (err) {
    args.setFormError(err instanceof Error ? err.message : "Failed to create user");
  } finally {
    args.setFormLoading(false);
  }
}
