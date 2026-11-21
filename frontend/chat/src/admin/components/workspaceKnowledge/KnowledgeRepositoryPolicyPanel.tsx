import { useCallback, useEffect, useState } from "react";
import { knowledgeBase, request } from "./workspaceKnowledgeRequest";

type RepositoryPolicy = { workspace_id: string; may_author: boolean; allow_local_snapshots: boolean };

const repositoryPolicyApi = {
  get: (workspaceId: string) => request<RepositoryPolicy>(`${knowledgeBase(workspaceId)}/repositories/policy`),
  put: (workspaceId: string, allow: boolean) =>
    request<RepositoryPolicy>(`${knowledgeBase(workspaceId)}/repositories/policy`, {
      method: "PUT",
      body: JSON.stringify({ allow_local_snapshots: allow }),
    }),
};

// Whether members may index the checkout they start octryx-claude in (`allow_local_snapshots`, off by default):
// the tracked files at HEAD become a git_repository source of this workspace. Only an admin or owner changes it.
// Shown in Settings › Workspace › Repositories, not on Knowledge › Sources.
export function KnowledgeRepositoryPolicyPanel({ workspaceId }: { workspaceId: string }) {
  const [policy, setPolicy] = useState<RepositoryPolicy | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = useCallback(async (action: () => Promise<RepositoryPolicy>) => {
    setBusy(true);
    try {
      setPolicy(await action());
      setMessage(null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void run(() => repositoryPolicyApi.get(workspaceId));
  }, [run, workspaceId]);

  if (!policy) return <div className="admin-panel__hint">{message ?? "Loading…"}</div>;
  return (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">Local repository snapshots</div>
      <div className="admin-form-toggle-row" data-policy-key="allow_local_snapshots">
        <div className="admin-form-toggle-copy">
          <span>Allow local snapshots</span>
          <div className="admin-form-help">
            Members' local git checkouts become a repository source of this Workspace.
          </div>
        </div>
        <button
          type="button"
          className={`toggle-switch ${policy.allow_local_snapshots ? "toggle-switch--on" : ""}`}
          role="switch"
          aria-checked={policy.allow_local_snapshots}
          aria-label="Allow local snapshots"
          disabled={busy || !policy.may_author}
          onClick={() => void run(() => repositoryPolicyApi.put(workspaceId, !policy.allow_local_snapshots))}
        />
      </div>
      {!policy.may_author ? (
        <div className="admin-panel__hint" style={{ margin: 0 }}>Only a workspace admin or owner can change this.</div>
      ) : null}
      {message ? <div className="admin-panel__hint" role="status">{message}</div> : null}
    </div>
  );
}
