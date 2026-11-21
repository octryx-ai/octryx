import type { Dispatch, SetStateAction } from "react";
import type { AdminProjectQuality } from "../types/projectQualityTypes";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type UseAdminProjectDesignTraceArgs = {
  readJson: ReadJsonFn;
  configuringProjectQuality: AdminProjectQuality | null;
  setAdminProjects: Dispatch<SetStateAction<AdminProjectQuality[]>>;
  setConfiguringProjectQuality: Dispatch<
    SetStateAction<AdminProjectQuality | null>
  >;
  setProjectQualityLoading: Dispatch<SetStateAction<boolean>>;
  setProjectQualityError: Dispatch<SetStateAction<string | null>>;
  editingProjectDesignArtifactId: string | null;
  projectDesignArtifactKind: string;
  projectDesignArtifactTitle: string;
  projectDesignArtifactStatus: string;
  projectDesignArtifactSummary: string;
  projectDesignArtifactContent: string;
  projectDesignArtifactLinkedRepositoryIds: string[];
  projectDesignArtifactDependsOnArtifactIds: string[];
  projectDesignArtifactRequired: boolean;
  projectDesignArtifactOrder: string;
  projectDesignTraceArtifactId: string;
  projectDesignTraceTargetType: string;
  projectDesignTraceTargetId: string;
  projectDesignTraceTitle: string;
  projectDesignTraceStatus: string;
  projectDesignTraceUrl: string;
  resetProjectDesignArtifactForm: () => void;
  resetProjectDesignTraceForm: () => void;
};
