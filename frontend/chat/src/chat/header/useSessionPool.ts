// "Put into the session pool" for the open chat: the holder hands the session to whoever in its Workspace can run it.
// The answer shows in the menu entry itself (the server's refusal in its own words).
import { useCallback, useEffect, useState } from "react";
import { readJson } from "../../admin/utils/adminPanelHelpers";

export type SessionPoolItem = { label: string; onSelect: () => void; disabled: boolean };

export const POOL_ACTION = "Put into the session pool";
export const POOLED = "In the session pool: whoever can run it may take it over";

export function useSessionPool(sessionId: string | null): SessionPoolItem | null {
  const [state, setState] = useState<{ label: string; disabled: boolean }>({ label: POOL_ACTION, disabled: false });
  useEffect(() => setState({ label: POOL_ACTION, disabled: false }), [sessionId]);
  const onSelect = useCallback(() => {
    if (!sessionId) return;
    setState({ label: "Putting into the pool…", disabled: true });
    readJson<unknown>("/api/v1/session-handovers", { method: "POST", body: JSON.stringify({ session_id: sessionId }) })
      .then(() => setState({ label: POOLED, disabled: true }))
      .catch((error: { message?: string }) => setState({ label: `Not in the pool: ${error?.message || "refused"}`, disabled: false }));
  }, [sessionId]);
  return sessionId ? { ...state, onSelect } : null;
}
