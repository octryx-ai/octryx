// The repository picker of a connection: a debounced search and pages of repositories with Previous and Next.
import { useEffect, useState } from "react";
import { ACCESS_MODE_LABEL } from "./connectorTypes";
import { REPOSITORY_PAGE_SIZE, connectionRepositoriesApi } from "./connectionRepositoriesApi";
import type { ConnectionRepository, RepositoryPage } from "./connectionRepositoriesApi";
import { FIRST_PAGE, nextPage, previousPage, refusalReason } from "./connectionRepositoryModel";
import type { PagerState } from "./connectionRepositoryModel";
import { KnowledgeFormField } from "./KnowledgeFormField";
import { KnowledgeReasonNotice } from "./KnowledgeReasonNotice";
import { reasonNotice } from "./runReasonNotice";
import { StatusLabel } from "../../../layout/StatusLabel";

const SEARCH_DELAY_MS = 300;
const ROW = { display: "flex", alignItems: "baseline", gap: "0.5rem", flexWrap: "wrap" } as const;
const LIST = {
  display: "grid", gap: "0.15rem", maxHeight: "18rem", overflowY: "auto", padding: "0.35rem 0.5rem",
  border: "1px solid var(--border-soft)", borderRadius: "var(--ds-radius-md)",
} as const;

/** A refusal as the run reports show it (a policy notice with its code), or the plain message. */
function Refusal({ error }: { error: unknown }) {
  const notice = reasonNotice(refusalReason(error));
  if (notice) return <KnowledgeReasonNotice notice={notice} />;
  return (
    <div className="admin-panel__hint" role="alert" style={{ margin: 0 }} data-testid="connection-repo-error">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

// The search (applied after a pause in typing, back to the first page), the pager and the page it loads.
function useRepositoryPages(workspaceId: string, connectionId: string) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [pager, setPager] = useState<PagerState>(FIRST_PAGE);
  const [page, setPage] = useState<RepositoryPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (search.trim() === query) return undefined;
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPager(FIRST_PAGE);
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search, query]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    connectionRepositoriesApi.repositories(workspaceId, connectionId, { q: query, start: pager.start, limit: REPOSITORY_PAGE_SIZE })
      .then((answer) => { if (!cancelled) setPage(answer); })
      .catch((err: unknown) => { if (!cancelled) { setPage(null); setError(err); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [workspaceId, connectionId, query, pager.start]);

  return { search, setSearch, query, pager, setPager, page, loading, error };
}

// The repositories of one connection: a search (debounced) and pages of 25 with Previous/Next; one is chosen.
export function ConnectionRepositoryPicker({ workspaceId, connectionId, selected, onSelect }: {
  workspaceId: string; connectionId: string; selected: ConnectionRepository | null;
  onSelect: (repository: ConnectionRepository) => void;
}) {
  const { search, setSearch, query, pager, setPager, page, loading, error } = useRepositoryPages(workspaceId, connectionId);

  const repositories = page?.repositories ?? [];
  const first = pager.start + 1;
  return (
    <div className="admin-panel__stack admin-panel__stack--compact" data-testid="connection-repo-picker">
      <KnowledgeFormField label="Repository">
        <input className="admin-panel__input" type="search" aria-label="Search repositories" value={search}
          placeholder="Search by project, slug or name" data-testid="connection-repo-search"
          onChange={(event) => setSearch(event.target.value)} />
      </KnowledgeFormField>
      {error ? <Refusal error={error} /> : null}
      {!error ? (
        <div style={LIST} role="radiogroup" aria-label="Repositories" aria-busy={loading}>
          {loading && !page ? <span className="admin-panel__muted">Loading repositories…</span> : null}
          {page && !repositories.length ? (
            <span className="admin-panel__muted" data-testid="connection-repo-empty">
              {query ? `No repository matches “${query}”.` : "This connection lists no repositories."}
            </span>
          ) : null}
          {repositories.map((repository) => {
            const id = `${repository.project_key}/${repository.slug}`;
            const mode = repository.registered?.access_mode ?? null;
            return (
              <label key={id} className="admin-panel__checkbox" data-testid="connection-repo-row" data-repository={id}>
                <input type="radio" name="connection-repository" checked={selected?.repository_url === repository.repository_url}
                  onChange={() => onSelect(repository)} />
                <span style={ROW}>
                  <code>{id}</code>
                  {repository.name && repository.name !== repository.slug ? <span>{repository.name}</span> : null}
                  {repository.registered ? (
                    <StatusLabel label={mode ? ACCESS_MODE_LABEL[mode] : "Added"} tone="neutral"
                      title={`Already a source of this Workspace (${repository.registered.connector_key})`} testId="connection-repo-registered" />
                  ) : null}
                </span>
              </label>
            );
          })}
        </div>
      ) : null}
      <div className="admin-users__row-actions" style={{ alignItems: "center" }}>
        <button type="button" className="admin-panel__action-btn" disabled={loading || !pager.previous.length}
          data-testid="connection-repo-previous" onClick={() => setPager(previousPage(pager))}>Previous</button>
        <button type="button" className="admin-panel__action-btn" disabled={loading || page?.next_start == null || page.is_last_page}
          data-testid="connection-repo-next" onClick={() => setPager(nextPage(pager, page?.next_start ?? null))}>Next</button>
        {repositories.length ? (
          <span className="admin-panel__muted" data-testid="connection-repo-range">
            {first}–{pager.start + repositories.length}{loading ? " · loading…" : ""}
          </span>
        ) : null}
      </div>
    </div>
  );
}
