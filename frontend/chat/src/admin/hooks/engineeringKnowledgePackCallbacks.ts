// Engineering Knowledge pack callbacks of the admin hook; the request bodies live in engineeringKnowledgePackRequests.
import { useCallback } from "react";

import type { EngineeringKnowledgePack } from "../types/engineeringKnowledgeTypes";
import { createBuildRun, deletePack, refreshPacks, searchRetrievalIndex } from "./engineeringKnowledgePackRequests";
import type { EngineeringKnowledgePackState } from "./engineeringKnowledgePackState";
import type { ReadJsonFn } from "./useAdminTabLoader.types";

export function usePackLoadCallbacks(readJson: ReadJsonFn, state: EngineeringKnowledgePackState) {
  const {
    selectedEngineeringKnowledgePack, setSelectedEngineeringKnowledgePack, setEngineeringKnowledgeLoading,
    setEngineeringKnowledgeError, setEngineeringKnowledgePacks, setEngineeringKnowledgePackTotal,
    setEngineeringKnowledgeBuildRuns,
  } = state;
  const loadEngineeringKnowledgePackDetail = useCallback(
    async (packId: string) => {
      const detail = await readJson<EngineeringKnowledgePack>(
        `/admin/chat/api/panel/engineering-knowledge/packs/${encodeURIComponent(packId)}`,
      );
      setSelectedEngineeringKnowledgePack(detail);
      return detail;
    },
    [readJson, setSelectedEngineeringKnowledgePack],
  );

  const refreshEngineeringKnowledgePacks = useCallback(async () => {
    await refreshPacks({
      readJson, selectedId: selectedEngineeringKnowledgePack?.id, setEngineeringKnowledgeLoading,
      setEngineeringKnowledgeError, setEngineeringKnowledgePacks, setEngineeringKnowledgePackTotal,
      setEngineeringKnowledgeBuildRuns, setSelectedEngineeringKnowledgePack,
    }, loadEngineeringKnowledgePackDetail);
  }, [
    loadEngineeringKnowledgePackDetail,
    readJson,
    selectedEngineeringKnowledgePack?.id,
    setEngineeringKnowledgeLoading, setEngineeringKnowledgeError, setEngineeringKnowledgePacks,
    setEngineeringKnowledgePackTotal, setEngineeringKnowledgeBuildRuns, setSelectedEngineeringKnowledgePack,
  ]);
  return { loadEngineeringKnowledgePackDetail, refreshEngineeringKnowledgePacks };
}

export function usePackEditCallbacks(
  readJson: ReadJsonFn,
  state: EngineeringKnowledgePackState,
  { loadEngineeringKnowledgePackDetail, refreshEngineeringKnowledgePacks }: ReturnType<typeof usePackLoadCallbacks>,
) {
  const {
    engineeringKnowledgeAllowNetwork, engineeringKnowledgeBuildVersions, selectedEngineeringKnowledgePack,
    setEngineeringKnowledgeError, setEngineeringKnowledgeBusy, setSelectedEngineeringKnowledgePack,
  } = state;
  const handleCreateEngineeringKnowledgeBuildRun = useCallback(async () => {
    await createBuildRun({
      readJson, engineeringKnowledgeBuildVersions, engineeringKnowledgeAllowNetwork, setEngineeringKnowledgeError,
      setEngineeringKnowledgeBusy,
    }, refreshEngineeringKnowledgePacks, loadEngineeringKnowledgePackDetail);
  }, [
    engineeringKnowledgeAllowNetwork,
    engineeringKnowledgeBuildVersions,
    loadEngineeringKnowledgePackDetail,
    readJson,
    refreshEngineeringKnowledgePacks,
    setEngineeringKnowledgeError, setEngineeringKnowledgeBusy,
  ]);

  const handleDeleteEngineeringKnowledgePack = useCallback(
    async (pack: EngineeringKnowledgePack) => {
      await deletePack({
        readJson, selectedId: selectedEngineeringKnowledgePack?.id, setEngineeringKnowledgeBusy,
        setEngineeringKnowledgeError, setSelectedEngineeringKnowledgePack,
      }, refreshEngineeringKnowledgePacks, pack);
    },
    [
      readJson,
      refreshEngineeringKnowledgePacks,
      selectedEngineeringKnowledgePack?.id,
      setEngineeringKnowledgeBusy, setEngineeringKnowledgeError, setSelectedEngineeringKnowledgePack,
    ],
  );
  return { handleCreateEngineeringKnowledgeBuildRun, handleDeleteEngineeringKnowledgePack };
}

export function useRetrievalSearchCallback(readJson: ReadJsonFn, state: EngineeringKnowledgePackState) {
  const {
    setEngineeringKnowledgeRetrievalLoading, setEngineeringKnowledgeError, setEngineeringKnowledgeRetrievalResults,
  } = state;
  return useCallback(
    (versionId: string, query: string, recordKind: string) =>
      searchRetrievalIndex({
        readJson, setEngineeringKnowledgeRetrievalLoading, setEngineeringKnowledgeError,
        setEngineeringKnowledgeRetrievalResults,
      }, versionId, query, recordKind),
    [readJson, setEngineeringKnowledgeRetrievalLoading, setEngineeringKnowledgeError, setEngineeringKnowledgeRetrievalResults],
  );
}
