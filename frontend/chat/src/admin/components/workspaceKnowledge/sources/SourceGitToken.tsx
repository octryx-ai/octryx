import { useState } from "react";
import { connectorsApi } from "../connectorsApi";
import type { SourceConnector } from "../connectorTypes";
import { TimeText } from "../../../utils/TimeText";

// A Bitbucket Data Center repository's own Git token (Data Center answers 500 on Git over HTTPS for
// the connection's OpenID Connect token). The panel shows only whether one is configured; an author replaces it (the
// server checks it against this repository first) or removes it (Git then signs in with the connection again).
export function SourceGitToken({ connector, workspaceId, editable, onChanged }: {
  connector: SourceConnector; workspaceId: string; editable: boolean; onChanged?: (connector: SourceConnector) => void;
}) {
  const state = connector.git_token ?? { configured: false };
  const [entering, setEntering] = useState(false);
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const act = async (request: () => Promise<SourceConnector>) => {
    setSaving(true);
    setProblem(null);
    try {
      const described = await request();
      setEntering(false);
      setToken("");
      onChanged?.(described);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };
  const replace = () => {
    if (!token.trim()) {
      setProblem("Enter the Git access token.");
      return;
    }
    void act(() => connectorsApi.replaceGitToken(workspaceId, connector.connector_key, token.trim()));
  };
  const remove = () => void act(() => connectorsApi.removeGitToken(workspaceId, connector.connector_key));

  return (
    <div className="admin-panel__stack admin-panel__stack--compact" data-testid="source-git-token">
      <div className="admin-users__row-actions" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <span data-testid="source-git-token-state">
          {state.configured ? "Git token configured" : "No Git token: Git signs in with the connection"}
          {state.configured && state.set_at ? <span className="admin-panel__muted"> · set <TimeText value={state.set_at} /></span> : null}
        </span>
        {editable && !entering ? (
          <>
            <button type="button" className="admin-panel__action-btn" disabled={saving} data-testid="source-git-token-replace"
              onClick={() => { setEntering(true); setProblem(null); }}>{state.configured ? "Replace" : "Set"}</button>
            {state.configured ? (
              <button type="button" className="admin-panel__action-btn" disabled={saving} data-testid="source-git-token-remove"
                onClick={remove}>{saving ? "Removing…" : "Remove"}</button>
            ) : null}
          </>
        ) : null}
      </div>
      {editable && entering ? (
        <div className="admin-users__row-actions" style={{ alignItems: "center" }}>
          <input className="admin-panel__input" type="password" autoComplete="new-password" aria-label="Git access token"
            placeholder="Bitbucket HTTP access token (Repository write)" value={token} disabled={saving}
            data-testid="source-git-token-input" onChange={(event) => setToken(event.target.value)} />
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={saving}
            data-testid="source-git-token-save" onClick={replace}>{saving ? "Checking…" : "Save"}</button>
          <button type="button" className="admin-panel__action-btn" disabled={saving}
            onClick={() => { setEntering(false); setToken(""); setProblem(null); }}>Cancel</button>
        </div>
      ) : null}
      {problem ? <span className="admin-panel__hint" role="alert" style={{ margin: 0 }}>{problem}</span> : null}
    </div>
  );
}
