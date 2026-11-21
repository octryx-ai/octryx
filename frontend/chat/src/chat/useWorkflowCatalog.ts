import { useEffect, useState } from "react";

import type { WorkflowOption } from "../chatOptionTypes";
import { chatApiPath, readJson } from "./chatApiClient";

type Catalog = {
  workspaceId: string;
  status: "loading" | "ready" | "error";
  options: WorkflowOption[];
  proposalsEnabled: boolean;
};
type Response = {
  workflows: WorkflowOption[];
  workflow_proposal_enabled?: boolean;
};
const empty = (workspaceId: string, status: Catalog["status"]): Catalog => ({
  workspaceId, status, options: [], proposalsEnabled: false,
});

export function scopedWorkflowOptions(options: WorkflowOption[], scope: string) {
  const byKey = new Map<string, WorkflowOption>();
  for (const option of options) {
    if (option.project_id && option.project_id !== scope) continue;
    if (!byKey.has(option.key) || option.project_id === scope) byKey.set(option.key, option);
  }
  return [...byKey.values()];
}

export function useWorkflowCatalog(workspaceId: string) {
  const scope = workspaceId.trim();
  const [catalog, setCatalog] = useState<Catalog>(() => empty(scope, "loading"));
  useEffect(() => {
    let cancelled = false;
    setCatalog(empty(scope, "loading"));
    const query = scope ? `?${new URLSearchParams({ project_id: scope })}` : "";
    readJson<Response>(chatApiPath(`/workflows${query}`))
      .then((payload) => {
        if (!cancelled) {
          setCatalog({ workspaceId: scope, status: "ready", options: scopedWorkflowOptions(payload.workflows ?? [], scope),
            proposalsEnabled: payload.workflow_proposal_enabled === true });
        }
      })
      .catch(() => {
        if (!cancelled) setCatalog(empty(scope, "error"));
      });
    return () => { cancelled = true; };
  }, [scope]);
  // Hide prior scope options before the new effect runs, including A -> B -> A races.
  return catalog.workspaceId === scope ? catalog : empty(scope, "loading");
}
