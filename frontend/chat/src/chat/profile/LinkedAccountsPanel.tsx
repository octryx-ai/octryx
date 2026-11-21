import { LinkedAccountRow } from "./LinkedAccountRow";
import { platformRows } from "./linkedAccountsModel";
import { useLinkedAccountsState } from "./linkedAccountsState";
import "./linkedAccounts.css";

// Linked accounts of one user (`userId` "me" in Profile, a user id in Settings → User accounts). Reviewer, author
// and assignee resolution read these accounts only; a Workspace's connection verifies them.
export function LinkedAccountsPanel({ userId, ownAccounts }: { userId: string; ownAccounts: boolean }) {
  const state = useLinkedAccountsState(userId);
  const { data, problem, notice, workspaceId, setWorkspaceId } = state;
  const whose = ownAccounts ? "your" : "this user's";

  return (
    <section className="admin-panel__card linked-accounts" aria-label="Linked accounts">
      <div className="admin-panel__section-header"><span>Linked accounts</span></div>
      <p className="admin-panel__hint">
        Pull requests ask {whose} linked account to review, and Work items assigned to it count as {whose}. A Workspace's
        connection verifies an account.
      </p>
      {problem ? <p className="work-area__error" role="alert">{problem}</p> : null}
      {notice ? <p className="linked-accounts__notice" role="status">{notice}</p> : null}
      {data === null && !problem ? <p className="admin-panel__hint" role="status">Loading linked accounts…</p> : null}
      {data ? (
        <>
          <label className="admin-panel__field linked-accounts__workspace">
            <span>Workspace that verifies accounts</span>
            <select value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}
              disabled={data.workspaces.length === 0}>
              {data.workspaces.length === 0 ? <option value="">No Workspace available</option> : null}
              {data.workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
              ))}
            </select>
          </label>
          <ul className="linked-accounts__list">
            {platformRows(data).map(({ platform, account }) => (
              <LinkedAccountRow key={platform.platform} state={state} platform={platform} account={account} />
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
