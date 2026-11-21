import { useCallback, useEffect, useState } from "react";

import { isOpsRefusal, loadSeatUsage } from "./operationsApi";
import { isMissingRoute, refusalText, type SeatUsageReport } from "./seatUsageModel";

// The seat report of Operations › Costs › Seats by person, loaded with the page's scope and period, so the view switch
// knows at once whether this server has the route (a 404 without a reason hides the view).
export type SeatUsageState = { report: SeatUsageReport | null; error: string; missing: boolean; reload: () => void };

/** Loads the seat report for the scope; `missing` when this server has no such route (the sub-view is hidden then). */
export function useSeatUsage(query: { workspaceId: string; days: number; ready: boolean }): SeatUsageState {
  const [report, setReport] = useState<SeatUsageReport | null>(null);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);
  const { workspaceId, days, ready } = query;

  const reload = useCallback(async () => {
    if (!ready) return;
    setReport(null);
    setError("");
    try {
      setReport(await loadSeatUsage({ workspaceId, days }));
    } catch (failure) {
      if (isOpsRefusal(failure) && isMissingRoute(failure)) setMissing(true);
      else if (isOpsRefusal(failure)) setError(refusalText(failure));
      else setError("Seat usage could not be loaded.");
    }
  }, [workspaceId, days, ready]);

  useEffect(() => { void reload(); }, [reload]);
  return { report, error, missing, reload: () => void reload() };
}

