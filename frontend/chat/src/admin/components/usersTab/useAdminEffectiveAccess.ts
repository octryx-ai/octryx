import { useCallback, useState } from "react";

import type { AdminEffectiveAccessRow, AdminReadJsonFn } from "./identityTypes";

export function useAdminEffectiveAccess(readJson: AdminReadJsonFn) {
  const [accessRows, setAccessRows] = useState<AdminEffectiveAccessRow[]>([]);
  const [accessLoading, setAccessLoading] = useState(false);
  const [accessError, setAccessError] = useState<string | null>(null);

  const loadAccessDiagnostics = useCallback(async () => {
    setAccessLoading(true);
    try {
      const data = await readJson<AdminEffectiveAccessRow[]>(
        "/admin/chat/api/panel/effective-access",
      );
      setAccessRows(data);
      setAccessError(null);
    } catch (error) {
      setAccessError(
        error instanceof Error
          ? error.message
          : "Failed to load access diagnostics",
      );
    } finally {
      setAccessLoading(false);
    }
  }, [readJson]);

  return {
    accessRows,
    accessLoading,
    accessError,
    loadAccessDiagnostics,
  };
}
