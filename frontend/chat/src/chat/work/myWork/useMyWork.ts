import { useCallback, useEffect, useState } from "react";

import { clearMyWork, loadMyWork, saveMyWork } from "./myWorkApi";
import { defaultScope, readStoredScope, scopeStorageKey, type MyWorkState, type WorkItemsScope } from "./myWorkModel";

export type MyWork = {
  state: MyWorkState;
  scope: WorkItemsScope;
  setScope: (scope: WorkItemsScope) => void;
  /** The person asked to pick another Jira account. */
  changing: boolean;
  setChanging: (value: boolean) => void;
  busy: boolean;
  choose: (accountId: string) => Promise<void>;
  clear: () => Promise<void>;
  retry: () => void;
};

// The person's last My work | All items choice per Workspace, in this browser only; a blocked storage keeps nothing.
function storedScope(workspaceId: string): WorkItemsScope | null {
  try {
    return readStoredScope(window.localStorage.getItem(scopeStorageKey(workspaceId)));
  } catch {
    return null;
  }
}

function storeScope(workspaceId: string, scope: WorkItemsScope) {
  try {
    window.localStorage.setItem(scopeStorageKey(workspaceId), scope);
  } catch {
    // Not kept: the page opens on My work next time.
  }
}

// "You in Jira" for the active Workspace: loaded on every Workspace switch; the page opens on My work (or the
// person's last choice), and on all items only when this server cannot keep who they are in Jira.
export function useMyWork(workspaceId: string | null | undefined): MyWork {
  const [state, setState] = useState<MyWorkState>({ kind: "loading" });
  const [scope, setScopeState] = useState<WorkItemsScope>("all");
  const [changing, setChanging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState(0);

  useEffect(() => {
    let current = true;
    setChanging(false);
    if (!workspaceId) {
      setState({ kind: "unavailable" });
      setScopeState("all");
      return;
    }
    setState({ kind: "loading" });
    // Opens on the person's scope at once (no list of every item that turns into My work a moment later).
    setScopeState(defaultScope({ kind: "loading" }, storedScope(workspaceId)));
    void loadMyWork(workspaceId).then((next) => {
      if (!current) return;
      setState(next);
      setScopeState(defaultScope(next, storedScope(workspaceId)));
    });
    return () => {
      current = false;
    };
  }, [workspaceId, token]);

  // The person's own choice (the switch, "Show all items") is remembered for this Workspace.
  const setScope = useCallback((next: WorkItemsScope) => {
    setScopeState(next);
    if (workspaceId) storeScope(workspaceId, next);
  }, [workspaceId]);

  const choose = useCallback(async (accountId: string) => {
    if (!workspaceId || !accountId) return;
    setBusy(true);
    const next = await saveMyWork(workspaceId, accountId);
    setBusy(false);
    setState(next);
    if (next.kind === "set") {
      setChanging(false);
      setScopeState("mine");
    }
  }, [workspaceId]);

  const clear = useCallback(async () => {
    if (!workspaceId) return;
    setBusy(true);
    const next = await clearMyWork(workspaceId);
    setBusy(false);
    setState(next);
    setChanging(false);
  }, [workspaceId]);

  const retry = useCallback(() => setToken((value) => value + 1), []);

  return { state, scope, setScope, changing, setChanging, busy, choose, clear, retry };
}
