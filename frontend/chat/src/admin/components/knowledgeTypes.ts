import type { Dispatch, SetStateAction } from "react";
import type {
  EngineeringKnowledgeBuildRun,
  EngineeringKnowledgePack,
  EngineeringKnowledgeRetrievalSearchPayload,
} from "../types/engineeringKnowledgeTypes";
import type { EngineeringKnowledgeBuildVersions } from "./engineeringKnowledgeBuildRequest";

export type ProjectOptionRow = {
  id: string;
  name: string;
};

// The admin Knowledge tab's props: the project selection of the entity graph.
export type AdminKnowledgeTabProps = {
  knowledgeProjectId: string;
  setKnowledgeProjectId: Dispatch<SetStateAction<string>>;
  projects: ProjectOptionRow[];
  readJson: <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;
  loadingTab: boolean;
  engineeringKnowledgeAllowNetwork: boolean;
  engineeringKnowledgeBuildRuns: EngineeringKnowledgeBuildRun[];
  engineeringKnowledgeBusy: boolean;
  engineeringKnowledgeError: string | null;
  engineeringKnowledgeLoading: boolean;
  engineeringKnowledgePackTotal: number;
  engineeringKnowledgePacks: EngineeringKnowledgePack[];
  engineeringKnowledgeBuildVersions: EngineeringKnowledgeBuildVersions;
  engineeringKnowledgeRetrievalLoading: boolean;
  engineeringKnowledgeRetrievalResults: Record<
    string,
    EngineeringKnowledgeRetrievalSearchPayload
  >;
  handleAssignEngineeringKnowledgeVersion: (versionId: string) => Promise<void>;
  handleCreateEngineeringKnowledgeBuildRun: () => Promise<void>;
  handleDeleteEngineeringKnowledgePack: (
    pack: EngineeringKnowledgePack,
  ) => Promise<void>;
  handlePublishEngineeringKnowledgeVersion: (
    versionId: string,
  ) => Promise<void>;
  handleRejectEngineeringKnowledgeVersion: (versionId: string) => Promise<void>;
  searchEngineeringKnowledgeRetrievalIndex: (
    versionId: string,
    query: string,
    recordKind: string,
  ) => Promise<EngineeringKnowledgeRetrievalSearchPayload>;
  loadEngineeringKnowledgePackDetail: (
    packId: string,
  ) => Promise<EngineeringKnowledgePack>;
  refreshEngineeringKnowledgePacks: () => Promise<void>;
  selectedEngineeringKnowledgePack: EngineeringKnowledgePack | null;
  setEngineeringKnowledgeAllowNetwork: Dispatch<SetStateAction<boolean>>;
  setEngineeringKnowledgeBuildVersions: Dispatch<
    SetStateAction<EngineeringKnowledgeBuildVersions>
  >;
};
