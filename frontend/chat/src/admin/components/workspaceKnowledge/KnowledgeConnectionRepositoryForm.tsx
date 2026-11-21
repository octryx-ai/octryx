import { ACCESS_MODE_LABEL } from "./connectorTypes";
import type { AccessMode } from "./connectorTypes";
import type { RepositoryConnection } from "./connectionRepositoriesApi";
import { repositoryConnectorKey, saveResultText } from "./connectionRepositoryModel";
import type { WorkspaceSaveResult } from "./connectionRepositoryModel";
import { ConnectionRepositoryPicker } from "./ConnectionRepositoryPicker";
import { KnowledgeFormField } from "./KnowledgeFormField";
import { useConnectionRepositoryForm } from "./useConnectionRepositoryForm";

const ACCESS_MODES: AccessMode[] = ["read_only", "read_write"];

type Form = ReturnType<typeof useConnectionRepositoryForm>;

// Branch, source name, access mode, optional Git token and target Workspaces of the chosen repository.
function RepositoryFields({ form, connection }: { form: Form; connection: RepositoryConnection | null }) {
  const { repository, ref, branchLoading, accessMode, gitToken, busy, workspaces, chosen } = form;
  if (!repository) return null;
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "0.5rem" }}>
        <KnowledgeFormField label="Branch">
          <input className="admin-panel__input" aria-label="Branch" value={ref} data-testid="connection-repo-branch"
            placeholder={branchLoading ? "Reading the default branch…" : "Branch, tag or 40-character commit sha"}
            onChange={(event) => { form.refTouched.current = true; form.setRef(event.target.value); }} />
        </KnowledgeFormField>
        <KnowledgeFormField label="Source name (a number is added when taken)">
          <input className="admin-panel__input" aria-label="Source name" readOnly
            value={repositoryConnectorKey(repository.project_key, repository.slug)} />
        </KnowledgeFormField>
      </div>
      <div role="radiogroup" aria-label="Access mode" style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
        <span className="admin-panel__muted">Access</span>
        {ACCESS_MODES.map((mode) => (
          <label key={mode} className="admin-panel__checkbox" style={{ gridColumn: "auto" }}>
            <input type="radio" name="connection-access-mode" value={mode} checked={accessMode === mode}
              data-testid={`connection-access-${mode}`} onChange={() => form.setAccessMode(mode)} />
            {ACCESS_MODE_LABEL[mode]}
          </label>
        ))}
      </div>
      {form.datacenter ? (
        <KnowledgeFormField label="Git access token (Bitbucket HTTP access token, Repository write)">
          <input className="admin-panel__input" type="password" autoComplete="new-password" aria-label="Git access token"
            value={gitToken} disabled={busy} data-testid="connection-repo-git-token" placeholder="Optional"
            onChange={(event) => form.setGitToken(event.target.value)} />
          <span className="admin-panel__muted" data-testid="connection-repo-git-token-help">
            Optional: Git clones and pushes with it instead of the connection; checked against this repository, stored encrypted, never shown again.
          </span>
        </KnowledgeFormField>
      ) : null}
      <div className="admin-panel__hint" style={{ margin: 0 }}>
        {accessMode === "read_write"
          ? `Agents may also push, create branches and open pull requests on this repository through ${connection?.name ?? "the connection"}.`
          : "Agents read the repository; they cannot push to it."}
      </div>
      <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: "0.25rem" }} data-testid="connection-workspaces">
        <legend className="admin-panel__muted" style={{ padding: 0 }}>Make available in</legend>
        {workspaces.map((workspace) => (
          <label key={workspace.id} className="admin-panel__checkbox" data-testid="connection-workspace" data-workspace={workspace.id}>
            <input type="checkbox" checked={chosen.includes(workspace.id)} disabled={busy}
              onChange={(event) => form.toggleWorkspace(workspace.id, event.target.checked)} />
            {workspace.name}{workspace.current ? <span className="admin-panel__muted"> (this Workspace)</span> : null}
          </label>
        ))}
      </fieldset>
    </>
  );
}

function SaveResults({ results }: { results: WorkspaceSaveResult[] }) {
  return (
    <ul className="admin-panel__stack admin-panel__stack--compact" style={{ margin: 0, paddingLeft: "1rem" }} data-testid="connection-save-results">
      {results.map((result) => (
        <li key={result.workspaceId} data-testid="connection-save-result" data-state={result.state} data-workspace={result.workspaceId}>
          <strong>{result.workspaceName}</strong>: {saveResultText(result)}
        </li>
      ))}
    </ul>
  );
}

// A Git repository added from a Bitbucket connection (instead of a public repository URL): the connection, one
// repository, its branch (prefilled with the default branch), the access mode, and the Workspaces it is added to.
// Each Workspace gets its own PUT and first run; the results are listed per Workspace.
export function KnowledgeConnectionRepositoryForm({ workspaceId, connections, onSaved, onCancel, preselectedConnectionId }: {
  workspaceId: string;
  connections: RepositoryConnection[];
  // A link that names the connection (a connection's Repositories tab) opens on it.
  preselectedConnectionId?: string;
  // After a save that reached at least one Workspace (the panel reloads its list).
  onSaved: () => void;
  onCancel: () => void;
}) {
  const form = useConnectionRepositoryForm(workspaceId, connections, onSaved, preselectedConnectionId);
  const { connectionId, repository, busy, results, chosen, problem } = form;
  const connection = connections.find((item) => item.id === connectionId) ?? null;
  return (
    <div className="admin-panel__stack admin-panel__stack--compact" data-testid="connection-repo-form">
      <KnowledgeFormField label="Connection">
        <select className="admin-panel__input" aria-label="Connection" value={connectionId} disabled={busy}
          onChange={(event) => form.changeConnection(event.target.value)}>
          {connections.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.host})</option>)}
        </select>
      </KnowledgeFormField>
      {connectionId ? (
        <ConnectionRepositoryPicker key={connectionId} workspaceId={workspaceId} connectionId={connectionId} selected={repository} onSelect={form.choose} />
      ) : null}
      <RepositoryFields form={form} connection={connection} />
      {results ? <SaveResults results={results} /> : null}
      <div className="admin-users__row-actions" style={{ flexWrap: "wrap" }}>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !repository}
          data-testid="connection-repo-save" onClick={() => void form.save()}>
          {busy ? "Adding…" : chosen.length > 1 ? `Add to ${chosen.length} Workspaces` : "Add source"}
        </button>
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onCancel}>
          {results ? "Done" : "Cancel"}
        </button>
      </div>
      {problem ? <div className="admin-panel__hint" role="alert" style={{ margin: 0 }}>{problem}</div> : null}
    </div>
  );
}
