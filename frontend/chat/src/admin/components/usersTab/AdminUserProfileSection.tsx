// User edit panel: profile form (username, email, display name, account type) with its save button.
import type { FormEvent } from "react";
import { SectionLabel } from "./userEditPanelParts";

type AdminUserProfileSectionProps = {
  username: string;
  setUsername: (value: string) => void;
  email: string;
  setEmail: (value: string) => void;
  displayName: string;
  setDisplayName: (value: string) => void;
  accountType: string;
  setAccountType: (value: string) => void;
  profileOk: boolean;
  profileSaving: boolean;
  handleSaveProfile: (e: FormEvent) => Promise<void>;
};

export function AdminUserProfileSection({
  username, setUsername, email, setEmail, displayName, setDisplayName,
  accountType, setAccountType, profileOk, profileSaving, handleSaveProfile,
}: AdminUserProfileSectionProps) {
  return (
    <section className="user-edit-panel__section">
      <SectionLabel>Profile</SectionLabel>
      <form
        className="user-edit-panel__form"
        onSubmit={(e) => void handleSaveProfile(e)}
      >
        <label className="user-edit-panel__field">
          <span>Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>
        <label className="user-edit-panel__field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="user-edit-panel__field">
          <span>Display name</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </label>
        <label className="user-edit-panel__field">
          <span>Account type</span>
          <select
            value={accountType}
            onChange={(e) => setAccountType(e.target.value)}
          >
            <option value="human">Human user</option>
            <option value="technical">Technical / bot</option>
          </select>
        </label>
        <div className="user-edit-panel__row-end">
          {profileOk && (
            <span className="user-edit-panel__ok">Saved</span>
          )}
          <button
            type="submit"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={profileSaving}
          >
            {profileSaving ? "Saving…" : "Save profile"}
          </button>
        </div>
      </form>
    </section>
  );
}
