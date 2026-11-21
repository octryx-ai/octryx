// Engineering Knowledge pack admin state: packs, build runs, selected pack, build form and retrieval results.
import { useState } from "react";

import type {
  EngineeringKnowledgeBuildRun,
  EngineeringKnowledgePack,
  EngineeringKnowledgeRetrievalSearchPayload,
} from "../types/engineeringKnowledgeTypes";
import {
  DEFAULT_ENGINEERING_KNOWLEDGE_BUILD_VERSIONS,
  type EngineeringKnowledgeBuildVersions,
} from "../components/engineeringKnowledgeBuildRequest";

export function useEngineeringKnowledgePackState() {
  const [engineeringKnowledgePacks, setEngineeringKnowledgePacks] = useState<
    EngineeringKnowledgePack[]
  >([]);
  const [engineeringKnowledgePackTotal, setEngineeringKnowledgePackTotal] =
    useState(0);
  const [engineeringKnowledgeBuildRuns, setEngineeringKnowledgeBuildRuns] =
    useState<EngineeringKnowledgeBuildRun[]>([]);
  const [
    selectedEngineeringKnowledgePack,
    setSelectedEngineeringKnowledgePack,
  ] = useState<EngineeringKnowledgePack | null>(null);
  const [
    engineeringKnowledgeBuildVersions,
    setEngineeringKnowledgeBuildVersions,
  ] = useState<EngineeringKnowledgeBuildVersions>(
    DEFAULT_ENGINEERING_KNOWLEDGE_BUILD_VERSIONS,
  );
  const [
    engineeringKnowledgeAllowNetwork,
    setEngineeringKnowledgeAllowNetwork,
  ] = useState(false);
  const [engineeringKnowledgeLoading, setEngineeringKnowledgeLoading] =
    useState(false);
  const [engineeringKnowledgeBusy, setEngineeringKnowledgeBusy] =
    useState(false);
  const [
    engineeringKnowledgeRetrievalLoading,
    setEngineeringKnowledgeRetrievalLoading,
  ] = useState(false);
  const [
    engineeringKnowledgeRetrievalResults,
    setEngineeringKnowledgeRetrievalResults,
  ] = useState<Record<string, EngineeringKnowledgeRetrievalSearchPayload>>({});
  const [engineeringKnowledgeError, setEngineeringKnowledgeError] = useState<
    string | null
  >(null);
  return {
    engineeringKnowledgePacks, setEngineeringKnowledgePacks,
    engineeringKnowledgePackTotal, setEngineeringKnowledgePackTotal,
    engineeringKnowledgeBuildRuns, setEngineeringKnowledgeBuildRuns,
    selectedEngineeringKnowledgePack, setSelectedEngineeringKnowledgePack,
    engineeringKnowledgeBuildVersions, setEngineeringKnowledgeBuildVersions,
    engineeringKnowledgeAllowNetwork, setEngineeringKnowledgeAllowNetwork,
    engineeringKnowledgeLoading, setEngineeringKnowledgeLoading,
    engineeringKnowledgeBusy, setEngineeringKnowledgeBusy,
    engineeringKnowledgeRetrievalLoading, setEngineeringKnowledgeRetrievalLoading,
    engineeringKnowledgeRetrievalResults, setEngineeringKnowledgeRetrievalResults,
    engineeringKnowledgeError, setEngineeringKnowledgeError,
  };
}

export type EngineeringKnowledgePackState = ReturnType<typeof useEngineeringKnowledgePackState>;
