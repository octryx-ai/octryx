import { useEffect, useState } from "react";
import { readEffectivePermission, type EffectivePermission } from "./myRoleModel";

// The caller's effective permission in the chat's Workspace (roles contract §3.3,
// GET /api/v1/work-roles/workspaces/{ws}/me), re-read when the Workspace changes. The composer and the chat header
// share one request per Workspace (a short-lived cache). Any failure (no route, no
// Workspace) means "nothing to show": the chat never blocks on it.

export const myRolePath = (workspaceId: string) => `/api/v1/work-roles/workspaces/${encodeURIComponent(workspaceId)}/me`;

const FRESH_MS = 30_000;
const cache = new Map<string, { at: number; answer: Promise<EffectivePermission | null> }>();

function loadMyRole(workspaceId: string): Promise<EffectivePermission | null> {
  const hit = cache.get(workspaceId);
  if (hit && Date.now() - hit.at < FRESH_MS) return hit.answer;
  const answer = fetch(myRolePath(workspaceId), { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((response) => (response.ok ? response.json() : null))
    .then(readEffectivePermission)
    .catch(() => null);
  cache.set(workspaceId, { at: Date.now(), answer });
  return answer;
}

export function useMyRole(workspaceId: string | null | undefined): EffectivePermission | null {
  const [state, setState] = useState<{ workspaceId: string; permission: EffectivePermission | null } | null>(null);
  useEffect(() => {
    if (!workspaceId) return undefined;
    let current = true;
    void loadMyRole(workspaceId).then((permission) => {
      if (current) setState({ workspaceId, permission });
    });
    return () => {
      current = false;
    };
  }, [workspaceId]);
  return workspaceId && state?.workspaceId === workspaceId ? state.permission : null;
}
