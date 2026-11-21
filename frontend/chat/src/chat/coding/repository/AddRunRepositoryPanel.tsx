import { useEffect, useId, useState, type FormEvent } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import {
  DEFAULT_RIGHTS, RIGHTS, addRunRepository, connectionLabel, detectRunRepository, detectionText, loadRunConnections,
  repositoryName, type Detection, type Rights, type RunConnection,
} from "./runRepositoryModel";

// Work › Repositories › "Add a repository for runs" (alpha): the connection, owner/name, base branch, an
// optional check of what the repository holds (its apps), the test command and the rights a run has. Before, a run
// repository came only from a Knowledge source or an admin form that needed a server path.
export function AddRunRepositoryPanel({ workspaceId, onClose, onAdded, knowledgeHref }: {
  workspaceId: string; onClose: () => void; onAdded: () => void; knowledgeHref: string;
}) {
  const id = useId();
  const [connections, setConnections] = useState<RunConnection[] | null>(null);
  const [connectionId, setConnectionId] = useState("");
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("main");
  const [test, setTest] = useState("");
  const [rights, setRights] = useState<Rights>(DEFAULT_RIGHTS);
  const [found, setFound] = useState<Detection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    loadRunConnections(workspaceId)
      .then((rows) => { if (current) { setConnections(rows); setConnectionId(rows[0]?.id ?? ""); } })
      .catch((failure: Error) => { if (current) { setConnections([]); setError(failure.message); } });
    return () => { current = false; };
  }, [workspaceId]);

  const parsed = repositoryName(repository);
  const draft = "name" in parsed ? { connection_id: connectionId, repository: parsed.name, base_branch: branch.trim() || "main" } : null;
  const changed = () => { setFound(null); setError(null); };

  const check = async () => {
    if (!draft) return;
    setBusy(true); setError(null);
    try { setFound(await detectRunRepository(workspaceId, draft)); } catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    setBusy(true); setError(null);
    try {
      await addRunRepository(workspaceId, { ...draft, test_command: test.trim(), rights, apps: found?.apps ?? [] });
      onAdded();
    } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  };

  const noConnection = connections !== null && !connections.length;
  return <SidePanel title="Add a repository for runs" subtitle="Work · Repositories" onClose={onClose}
    testId="run-repository-panel"
    footer={<>
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onClose}>Cancel</button>
      <button type="submit" form={`${id}-form`} className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={busy || !draft || !connectionId || found?.exists === false} data-testid="run-repository-add">
        {busy ? "Adding…" : "Add repository"}</button>
    </>}>
    {noConnection ? <p className="admin-panel__note" role="status" data-testid="run-repository-no-connection">
      This Workspace has no GitHub, GitLab or Bitbucket connection yet. An admin adds one in Admin › Connections and
      makes it available here.</p> : null}
    <form id={`${id}-form`} className="knowledge-upload-drawer__form" onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy || noConnection || connections === null}>
        <legend className="knowledge-upload-drawer__legend">Repository</legend>
        <label className="admin-panel__field">Connection
          <select className="admin-panel__input" value={connectionId} data-testid="run-repository-connection"
            onChange={(event) => { setConnectionId(event.target.value); changed(); }}>
            {(connections ?? []).map((row) => <option key={row.id} value={row.id}>{connectionLabel(row)}</option>)}
          </select></label>
        <label className="admin-panel__field">Repository (owner/name)
          <input className="admin-panel__input" value={repository} maxLength={300} placeholder="demo-org/demo-shop"
            data-testid="run-repository-name" onChange={(event) => { setRepository(event.target.value); changed(); }} /></label>
        {repository && "problem" in parsed ? <p className="admin-panel__note" role="alert">{parsed.problem}</p> : null}
        <label className="admin-panel__field">Base branch
          <input className="admin-panel__input" value={branch} maxLength={200} data-testid="run-repository-branch"
            onChange={(event) => { setBranch(event.target.value); changed(); }} /></label>
        <p className="work-area__actions">
          <button type="button" className="admin-panel__action-btn" disabled={busy || !draft || !connectionId}
            data-testid="run-repository-check" onClick={() => void check()}>Check repository</button>
        </p>
        {found ? <p className="admin-panel__note" role="status" data-testid="run-repository-found">{detectionText(found)}</p> : null}
        <label className="admin-panel__field">Test command (optional)
          <input className="admin-panel__input" value={test} maxLength={500} placeholder="npm test"
            data-testid="run-repository-test" onChange={(event) => setTest(event.target.value)} /></label>
        <p className="admin-panel__note">An app's .octryx/environment.json, when there is one, names its own commands.</p>
      </fieldset>
      <fieldset disabled={busy || noConnection}>
        <legend className="knowledge-upload-drawer__legend">What a run may do here</legend>
        {RIGHTS.map((right) => <label key={right.key} className="admin-panel__checkbox" title={right.hint}>
          <input type="checkbox" checked={rights[right.key]} data-testid={`run-repository-right-${right.key}`}
            onChange={(event) => setRights({ ...rights, [right.key]: event.target.checked })} /> {right.label}
        </label>)}
      </fieldset>
      {error ? <p role="alert" data-testid="run-repository-error">{error}</p> : null}
      <p className="admin-panel__note">For Knowledge search only, <a href={knowledgeHref}>add a Knowledge source</a> instead.</p>
    </form>
  </SidePanel>;
}
