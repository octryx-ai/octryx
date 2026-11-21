import { useCallback, useEffect, useState } from "react";

import {
  addRepositoryFromSource,
  loadRepositorySources,
  loadWorkspaceRepositories,
  setupText,
  sourceText,
  type RepositorySource,
  type WorkspaceRepository,
} from "./workspaceRepositoriesApi";
import { RepositoryCodingSetup } from "./RepositoryCodingSetup";
import { addRepositoryFromConnectionHref } from "../../workspaceKnowledge/sourceLinks";

// Settings → Workspace → Repositories: one record per repository — where
// it comes from, its branches, owners and its Coding setup. Work and Coding reference it and never re-declare it.
export function WorkspaceRepositoriesSection({ workspaceId }: { workspaceId: string }) {
  const [repositories, setRepositories] = useState<WorkspaceRepository[] | null>(null);
  const [sources, setSources] = useState<RepositorySource[] | null>(null);
  const [open, setOpen] = useState<WorkspaceRepository | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    loadWorkspaceRepositories(workspaceId).then(setRepositories)
      .catch((failure) => setError(failure instanceof Error ? failure.message : "Could not load the repositories."));
  }, [workspaceId]);
  useEffect(() => { reload(); }, [reload]);

  async function showSources() {
    setError(null);
    try {
      const listed = await loadRepositorySources(workspaceId);
      const bound = new Set((repositories ?? []).map((repository) => repository.source.name));
      setSources(listed.filter((source) => !bound.has(source.name)));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load the Knowledge git sources.");
    }
  }

  async function add(source: RepositorySource) {
    try {
      await addRepositoryFromSource(workspaceId, source.id);
      setSources(null);
      reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not add the repository.");
    }
  }

  return (
    <section className="admin-modal__stack" data-testid="workspace-repositories">
      <p className="admin-panel__hint">
        One record per repository: where it comes from, its branches, owners, and its Coding setup. Work and Coding
        reference it and never re-declare it.
      </p>
      {repositories === null ? <div className="admin-panel__empty-state">Loading repositories…</div> : repositories.length ? (
        <RepositoryTable repositories={repositories} onOpen={setOpen} />
      ) : <div className="admin-panel__empty-state">No repository yet. Add one from a Knowledge git source.</div>}
      <div className="admin-inline-actions">
        <button type="button" className="admin-panel__action-btn" onClick={() => void showSources()}>+ Set up from a Knowledge source</button>
        <a className="admin-panel__action-btn" href={addRepositoryFromConnectionHref(workspaceId)}
          data-testid="repository-add-from-connection">+ Add from a connection (Bitbucket, GitHub, ...)</a>
      </div>
      {sources ? (
        <SourcesCard sources={sources} onClose={() => setSources(null)} onAdd={(source) => void add(source)} />
      ) : null}
      {error ? <div className="admin-panel__error" role="alert">{error}</div> : null}
      {open ? <RepositoryCodingSetup workspaceId={workspaceId} repository={open} onClose={() => setOpen(null)} onSaved={reload} /> : null}
    </section>
  );
}

// One row per repository record; a row (click or Enter) opens its Coding setup.
function RepositoryTable({ repositories, onOpen }: {
  repositories: WorkspaceRepository[]; onOpen: (repository: WorkspaceRepository) => void;
}) {
  return (
    <table className="admin-panel__table work-cards">
      <thead><tr><th>Repository</th><th>Source</th><th>Default branch</th><th>Owners</th><th>Coding setup</th></tr></thead>
      <tbody>
        {repositories.map((repository) => {
          const setup = setupText(repository.coding_setup);
          return (
            <tr key={repository.id} tabIndex={0} onClick={() => onOpen(repository)}
              onKeyDown={(event) => { if (event.key === "Enter") onOpen(repository); }} data-testid="repository-row">
              <td data-label="Repository"><b>{repository.name}</b></td>
              <td data-label="Source">{sourceText(repository.source)}</td>
              <td data-label="Default branch" className="work-mono">{repository.default_branch || "–"}</td>
              <td data-label="Owners">{repository.owners.join(", ") || "–"}</td>
              <td data-label="Coding setup">
                {setup.missing ? <span className="work-badge work-badge--attention">{setup.text}</span> : setup.text}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// The Knowledge git sources without a repository record yet, each with Add.
function SourcesCard({ sources, onClose, onAdd }: {
  sources: RepositorySource[]; onClose: () => void; onAdd: (source: RepositorySource) => void;
}) {
  return (
    <div className="admin-panel__card" data-testid="repository-sources">
      <div className="admin-panel__section-header"><span>Knowledge git sources</span>
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button></div>
      {sources.length ? sources.map((source) => (
        <div key={source.id} className="named-connections__row">
          <span>{source.name}</span>
          <button type="button" className="admin-panel__action-btn" onClick={() => onAdd(source)}>Add</button>
        </div>
      )) : <p className="admin-panel__hint">Every Knowledge git source of this Workspace already has a repository. Add a git source under Knowledge first.</p>}
    </div>
  );
}
