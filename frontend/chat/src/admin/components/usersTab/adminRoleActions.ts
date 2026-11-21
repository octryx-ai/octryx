// Role actions of the users tab: create, update description/permissions and confirmed delete.
import type { Dispatch, FormEvent, SetStateAction } from "react";

import type { ConfirmRequest } from "../confirm/useConfirmAction";
import { normalizeRoleRow } from "./rolePayload";
import type { AdminReadJsonFn, AdminRolePermission, AdminRoleRow } from "./identityTypes";

export type AdminRoleActionsDeps = {
  readJson: AdminReadJsonFn;
  ask: (request: ConfirmRequest) => void;
  roleName: string;
  roleDescription: string;
  setRoles: Dispatch<SetStateAction<AdminRoleRow[]>>;
  setRoleName: Dispatch<SetStateAction<string>>;
  setRoleDescription: Dispatch<SetStateAction<string>>;
  setRoleLoading: Dispatch<SetStateAction<string | null>>;
  setRoleError: Dispatch<SetStateAction<string | null>>;
  setShowCreateRole: Dispatch<SetStateAction<boolean>>;
};

async function createRole(deps: AdminRoleActionsDeps) {
  const { readJson, roleName, roleDescription, setRoles, setRoleName, setRoleDescription, setRoleLoading, setRoleError, setShowCreateRole } = deps;
  setRoleLoading("create");
  try {
    const created = await readJson<AdminRoleRow>(
      "/admin/chat/api/panel/roles",
      {
        method: "POST",
        body: JSON.stringify({
          name: roleName,
          description: roleDescription,
        }),
      },
    );
    setRoles((current) =>
      [...current, normalizeRoleRow(created)].sort((a, b) =>
        a.name.localeCompare(b.name),
      ),
    );
    setRoleName("");
    setRoleDescription("");
    setRoleError(null);
    setShowCreateRole(false);
  } catch (error) {
    setRoleError(
      error instanceof Error ? error.message : "Failed to create role",
    );
  } finally {
    setRoleLoading(null);
  }
}

/** One PUT of a role (its description or its permissions), replacing the row with the answer. */
async function updateRole(
  deps: AdminRoleActionsDeps,
  role: AdminRoleRow,
  loading: string,
  change: { description: string } | { permissions: AdminRolePermission[] },
  failure: string,
) {
  const { readJson, setRoles, setRoleLoading, setRoleError } = deps;
  setRoleLoading(loading);
  try {
    const updated = await readJson<AdminRoleRow>(
      `/admin/chat/api/panel/roles/${role.id}`,
      {
        method: "PUT",
        body: JSON.stringify(change),
      },
    );
    setRoles((current) =>
      current.map((item) =>
        item.id === role.id ? normalizeRoleRow(updated) : item,
      ),
    );
    setRoleError(null);
  } catch (error) {
    setRoleError(error instanceof Error ? error.message : failure);
  } finally {
    setRoleLoading(null);
  }
}

export function createAdminRoleActions(deps: AdminRoleActionsDeps) {
  const { readJson, ask, setRoles, setRoleError } = deps;
  const handleCreateRole = async (event: FormEvent) => {
    event.preventDefault();
    await createRole(deps);
  };

  const handleUpdateRoleDescription = (
    role: AdminRoleRow,
    description: string,
  ) => updateRole(deps, role, `update:${role.id}`, { description }, "Failed to update role");

  const handleUpdateRolePermissions = (
    role: AdminRoleRow,
    permissions: AdminRolePermission[],
  ) => updateRole(deps, role, `permissions:${role.id}`, { permissions }, "Failed to update role permissions");

  // Destructive actions confirm in the page, name the object, and say afterwards what happened.
  const handleDeleteRole = (role: AdminRoleRow) => ask({
    title: `Delete role ${role.name}?`, confirmLabel: `Delete ${role.name}`, done: `Role ${role.name} deleted.`,
    run: async () => {
      await readJson(`/admin/chat/api/panel/roles/${role.id}`, { method: "DELETE" });
      setRoles((current) => current.filter((item) => item.id !== role.id));
      setRoleError(null);
    },
  });

  return {
    handleCreateRole,
    handleUpdateRoleDescription,
    handleUpdateRolePermissions,
    handleDeleteRole,
  };
}
