import { useCallback, useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { PERMISSION_MODES_ENDPOINT } from "./permissionModeCatalog";
import type { PermissionModeCatalog, PermissionModeRow } from "./permissionModeCatalog";

export type PermissionModeLoader = () => Promise<PermissionModeRow[]>;

// Read structurally: an error from another realm (iframe, test VM) is still reported by its message.
function errorMessage(err: unknown): string {
  const message = (err as { message?: unknown } | null)?.message;
  return typeof message === "string" && message ? message : "request failed";
}

const loadPermissionModes: PermissionModeLoader = () => readJson<PermissionModeRow[]>(PERMISSION_MODES_ENDPOINT);

// The form's own catalog: loaded each time the form opens, with an explicit retry after an error.
export function usePermissionModeCatalog(enabled: boolean, load: PermissionModeLoader = loadPermissionModes) {
  const [catalog, setCatalog] = useState<PermissionModeCatalog>({ status: "loading", modes: [] });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setCatalog((current) => ({ status: "loading", modes: current.modes }));
    load()
      .then((modes) => {
        if (!cancelled) setCatalog({ status: "ready", modes: Array.isArray(modes) ? modes : [] });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCatalog({ status: "error", modes: [], error: errorMessage(err) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, attempt, load]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { catalog, retry };
}
