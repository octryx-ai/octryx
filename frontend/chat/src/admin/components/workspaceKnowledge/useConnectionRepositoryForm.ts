import { useEffect, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import type { AccessMode } from "./connectorTypes";
import { connectionRepositoriesApi } from "./connectionRepositoriesApi";
import type { ConnectionRepository, ConnectionWorkspace, RepositoryConnection } from "./connectionRepositoriesApi";
import { addRepositoryToWorkspaces, defaultWorkspaceSelection, orderedWorkspaces } from "./connectionRepositoryModel";
import type { WorkspaceSaveResult } from "./connectionRepositoryModel";
import { refProblem } from "./gitRepositoryScope";

type Setter<T> = Dispatch<SetStateAction<T>>;

// The Workspaces the connection may serve; this Workspace alone when the server cannot say. Returns the cleanup.
function loadWorkspaces(workspaceId: string, connectionId: string, setWorkspaces: Setter<ConnectionWorkspace[]>, setChosen: Setter<string[]>) {
  let cancelled = false;
  const own: ConnectionWorkspace[] = [{ id: workspaceId, name: "This Workspace", current: true }];
  connectionRepositoriesApi.workspaces(workspaceId, connectionId)
    .then((answer) => {
      if (cancelled) return;
      const listed = orderedWorkspaces(answer.workspaces.length ? answer.workspaces : own);
      setWorkspaces(listed);
      setChosen(defaultWorkspaceSelection(listed, workspaceId));
    })
    .catch(() => {
      if (cancelled) return;
      setWorkspaces(own);
      setChosen([workspaceId]);
    });
  return () => { cancelled = true; };
}

// The default branch of the chosen repository; a branch typed meanwhile is kept. Returns the cleanup.
function loadDefaultBranch(workspaceId: string, connectionId: string, repository: ConnectionRepository, refTouched: MutableRefObject<boolean>,
  setRef: Setter<string>, setBranchLoading: Setter<boolean>) {
  let cancelled = false;
  refTouched.current = false;
  setRef("");
  setBranchLoading(true);
  connectionRepositoriesApi.defaultBranch(workspaceId, connectionId, repository.project_key, repository.slug)
    .then((answer) => { if (!cancelled && !refTouched.current) setRef(answer.default_branch ?? ""); })
    .catch(() => undefined)
    .finally(() => { if (!cancelled) setBranchLoading(false); });
  return () => { cancelled = true; };
}

type SaveContext = {
  repository: ConnectionRepository | null; ref: string; workspaces: ConnectionWorkspace[]; chosen: string[]; connectionId: string;
  accessMode: AccessMode; gitToken: string; datacenter: boolean; onSaved: () => void;
  setProblem: Setter<string | null>; setBusy: Setter<boolean>; setResults: Setter<WorkspaceSaveResult[] | null>; setGitToken: Setter<string>;
};

async function saveRepository(ctx: SaveContext) {
  const { repository, ref } = ctx;
  if (!repository) {
    ctx.setProblem("Choose a repository.");
    return;
  }
  const branchProblem = refProblem(ref);
  if (branchProblem) {
    ctx.setProblem(branchProblem);
    return;
  }
  const targets = ctx.workspaces.filter((workspace) => ctx.chosen.includes(workspace.id));
  if (!targets.length) {
    ctx.setProblem("Choose at least one Workspace.");
    return;
  }
  ctx.setProblem(null);
  ctx.setBusy(true);
  try {
    const done = await addRepositoryToWorkspaces(
      { workspaces: targets, repository, ref: ref.trim(), connectionId: ctx.connectionId, accessMode: ctx.accessMode, gitToken: ctx.datacenter ? ctx.gitToken : "" },
      { onProgress: ctx.setResults },
    );
    ctx.setResults(done);
    if (done.some((result) => result.state === "saved")) {
      ctx.setGitToken("");
      ctx.onSaved();
    }
  } finally {
    ctx.setBusy(false);
  }
}

// The form's state: connection, repository, branch, access, token, target Workspaces and the per-Workspace results.
export function useConnectionRepositoryForm(workspaceId: string, connections: RepositoryConnection[], onSaved: () => void, preselectedConnectionId?: string) {
  const [connectionId, setConnectionId] = useState(
    connections.find((connection) => connection.id === preselectedConnectionId)?.id ?? connections[0]?.id ?? "");
  const [repository, setRepository] = useState<ConnectionRepository | null>(null);
  const [ref, setRef] = useState("");
  const [branchLoading, setBranchLoading] = useState(false);
  const refTouched = useRef(false);
  const [accessMode, setAccessMode] = useState<AccessMode>("read_only");
  // The repository's own Git token (Data Center only); kept in this form's state only, never listed or echoed.
  const [gitToken, setGitToken] = useState("");
  const [workspaces, setWorkspaces] = useState<ConnectionWorkspace[]>([]);
  const [chosen, setChosen] = useState<string[]>([workspaceId]);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<WorkspaceSaveResult[] | null>(null);

  useEffect(() => loadWorkspaces(workspaceId, connectionId, setWorkspaces, setChosen), [workspaceId, connectionId]);

  // The default branch is read when a repository is chosen; a branch typed meanwhile is kept.
  useEffect(() => {
    if (!repository) return undefined;
    return loadDefaultBranch(workspaceId, connectionId, repository, refTouched, setRef, setBranchLoading);
  }, [workspaceId, connectionId, repository]);

  const choose = (next: ConnectionRepository) => {
    setRepository(next);
    setAccessMode(next.registered?.access_mode ?? "read_only");
    setGitToken("");
    setResults(null);
    setProblem(null);
  };
  const changeConnection = (id: string) => {
    setConnectionId(id);
    setRepository(null);
    setGitToken("");
    setResults(null);
  };
  const toggleWorkspace = (id: string, checked: boolean) =>
    setChosen((current) => (checked ? [...current.filter((item) => item !== id), id] : current.filter((item) => item !== id)));
  // A Data Center connection signed in with OpenID Connect cannot serve Git over HTTPS: the repository may bring its own token.
  const datacenter = (connections.find((item) => item.id === connectionId)?.deployment ?? "datacenter") !== "cloud";
  const save = () => saveRepository({
    repository, ref, workspaces, chosen, connectionId, accessMode, gitToken, datacenter, onSaved, setProblem, setBusy, setResults, setGitToken,
  });
  return {
    connectionId, repository, ref, setRef, branchLoading, refTouched, accessMode, setAccessMode, gitToken, setGitToken, workspaces, chosen,
    problem, busy, results, choose, changeConnection, toggleWorkspace, datacenter, save,
  };
}
