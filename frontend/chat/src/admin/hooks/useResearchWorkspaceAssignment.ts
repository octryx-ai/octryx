// Research policy Workspace assignment: assign a published version to the selected Workspace or clear it.
import { useCallback, type Dispatch, type SetStateAction } from "react";
import { readJson } from "../utils/adminPanelHelpers";
import type { WorkspaceResearchPolicyPayload } from "../types/researchPolicyTypes";

type UseResearchWorkspaceAssignmentArgs = {
  runSavingAction: (action: () => Promise<void>, success: string) => Promise<boolean>;
  selectedProjectId: string;
  setWorkspacePolicy: Dispatch<SetStateAction<WorkspaceResearchPolicyPayload | null>>;
};

export function useResearchWorkspaceAssignment({
  runSavingAction,
  selectedProjectId,
  setWorkspacePolicy,
}: UseResearchWorkspaceAssignmentArgs) {
  const assignWorkspacePolicy = useCallback(
    (profileVersionId: string) =>
      runSavingAction(async () => {
        if (!selectedProjectId) throw new Error("Select a workspace first.");
        const next = await readJson<WorkspaceResearchPolicyPayload>(
          `/admin/chat/api/panel/projects/${encodeURIComponent(selectedProjectId)}/research-policy`,
          {
            method: "PUT",
            body: JSON.stringify({ profile_version_id: profileVersionId }),
          },
        );
        setWorkspacePolicy(next);
      }, "Workspace research policy assigned."),
    [runSavingAction, selectedProjectId, setWorkspacePolicy],
  );

  const clearWorkspacePolicy = useCallback(
    () =>
      runSavingAction(async () => {
        if (!selectedProjectId) throw new Error("Select a workspace first.");
        const next = await readJson<WorkspaceResearchPolicyPayload>(
          `/admin/chat/api/panel/projects/${encodeURIComponent(selectedProjectId)}/research-policy`,
          {
            method: "PUT",
            body: JSON.stringify({ clear_assignment: true }),
          },
        );
        setWorkspacePolicy(next);
      }, "Workspace assignment cleared."),
    [runSavingAction, selectedProjectId, setWorkspacePolicy],
  );

  return { assignWorkspacePolicy, clearWorkspacePolicy };
}
