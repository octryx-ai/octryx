import {
  usePackEditCallbacks,
  usePackLoadCallbacks,
  useRetrievalSearchCallback,
} from "./engineeringKnowledgePackCallbacks";
import { useEngineeringKnowledgePackState } from "./engineeringKnowledgePackState";
import type { ReadJsonFn } from "./useAdminTabLoader.types";
import { useEngineeringKnowledgeVersionActions } from "./useEngineeringKnowledgeVersionActions";

export function useAdminEngineeringKnowledgePacks(readJson: ReadJsonFn) {
  const state = useEngineeringKnowledgePackState();
  const loadCallbacks = usePackLoadCallbacks(readJson, state);
  const { loadEngineeringKnowledgePackDetail, refreshEngineeringKnowledgePacks } = loadCallbacks;
  const { handleCreateEngineeringKnowledgeBuildRun, handleDeleteEngineeringKnowledgePack } =
    usePackEditCallbacks(readJson, state, loadCallbacks);

  const {
    handleAssignEngineeringKnowledgeVersion,
    handlePublishEngineeringKnowledgeVersion,
    handleRejectEngineeringKnowledgeVersion,
  } = useEngineeringKnowledgeVersionActions({
    readJson,
    refreshEngineeringKnowledgePacks,
    setEngineeringKnowledgeBusy: state.setEngineeringKnowledgeBusy,
    setEngineeringKnowledgeError: state.setEngineeringKnowledgeError,
  });

  const searchEngineeringKnowledgeRetrievalIndex = useRetrievalSearchCallback(readJson, state);

  return {
    engineeringKnowledgeAllowNetwork: state.engineeringKnowledgeAllowNetwork,
    engineeringKnowledgeBuildRuns: state.engineeringKnowledgeBuildRuns,
    engineeringKnowledgeBusy: state.engineeringKnowledgeBusy,
    engineeringKnowledgeError: state.engineeringKnowledgeError,
    engineeringKnowledgeLoading: state.engineeringKnowledgeLoading,
    engineeringKnowledgePackTotal: state.engineeringKnowledgePackTotal,
    engineeringKnowledgePacks: state.engineeringKnowledgePacks,
    engineeringKnowledgeBuildVersions: state.engineeringKnowledgeBuildVersions,
    engineeringKnowledgeRetrievalLoading: state.engineeringKnowledgeRetrievalLoading,
    engineeringKnowledgeRetrievalResults: state.engineeringKnowledgeRetrievalResults,
    handleAssignEngineeringKnowledgeVersion,
    handleCreateEngineeringKnowledgeBuildRun,
    handleDeleteEngineeringKnowledgePack,
    handlePublishEngineeringKnowledgeVersion,
    handleRejectEngineeringKnowledgeVersion,
    loadEngineeringKnowledgePackDetail,
    refreshEngineeringKnowledgePacks,
    searchEngineeringKnowledgeRetrievalIndex,
    selectedEngineeringKnowledgePack: state.selectedEngineeringKnowledgePack,
    setEngineeringKnowledgeAllowNetwork: state.setEngineeringKnowledgeAllowNetwork,
    setEngineeringKnowledgeBuildVersions: state.setEngineeringKnowledgeBuildVersions,
  };
}
