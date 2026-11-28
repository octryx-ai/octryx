import { useEffect, useState } from "react";

import { loadClassificationWorkspaces } from "../dataClassification/dataClassificationApi";
import { readWorkspaceClasses, type WorkspaceClasses } from "./workspaceListRow";

// Only platform admins read the levels: a refusal leaves them unknown (null), never "not set".
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
