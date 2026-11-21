import { useEffect, useState } from "react";

import { loadClassificationWorkspaces } from "../dataClassification/dataClassificationApi";
import { readWorkspaceClasses, type WorkspaceClasses } from "./workspaceListRow";

// Each Workspace's classification level for the Workspaces list's Class column: one call for all of them. A
// refusal (only platform admins read the levels) or a failure leaves them unknown (null); the cell then offers to
// open the Workspace's classification instead of claiming it is not set.
export function useWorkspaceClasses(reloadKey: unknown): WorkspaceClasses | null {
  const [classes, setClasses] = useState<WorkspaceClasses | null>(null);
  useEffect(() => {
    let current = true;
    loadClassificationWorkspaces()
      .then((answer) => { if (current) setClasses(readWorkspaceClasses(answer)); })
      .catch(() => { if (current) setClasses(null); });
    return () => { current = false; };
  }, [reloadKey]);
  return classes;
}
