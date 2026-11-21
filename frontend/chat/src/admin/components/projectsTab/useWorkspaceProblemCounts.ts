import { useEffect, useState } from "react";

import { loadAdminProblems } from "../problems/problemsApi";
import { problemCountsByWorkspace } from "./workspaceListRow";
import type { WorkspaceProblemCounts } from "../AdminProjectsSummarySection";

// Problems per Workspace for the Workspaces list: one unfiltered Admin › Problems call, grouped by Workspace. Any
// refusal or failure leaves the counts unknown (null), so the list simply has no Problems column.
export function useWorkspaceProblemCounts(reloadKey: unknown): WorkspaceProblemCounts | null {
  const [counts, setCounts] = useState<WorkspaceProblemCounts | null>(null);
  useEffect(() => {
    let current = true;
    loadAdminProblems({})
      .then((list) => { if (current) setCounts(problemCountsByWorkspace(list.problems)); })
      .catch(() => { if (current) setCounts(null); });
    return () => { current = false; };
  }, [reloadKey]);
  return counts;
}
