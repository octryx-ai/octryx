import { useSyncExternalStore } from "react";

// The written-out name of the active Workspace, published by the one global switch so every
// area's sidebar head can read "Work · Test" without loading the Workspace list again. Plain module state: the switch
// is mounted once per shell, and an area without a switch simply shows no name.

let current = "";
const listeners = new Set<() => void>();

/** Called by the global switch whenever the active Workspace (or its name) changes. */
export function publishActiveWorkspaceName(name: string | null | undefined) {
  const next = String(name ?? "").trim();
  if (next === current) return;
  current = next;
  listeners.forEach((listener) => listener());
}

export function readActiveWorkspaceName(): string {
  return current;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The active Workspace's name, "" when none is chosen. */
export function useActiveWorkspaceName(): string {
  return useSyncExternalStore(subscribe, readActiveWorkspaceName, readActiveWorkspaceName);
}

/** "Work · Test" for a sidebar head; just the area without a Workspace. */
export function areaWithWorkspace(area: string, workspaceName: string): string {
  return workspaceName ? `${area} · ${workspaceName}` : area;
}
