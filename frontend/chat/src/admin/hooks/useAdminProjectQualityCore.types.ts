import type { Dispatch, FormEvent, SetStateAction } from "react";

import type { AdminProjectQuality } from "../types/projectQualityTypes";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type UseAdminProjectQualityCoreArgs = {
  readJson: ReadJsonFn;
  setAdminProjects: Dispatch<SetStateAction<AdminProjectQuality[]>>;
  configuringProjectQuality: AdminProjectQuality | null;
  setConfiguringProjectQuality: Dispatch<
    SetStateAction<AdminProjectQuality | null>
  >;
  projectQualityDraft: string;
  setProjectQualityDraft: Dispatch<SetStateAction<string>>;
  setProjectQualityLoading: Dispatch<SetStateAction<boolean>>;
  setProjectQualityError: Dispatch<SetStateAction<string | null>>;
  projectRepoBootstrapEnabled: boolean;
  setProjectRepoBootstrapEnabled: Dispatch<SetStateAction<boolean>>;
  projectRepoBootstrapProvider: string;
  setProjectRepoBootstrapProvider: Dispatch<SetStateAction<string>>;
  projectRepoBootstrapAutoOnSessionStart: boolean;
  setProjectRepoBootstrapAutoOnSessionStart: Dispatch<SetStateAction<boolean>>;
  projectRepoBootstrapWorkspaceSubdir: string;
  setProjectRepoBootstrapWorkspaceSubdir: Dispatch<SetStateAction<string>>;
  projectRepoBootstrapDefaultRepoName: string;
  setProjectRepoBootstrapDefaultRepoName: Dispatch<SetStateAction<string>>;
  projectRepoBootstrapDefaultBranch: string;
  setProjectRepoBootstrapDefaultBranch: Dispatch<SetStateAction<string>>;
  projectRepoBootstrapRemoteVisibility: string;
  setProjectRepoBootstrapRemoteVisibility: Dispatch<SetStateAction<string>>;
  projectRepoBootstrapGithubOwner: string;
  setProjectRepoBootstrapGithubOwner: Dispatch<SetStateAction<string>>;
  projectRepoBootstrapGithubOwnerType: string;
  setProjectRepoBootstrapGithubOwnerType: Dispatch<SetStateAction<string>>;
  projectRepoBootstrapBitbucketProjectKey: string;
  setProjectRepoBootstrapBitbucketProjectKey: Dispatch<SetStateAction<string>>;
  setEditingProjectDesignArtifactId: Dispatch<SetStateAction<string | null>>;
  setProjectDesignArtifactKind: Dispatch<SetStateAction<string>>;
  setProjectDesignArtifactTitle: Dispatch<SetStateAction<string>>;
  setProjectDesignArtifactStatus: Dispatch<SetStateAction<string>>;
  setProjectDesignArtifactSummary: Dispatch<SetStateAction<string>>;
  setProjectDesignArtifactContent: Dispatch<SetStateAction<string>>;
  setProjectDesignArtifactLinkedRepositoryIds: Dispatch<
    SetStateAction<string[]>
  >;
  setProjectDesignArtifactDependsOnArtifactIds: Dispatch<
    SetStateAction<string[]>
  >;
  setProjectDesignArtifactRequired: Dispatch<SetStateAction<boolean>>;
  setProjectDesignArtifactOrder: Dispatch<SetStateAction<string>>;
  setProjectDesignTraceArtifactId: Dispatch<SetStateAction<string>>;
  setProjectDesignTraceTargetType: Dispatch<SetStateAction<string>>;
  setProjectDesignTraceTargetId: Dispatch<SetStateAction<string>>;
  setProjectDesignTraceTitle: Dispatch<SetStateAction<string>>;
  setProjectDesignTraceStatus: Dispatch<SetStateAction<string>>;
  setProjectDesignTraceUrl: Dispatch<SetStateAction<string>>;
  setEditingProjectCodeRepositoryId: Dispatch<SetStateAction<string | null>>;
  editingProjectCodeRepositoryId: string | null;
  projectCodeRepositoryName: string;
  setProjectCodeRepositoryName: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryDescription: string;
  setProjectCodeRepositoryDescription: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryRoot: string;
  setProjectCodeRepositoryRoot: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryProvider: string;
  setProjectCodeRepositoryProvider: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryRemoteUrl: string;
  setProjectCodeRepositoryRemoteUrl: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryBranch: string;
  setProjectCodeRepositoryBranch: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryIndexBackend: string;
  setProjectCodeRepositoryIndexBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositorySemanticBackend: string;
  setProjectCodeRepositorySemanticBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryStructureBackend: string;
  setProjectCodeRepositoryStructureBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryGraphBackend: string;
  setProjectCodeRepositoryGraphBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryActive: boolean;
  setProjectCodeRepositoryActive: Dispatch<SetStateAction<boolean>>;
  setProjectCodeRepositoryLoading: Dispatch<SetStateAction<boolean>>;
  setProjectCodeRepositoryRunningId: Dispatch<SetStateAction<string | null>>;
  projectRuntimePolicyDraft: string;
  setProjectRuntimePolicyDraft: Dispatch<SetStateAction<string>>;
};
