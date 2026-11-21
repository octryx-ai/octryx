// The Work area's loaded data: items, whether the Workspace has an intake, and workflows of a Workspace.
import { useState } from "react";

import { loadIntakeOverview } from "./intake/workIntakeApi";
import { loadWorkItems, loadWorkflows } from "./workApi";
import type { WorkItem } from "./workItemTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";

export function useWorkAreaData(workspaceId: string | undefined, canManageWork: boolean) {
  const [items, setItems] = useState<WorkItem[]>([]);
  const [hasIntakes, setHasIntakes] = useState(false);
  const [workflows, setWorkflows] = useState<WorkWorkflowDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [nextItems, nextHasIntakes, nextWorkflows] = await Promise.all([
        loadWorkItems(1000, workspaceId),
        // The Workspace's intakes are the Work role's; a reader does not ask for them.
        canManageWork && workspaceId
          ? loadIntakeOverview(workspaceId).then((overview) => overview.intakes.length > 0)
          : Promise.resolve(false),
        loadWorkflows(),
      ]);
      setItems(nextItems);
      setHasIntakes(nextHasIntakes);
      setWorkflows(nextWorkflows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load work items");
    } finally {
      setLoading(false);
    }
  }

  return { items, hasIntakes, workflows, loading, error, refresh };
}
