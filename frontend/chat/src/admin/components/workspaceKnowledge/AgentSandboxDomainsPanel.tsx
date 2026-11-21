import { useCallback, useEffect, useState } from "react";
import { request } from "./workspaceKnowledgeRequest";

type SandboxDomains = { workspace_id: string; may_author: boolean; allowed_domains: string[] };

const sandboxUrl = (workspaceId: string) =>
  `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-gateway/sandbox`;

// The domains Bash may reach inside Claude Code's sandbox in octryx-claude sessions of this workspace (builds,
// package registries). Empty: Claude Code asks per domain. The platform host is never allowed.
export function AgentSandboxDomainsPanel({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<SandboxDomains | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = useCallback(async (action: () => Promise<SandboxDomains>) => {
    setBusy(true);
    try {
      const next = await action();
      setState(next);
      setDraft(next.allowed_domains.join("\n"));
      setMessage(null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void run(() => request<SandboxDomains>(sandboxUrl(workspaceId)));
  }, [run, workspaceId]);

  if (!state) return <div className="admin-panel__hint">{message ?? "Loading…"}</div>;
  const save = () => {
    const domains = draft.split(/\s+/).map((entry) => entry.trim()).filter(Boolean);
    void run(() =>
      request<SandboxDomains>(sandboxUrl(workspaceId), {
        method: "PUT",
        body: JSON.stringify({ allowed_domains: domains }),
      }),
    );
  };

  return (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">Claude Code sandbox network</div>
      <div className="admin-form-help">
        Domains Bash may reach in octryx-claude sessions (one per line, optional leading *.), for example
        pypi.org or *.npmjs.org. Empty: Claude Code asks per domain.
      </div>
      <textarea
        className="admin-panel__input"
        rows={4}
        value={draft}
        disabled={busy || !state.may_author}
        aria-label="Allowed sandbox domains"
        onChange={(event) => setDraft(event.target.value)}
      />
      <button type="button" className="admin-panel__action-btn" disabled={busy || !state.may_author} onClick={save}>
        Save domains
      </button>
      {!state.may_author ? (
        <div className="admin-panel__hint" style={{ margin: 0 }}>Only a workspace admin or owner can change this.</div>
      ) : null}
      {message ? <div className="admin-panel__hint" role="status">{message}</div> : null}
    </div>
  );
}
