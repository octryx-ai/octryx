import type { FormEvent } from "react";

import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";
import { roleDescription } from "./identityPresentation";

import "./identityPages.css";

// Mirrors CORE_ROLE_NAMES in backend admin_role_service.py.
const CORE_ROLE_NAMES = new Set(["admin", "operator", "technical", "viewer"]);

type AdminUserCreateFormProps = {
  roleNames: string[];
  newUsername: string;
  newEmail: string;
  newPassword: string;
  newDisplayName: string;
  newAccountType: string;
  newRole: string;
  formError: string | null;
  formLoading: boolean;
  setNewUsername: (value: string) => void;
  setNewEmail: (value: string) => void;
  setNewPassword: (value: string) => void;
  setNewDisplayName: (value: string) => void;
  setNewAccountType: (value: string) => void;
  setNewRoles: (value: string) => void;
  onCreateUser: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onClose: () => void;
};

const FORM_ID = "admin-user-create-form";

type AccountFieldsProps = Omit<AdminUserCreateFormProps, "formError" | "formLoading" | "onCreateUser" | "onClose">;

// Username, email, password and display name.
function UserIdentityFields({ newUsername, newEmail, newPassword, newDisplayName, setNewUsername, setNewEmail, setNewPassword, setNewDisplayName }: AccountFieldsProps) {
  return (
    <>
    <label className="admin-panel__field">
      <span>
        Username <span className="admin-users__form-required" aria-hidden="true">*</span>
      </span>
      <input
        value={newUsername}
        onChange={(event) => setNewUsername(event.target.value)}
        autoComplete="off"
        required
      />
    </label>
    <label className="admin-panel__field">
      <span>
        Email <span className="admin-users__form-required" aria-hidden="true">*</span>
      </span>
      <input
        type="email"
        value={newEmail}
        onChange={(event) => setNewEmail(event.target.value)}
        autoComplete="off"
        required
      />
    </label>
    <label className="admin-panel__field">
      <span>
        Password <span className="admin-users__form-required" aria-hidden="true">*</span>
      </span>
      <input
        type="password"
        value={newPassword}
        onChange={(event) => setNewPassword(event.target.value)}
        autoComplete="new-password"
        required
        minLength={8}
      />
      <span className="admin-users__form-help">At least 8 characters.</span>
    </label>
    <label className="admin-panel__field">
      <span>Display name</span>
      <input
        value={newDisplayName}
        onChange={(event) => setNewDisplayName(event.target.value)}
      />
    </label>
    </>
  );
}

// The account type and primary role; choosing the account type moves the role to "technical" or back to "viewer"
// when those exist.
function UserRoleFields({ roleNames, newAccountType, newRole, setNewAccountType, setNewRoles }: AccountFieldsProps) {
  const hasTechnicalRole = roleNames.includes("technical");
  const hasViewerRole = roleNames.includes("viewer");

  const roleEffect = newRole
    ? roleDescription({ name: newRole, description: "", is_core: CORE_ROLE_NAMES.has(newRole) }) ||
      "Custom role: its permissions are listed under People & sign-in → Platform access."
    : "Choose what the account may do on the platform.";

  return (
    <>
    <label className="admin-panel__field">
      <span>Account type</span>
      <select
        value={newAccountType}
        onChange={(event) => {
          const accountType = event.target.value;
          setNewAccountType(accountType);
          if (accountType === "technical" && hasTechnicalRole) {
            setNewRoles("technical");
          }
          if (
            accountType === "human" &&
            newRole === "technical" &&
            hasViewerRole
          ) {
            setNewRoles("viewer");
          }
        }}
      >
        <option value="human">Human user</option>
        <option value="technical">Technical user / bot</option>
      </select>
    </label>
    <label className="admin-panel__field">
      <span>
        Primary role <span className="admin-users__form-required" aria-hidden="true">*</span>
      </span>
      <select
        value={newRole}
        onChange={(event) => setNewRoles(event.target.value)}
        required
      >
        <option value="">Select role</option>
        {roleNames.map((role) => (
          <option key={role} value={role}>
            {role}
          </option>
        ))}
      </select>
      <span className="admin-users__form-help">{roleEffect}</span>
    </label>
    </>
  );
}

// "New user": a side panel over the dimmed user list; Cancel and "Create user" at the
// bottom right. Who is created here and who arrives through SSO is in help/admin/users.md.
export function AdminUserCreateForm({ formError, formLoading, onCreateUser, onClose, ...fields }: AdminUserCreateFormProps) {
  return (
    <SidePanel
      title="New user"
      onClose={onClose}
      testId="user-create-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button
            type="submit"
            form={FORM_ID}
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={formLoading}
            data-testid="user-create-submit"
          >
            {formLoading ? "Creating..." : "Create user"}
          </button>
        </>
      )}
    >
    <form
      id={FORM_ID}
      className="admin-users__create"
      onSubmit={(event) => void onCreateUser(event)}
      aria-label="New user"
    >
      <FormSection title="Account">
      <UserIdentityFields {...fields} />
      <UserRoleFields {...fields} />
      </FormSection>
      {formError ? <div className="admin-panel__error" role="alert">{formError}</div> : null}
    </form>
    </SidePanel>
  );
}
