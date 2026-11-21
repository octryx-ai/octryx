import { useEffect, useState } from "react";
import { KnowledgeFormField } from "./KnowledgeFormField";
import { connectionRepositoriesApi } from "./connectionRepositoriesApi";
import { ConnectorRequestError } from "./connectorReasons";
import {
  CANDIDATES_DEBOUNCE_MS,
  URL_REFUSED_TEXT,
  candidatesQueryable,
  connectionHint,
  connectionLabel,
  connectionOptions,
  preselectConnection,
} from "./gitConnectionModel";
import type { GitConnectionCandidate } from "./gitConnectionModel";

export type GitCandidates = { candidates: GitConnectionCandidate[]; urlRefused: string | null };

// The server's candidates for the URL, asked again (debounced) when it changes and parses; an unlinked source starts
// with the ones its listing carries. A 400 is an address of no known host (said at the URL field); any other failure
// (a reader's 403) leaves no candidates.
export function useGitCandidates(workspaceId: string | undefined, repositoryUrl: string, wanted: boolean,
  initial: GitConnectionCandidate[] = []): GitCandidates {
  const [state, setState] = useState<GitCandidates>({ candidates: initial, urlRefused: null });
  useEffect(() => {
    if (!workspaceId || !wanted) return undefined;
    if (!candidatesQueryable(repositoryUrl)) {
      setState({ candidates: [], urlRefused: null });
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      connectionRepositoriesApi.gitCandidates(workspaceId, repositoryUrl)
        .then((answer) => { if (!cancelled) setState({ candidates: answer.candidates ?? [], urlRefused: null }); })
        .catch((error: unknown) => {
          if (cancelled) return;
          const refused = error instanceof ConnectorRequestError && error.status === 400;
          setState({ candidates: [], urlRefused: refused ? URL_REFUSED_TEXT : null });
        });
    }, CANDIDATES_DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [workspaceId, repositoryUrl, wanted]);
  return state;
}

// "Read through connection": the candidates plus "None (public repository)". Until the person picks, the one
// candidate is preselected; an edited source keeps its stored connection. A linked source offers no None: the server
// keeps a link a save does not name, so None would not unlink it.
export function KnowledgeGitConnectionSelect({ candidates, connectionId, onChange, editing, linked }: {
  candidates: GitConnectionCandidate[];
  connectionId: string;
  onChange: (connectionId: string) => void;
  editing: boolean;
  linked: boolean;
}) {
  const [picked, setPicked] = useState(editing);
  const preselected = preselectConnection(candidates);
  useEffect(() => {
    if (!picked && preselected !== connectionId) onChange(preselected);
  }, [picked, preselected, connectionId, onChange]);
  const options = connectionOptions(candidates, connectionId);
  return (
    <>
      <KnowledgeFormField label="Read through connection">
        <select className="admin-panel__input" aria-label="Read through connection" data-testid="git-connection-select"
          value={connectionId}
          onChange={(event) => { setPicked(true); onChange(event.target.value); }}>
          {linked ? null : <option value="">None (public repository)</option>}
          {options.map((option) => <option key={option.id} value={option.id}>{connectionLabel(option)}</option>)}
        </select>
      </KnowledgeFormField>
      <div className="admin-panel__hint" style={{ margin: 0 }} data-testid="git-connection-hint">
        {connectionHint(candidates, connectionId)}
      </div>
    </>
  );
}
