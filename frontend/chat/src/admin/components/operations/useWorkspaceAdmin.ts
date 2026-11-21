import { useEffect, useState } from "react";

import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";

// Whether the viewer administers the active Workspace (platform admin, or its admin/owner): decides the Workspace-admin
// entries of the Operations menu (Costs). The app's bootstrap carries no Workspace roles, so, as Live decides on the
// stop button, the admin route answers: a read of the Workspace's emergency-stop history (small, read-only, the
// Problems scope) is 200 for its admins and 403 for everyone else. Presentation only; each page keeps the server check.

const known = new Map<string, boolean>();

export function useWorkspaceAdmin(isPlatformAdmin: boolean, projects: { id: string }[], enabled = true): boolean {
  const [activeId] = useActiveWorkspace(projects);
  const [answer, setAnswer] = useState<boolean>(() => isPlatformAdmin || known.get(activeId) === true);

  useEffect(() => {
    if (isPlatformAdmin) { setAnswer(true); return undefined; }
    if (!enabled || !activeId) { setAnswer(false); return undefined; }
    if (known.has(activeId)) { setAnswer(known.get(activeId) === true); return undefined; }
    let current = true;
    fetch(`/api/v1/admin/operations/emergency-stop/history?workspace_id=${encodeURIComponent(activeId)}`,
      { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((response) => response.ok, () => false)
      .then((ok) => {
        known.set(activeId, ok);
        if (current) setAnswer(ok);
      });
    return () => { current = false; };
  }, [isPlatformAdmin, enabled, activeId]);

  return isPlatformAdmin || answer;
}
