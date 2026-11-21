// Form state and save handlers of the admin user edit panel.
import { type FormEvent, useState } from "react";

import type { AdminUserEditPanelProps } from "./AdminUserEditPanel";
import type { AdminUserRow } from "./identityTypes";

export function useAdminUserEditState(user: AdminUserRow | null) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [accountType, setAccountType] = useState(user?.account_type ?? "human");
  // All assigned roles are kept, including ones mapped from SSO; saving sends the full list.
  const [selectedRoles, setSelectedRoles] = useState<string[]>(
    user?.roles ?? [],
  );
  const [selectedGroupIds, setSelectedGroupIds] = useState(
    user?.groups.map((g) => g.id) ?? [],
  );
  const [newPassword, setNewPassword] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);
  const [roleSaving, setRoleSaving] = useState(false);
  const [groupsSaving, setGroupsSaving] = useState(false);
  const [pwSaving, setPwSaving] = useState(false);
  const [profileOk, setProfileOk] = useState(false);
  const [pwOk, setPwOk] = useState(false);
  return {
    username, setUsername, email, setEmail, displayName, setDisplayName, accountType, setAccountType,
    selectedRoles, setSelectedRoles, selectedGroupIds, setSelectedGroupIds, newPassword, setNewPassword,
    profileSaving, setProfileSaving, roleSaving, setRoleSaving, groupsSaving, setGroupsSaving,
    pwSaving, setPwSaving, profileOk, setProfileOk, pwOk, setPwOk,
  };
}

export type AdminUserEditState = ReturnType<typeof useAdminUserEditState>;
type SaveCallbacks = Pick<AdminUserEditPanelProps, "onSaveProfile" | "onSaveRole" | "onSaveGroups" | "onResetPassword">;

function createProfileAndPasswordHandlers(user: AdminUserRow, s: AdminUserEditState, props: SaveCallbacks) {
  const handleSaveProfile = async (e: FormEvent) => {
    e.preventDefault();
    s.setProfileSaving(true);
    s.setProfileOk(false);
    try {
      await props.onSaveProfile(user.id, {
        username: s.username,
        email: s.email,
        display_name: s.displayName,
        account_type: s.accountType,
      });
      s.setProfileOk(true);
      setTimeout(() => s.setProfileOk(false), 2500);
    } finally {
      s.setProfileSaving(false);
    }
  };

  const handleResetPassword = async (e: FormEvent) => {
    e.preventDefault();
    if (!s.newPassword) return;
    s.setPwSaving(true);
    s.setPwOk(false);
    try {
      await props.onResetPassword(user.id, s.newPassword);
      s.setNewPassword("");
      s.setPwOk(true);
      setTimeout(() => s.setPwOk(false), 2500);
    } finally {
      s.setPwSaving(false);
    }
  };
  return { handleSaveProfile, handleResetPassword };
}

export function createAdminUserEditHandlers(user: AdminUserRow, s: AdminUserEditState, props: SaveCallbacks) {
  const handleSaveRole = async () => {
    s.setRoleSaving(true);
    try {
      await props.onSaveRole(user.id, s.selectedRoles);
    } finally {
      s.setRoleSaving(false);
    }
  };

  const handleSaveGroups = async () => {
    s.setGroupsSaving(true);
    try {
      await props.onSaveGroups(user, s.selectedGroupIds);
    } finally {
      s.setGroupsSaving(false);
    }
  };
  return { ...createProfileAndPasswordHandlers(user, s, props), handleSaveRole, handleSaveGroups };
}
