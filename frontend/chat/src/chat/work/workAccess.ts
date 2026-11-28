import { createContext, useContext } from "react";

// A reader never sees a control the server would refuse.
export const WORK_MANAGER_ROLES = ["admin", "operation", "operations", "operator"];

export function canManageWorkWith(roles: readonly string[]): boolean {
  return roles.some((role) => WORK_MANAGER_ROLES.includes(role.trim().toLowerCase()));
}

export function canReadWorkWith(roles: readonly string[], workspaceCount: number): boolean {
  return canManageWorkWith(roles) || workspaceCount > 0;
}

export const MANAGER_ONLY_PAGES = new Set(["work:intake", "coding:rules", "coding:sessions", "coding:pipelines"]);

export function visibleToReader(host: string, key: string): boolean {
  return !MANAGER_ONLY_PAGES.has(`${host}:${key}`);
}

export const WorkAccessContext = createContext<boolean>(true);

export function useCanManageWork(): boolean {
  return useContext(WorkAccessContext);
}
