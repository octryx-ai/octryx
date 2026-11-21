import { createContext, useContext } from "react";

// Who may change Work (a team leader shows the team its work). Every Workspace member reads Work
// items, Board, Plans, Runs, Epics and pull requests; starting a workflow, moving, closing and the configuration pages
// stay with the Work role (admin/operation). A reader never sees a control the server would refuse.
export const WORK_MANAGER_ROLES = ["admin", "operation", "operations", "operator"];

export function canManageWorkWith(roles: readonly string[]): boolean {
  return roles.some((role) => WORK_MANAGER_ROLES.includes(role.trim().toLowerCase()));
}

/** Members of a Workspace read its Work; who manages Work reads it everywhere it may. */
export function canReadWorkWith(roles: readonly string[], workspaceCount: number): boolean {
  return canManageWorkWith(roles) || workspaceCount > 0;
}

/** The Work pages a reader does not see: they configure or start work. */
export const MANAGER_ONLY_PAGES = new Set(["work:intake", "coding:rules", "coding:sessions", "coding:pipelines"]);

export function visibleToReader(host: string, key: string): boolean {
  return !MANAGER_ONLY_PAGES.has(`${host}:${key}`);
}

export const WorkAccessContext = createContext<boolean>(true);

export function useCanManageWork(): boolean {
  return useContext(WorkAccessContext);
}
