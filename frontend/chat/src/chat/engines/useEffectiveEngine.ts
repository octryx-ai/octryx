import { useEffect, useState } from "react";

import { loadWorkspaceEngines } from "./engineApi";
import { CLAUDE_CODE, readWorkspaceEngines } from "./engineModel";

/** The person's coding engine in a Workspace (their choice, the Workspace's or the platform's default); Claude Code
 * until the answer is in or when it cannot be read. It picks the model list of a run start. */
export function useEffectiveEngine(projectId: string | null | undefined): string {
  const [engine, setEngine] = useState(CLAUDE_CODE);
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void loadWorkspaceEngines(projectId)
      .then((payload) => { if (!cancelled) setEngine(readWorkspaceEngines(payload)?.effective.engine ?? CLAUDE_CODE); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [projectId]);
  return engine;
}
