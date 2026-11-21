// One platform row of the linked accounts panel: the account and its actions, and the editor when it is open.
import { canFindByEmail, canVerify, identifierLabel, verificationBadge } from "./linkedAccountsModel";
import type { LinkedAccount, LinkedPlatform } from "./linkedAccountsModel";
import { type LinkedAccountsState, saveAccount, unlinkAccount, verifyAccount } from "./linkedAccountsState";

type RowProps = { state: LinkedAccountsState; platform: LinkedPlatform; account: LinkedAccount | null };

function AccountIdentity({ platform, account }: Omit<RowProps, "state">) {
  return (
    <div>
      <div className="linked-accounts__platform">{platform.label}</div>
      {account ? (
        <div className="linked-accounts__identity">
          <code>{account.identifier}</code>
          {account.displayName ? <span>{account.displayName}</span> : null}
        </div>
      ) : (
        <div className="admin-panel__cell--muted">{platform.description}</div>
      )}
      {account?.verificationDetail ? (
        <div className="admin-panel__cell--muted">{account.verificationDetail}</div>
      ) : null}
    </div>
  );
}

function AccountActions({ state, platform, account }: RowProps) {
  const { busy, editing, confirmUnlink, setEditing, setConfirmUnlink } = state;
  const edit = editing?.platform === platform.platform ? editing : null;
  const badge = account ? verificationBadge(account) : null;
  return (
    <div className="linked-accounts__actions">
      {badge ? <span className={`work-badge work-badge--${badge.tone}`}>{badge.label}</span> : null}
      {account && canVerify(platform.platform) ? (
        <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
          onClick={() => verifyAccount(state, account)}>
          {busy === `verify:${platform.platform}` ? "Verifying…" : "Verify"}
        </button>
      ) : null}
      {!edit ? (
        <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
          onClick={() => setEditing({ platform: platform.platform, mode: "identifier", value: account?.identifier ?? "" })}>
          {account ? "Change" : "Link"}
        </button>
      ) : null}
      {account && confirmUnlink !== platform.platform ? (
        <button type="button" className="admin-panel__danger-btn" disabled={busy !== null}
          onClick={() => setConfirmUnlink(platform.platform)}>
          Unlink
        </button>
      ) : null}
      {account && confirmUnlink === platform.platform ? (
        <>
          <button type="button" className="admin-panel__action-btn" onClick={() => setConfirmUnlink(null)}>
            Cancel
          </button>
          <button type="button" className="admin-panel__danger-btn" disabled={busy !== null}
            onClick={() => unlinkAccount(state, account)}>
            Confirm unlink
          </button>
        </>
      ) : null}
    </div>
  );
}

function ModeButton({ state, mode, label }: { state: LinkedAccountsState; mode: "identifier" | "email"; label: string }) {
  const edit = state.editing!;
  return (
    <button type="button"
      className={`admin-panel__action-btn ${edit.mode === mode ? "admin-panel__action-btn--primary" : ""}`}
      aria-pressed={edit.mode === mode}
      onClick={() => state.setEditing({ ...edit, mode, value: "" })}>
      {label}
    </button>
  );
}

function AccountEditor({ state, platform }: Omit<RowProps, "account">) {
  const { busy, setEditing } = state;
  const edit = state.editing!;
  return (
    <div className="linked-accounts__edit">
      {canFindByEmail(platform.platform) ? (
        <div className="linked-accounts__modes" role="group" aria-label="How to link">
          <ModeButton state={state} mode="identifier" label="By account id" />
          <ModeButton state={state} mode="email" label="Find by email" />
        </div>
      ) : null}
      <label className="admin-panel__field">
        <span>{edit.mode === "email" ? "Email of the Atlassian account" : identifierLabel(platform.identifierKind)}</span>
        <input className="admin-panel__input" type={edit.mode === "email" ? "email" : "text"}
          value={edit.value} autoComplete="off" spellCheck={false}
          onChange={(event) => setEditing({ ...edit, value: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === "Enter") saveAccount(state, platform);
          }} />
      </label>
      <p className="admin-panel__hint">
        {edit.mode === "email"
          ? "The selected Workspace's Jira Cloud connection finds the one account that shows exactly this email. The email is not stored."
          : platform.description}
      </p>
      <div className="linked-accounts__buttons">
        <button type="button" className="admin-panel__action-btn" onClick={() => setEditing(null)}>
          Cancel
        </button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy !== null || !edit.value.trim()} onClick={() => saveAccount(state, platform)}>
          {edit.mode === "email" ? "Find and link" : "Save"}
        </button>
      </div>
    </div>
  );
}

export function LinkedAccountRow({ state, platform, account }: RowProps) {
  const edit = state.editing?.platform === platform.platform ? state.editing : null;
  return (
    <li className="linked-accounts__row" data-testid={`linked-account-${platform.platform}`}>
      <div className="linked-accounts__head">
        <AccountIdentity platform={platform} account={account} />
        <AccountActions state={state} platform={platform} account={account} />
      </div>
      {account && !canVerify(platform.platform) ? (
        <div className="admin-panel__cell--muted">
          Used as entered: the {platform.label} connection offers no account lookup.
        </div>
      ) : null}
      {edit ? <AccountEditor state={state} platform={platform} /> : null}
    </li>
  );
}
