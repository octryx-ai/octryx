// Roles and password sections of the admin user edit panel.
import type { FormEvent } from "react";

import { MultiSelect } from "./UserEditMultiSelect";
import { SectionLabel } from "./userEditPanelParts";

export function AdminUserRolesSection({ roleOptions, selectedRoles, setSelectedRoles, roleSaving, onSave }: {
  roleOptions: { id: string; name: string }[];
  selectedRoles: string[];
  setSelectedRoles: (roles: string[]) => void;
  roleSaving: boolean;
  onSave: () => void;
}) {
  return (
    <section className="user-edit-panel__section">
      <SectionLabel>Roles</SectionLabel>
      <div className="user-edit-panel__row">
        <MultiSelect
          options={roleOptions}
          selectedIds={selectedRoles}
          onChange={setSelectedRoles}
          noun={{ one: "role", many: "roles" }}
        />
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onSave}
          disabled={roleSaving}
        >
          {roleSaving ? "Saving…" : "Save"}
        </button>
      </div>
    </section>
  );
}

export function AdminUserPasswordSection({ newPassword, setNewPassword, pwOk, pwSaving, onSubmit }: {
  newPassword: string;
  setNewPassword: (password: string) => void;
  pwOk: boolean;
  pwSaving: boolean;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <section className="user-edit-panel__section">
      <SectionLabel>Reset password</SectionLabel>
      <form className="user-edit-panel__row" onSubmit={onSubmit}>
        <input
          type="password"
          className="user-edit-panel__pw-input"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          minLength={8}
          required
          placeholder="New password (min 8 chars)"
        />
        {pwOk && <span className="user-edit-panel__ok">Done</span>}
        <button
          type="submit"
          className="admin-panel__action-btn"
          disabled={pwSaving}
        >
          {pwSaving ? "Resetting…" : "Reset"}
        </button>
      </form>
    </section>
  );
}
