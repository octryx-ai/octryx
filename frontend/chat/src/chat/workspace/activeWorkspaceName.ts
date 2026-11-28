import { useSyncExternalStore } from "react";

// Plain module state: the switch is mounted once per shell.

let current = "";
const listeners = new Set<() => void>();

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

export function useActiveWorkspaceName(): string {
  return useSyncExternalStore(subscribe, readActiveWorkspaceName, readActiveWorkspaceName);
}

export function areaWithWorkspace(area: string, workspaceName: string): string {
  return workspaceName ? `${area} · ${workspaceName}` : area;
}
