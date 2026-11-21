import { useEffect, useMemo, useState } from "react";
import { workspaceKnowledgeApi } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeApi";
import type { BindingsOverview } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
// One bindings read per workspace while it is in flight: a Knowledge page asks twice at once (the page and its
// status line), and both share that answer. A later visit reads again, so a permission is never served stale.
const pendingBindings = new Map<string, Promise<BindingsOverview>>();
export function sharedBindingsRead(workspaceId: string): Promise<BindingsOverview> {
  const pending = pendingBindings.get(workspaceId);
  if (pending) return pending;
  const read = workspaceKnowledgeApi.bindings(workspaceId);
  pendingBindings.set(workspaceId, read);
  const forget = () => { if (pendingBindings.get(workspaceId) === read) pendingBindings.delete(workspaceId); };
  read.then(forget, forget);
  return read;
}
export function useKnowledgePermissions(workspaceId: string, load: (workspaceId: string) => Promise<BindingsOverview> = sharedBindingsRead) {
  return useKnowledgePermissionState(workspaceId, load).mayAuthor;
}
// The same read, also saying whether it has answered yet, so "not answered yet" is never read as "no author"
// (the Repositories page would skip the repository sources and say "No repository connected yet").
export function useKnowledgePermissionState(workspaceId: string,
  load: (workspaceId: string) => Promise<BindingsOverview> = sharedBindingsRead) {
  // A return to the same workspace is a new scope visit and requires a fresh permission read.
  const scope = useMemo(() => ({ workspaceId }), [workspaceId]);
  const [permission, setPermission] = useState<{ scope: typeof scope; mayAuthor: boolean } | null>(null);
  useEffect(() => {
    let active = true;
    const accept = (result?: BindingsOverview) => {
      if (active) setPermission({ scope, mayAuthor: result?.may_author === true });
    };
    void load(scope.workspaceId).then(accept, () => accept());
    return () => { active = false; };
  }, [scope, load]);
  const resolved = permission?.scope === scope;
  return { resolved, mayAuthor: resolved && permission.mayAuthor };
}
