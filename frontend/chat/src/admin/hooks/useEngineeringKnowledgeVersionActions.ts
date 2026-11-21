// Engineering Knowledge version actions: publish, reject and assign one pack version, then refresh the packs.
import { useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { ReadJsonFn } from "./useAdminTabLoader.types";

type VersionActionsArgs = {
  readJson: ReadJsonFn;
  refreshEngineeringKnowledgePacks: () => Promise<void>;
  setEngineeringKnowledgeBusy: Dispatch<SetStateAction<boolean>>;
  setEngineeringKnowledgeError: Dispatch<SetStateAction<string | null>>;
};

export function useEngineeringKnowledgeVersionActions({
  readJson,
  refreshEngineeringKnowledgePacks,
  setEngineeringKnowledgeBusy,
  setEngineeringKnowledgeError,
}: VersionActionsArgs) {
  const handlePublishEngineeringKnowledgeVersion = useCallback(
    async (versionId: string) => {
      setEngineeringKnowledgeBusy(true);
      setEngineeringKnowledgeError(null);
      try {
        await readJson(
          `/admin/chat/api/panel/engineering-knowledge/versions/${encodeURIComponent(versionId)}/publish`,
          { method: "POST" },
        );
        await refreshEngineeringKnowledgePacks();
      } catch (error) {
        setEngineeringKnowledgeError(
          error instanceof Error
            ? error.message
            : "Engineering pack publish failed",
        );
      } finally {
        setEngineeringKnowledgeBusy(false);
      }
    },
    [readJson, refreshEngineeringKnowledgePacks, setEngineeringKnowledgeBusy, setEngineeringKnowledgeError],
  );

  const handleRejectEngineeringKnowledgeVersion = useCallback(
    async (versionId: string) => {
      const reason =
        window.prompt("Reason for rejecting this Engineering Pack version?") ||
        "";
      setEngineeringKnowledgeBusy(true);
      setEngineeringKnowledgeError(null);
      try {
        await readJson(
          `/admin/chat/api/panel/engineering-knowledge/versions/${encodeURIComponent(versionId)}/reject`,
          {
            method: "POST",
            body: JSON.stringify({ reason }),
          },
        );
        await refreshEngineeringKnowledgePacks();
      } catch (error) {
        setEngineeringKnowledgeError(
          error instanceof Error
            ? error.message
            : "Engineering pack rejection failed",
        );
      } finally {
        setEngineeringKnowledgeBusy(false);
      }
    },
    [readJson, refreshEngineeringKnowledgePacks, setEngineeringKnowledgeBusy, setEngineeringKnowledgeError],
  );

  const handleAssignEngineeringKnowledgeVersion = useCallback(
    async (versionId: string) => {
      setEngineeringKnowledgeBusy(true);
      setEngineeringKnowledgeError(null);
      try {
        await readJson(
          `/admin/chat/api/panel/engineering-knowledge/versions/${encodeURIComponent(versionId)}/assignments`,
          {
            method: "POST",
            body: JSON.stringify({
              scope_type: "global",
              assignment_policy: {
                resolution: "automatic",
                manual_user_selection: false,
              },
            }),
          },
        );
        await refreshEngineeringKnowledgePacks();
      } catch (error) {
        setEngineeringKnowledgeError(
          error instanceof Error
            ? error.message
            : "Engineering pack assignment failed",
        );
      } finally {
        setEngineeringKnowledgeBusy(false);
      }
    },
    [readJson, refreshEngineeringKnowledgePacks, setEngineeringKnowledgeBusy, setEngineeringKnowledgeError],
  );

  return {
    handleAssignEngineeringKnowledgeVersion,
    handlePublishEngineeringKnowledgeVersion,
    handleRejectEngineeringKnowledgeVersion,
  };
}
