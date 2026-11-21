import type { Dispatch, SetStateAction } from "react";
import type { AdminProjectQuality } from "../types/projectQualityTypes";

type RepositoryBootstrapDraftSetters = {
  setProjectRepoBootstrapEnabled: Dispatch<SetStateAction<boolean>>;
  setProjectRepoBootstrapProvider: Dispatch<SetStateAction<string>>;
  setProjectRepoBootstrapAutoOnSessionStart: Dispatch<SetStateAction<boolean>>;
  setProjectRepoBootstrapWorkspaceSubdir: Dispatch<SetStateAction<string>>;
  setProjectRepoBootstrapDefaultRepoName: Dispatch<SetStateAction<string>>;
  setProjectRepoBootstrapDefaultBranch: Dispatch<SetStateAction<string>>;
  setProjectRepoBootstrapRemoteVisibility: Dispatch<SetStateAction<string>>;
  setProjectRepoBootstrapGithubOwner: Dispatch<SetStateAction<string>>;
  setProjectRepoBootstrapGithubOwnerType: Dispatch<SetStateAction<string>>;
  setProjectRepoBootstrapBitbucketProjectKey: Dispatch<SetStateAction<string>>;
};

type SetProjectQualityList = Dispatch<SetStateAction<AdminProjectQuality[]>>;
type SetProjectQualityCurrent = Dispatch<
  SetStateAction<AdminProjectQuality | null>
>;

export function resetProjectRepositoryBootstrapDrafts({
  setProjectRepoBootstrapEnabled,
  setProjectRepoBootstrapProvider,
  setProjectRepoBootstrapAutoOnSessionStart,
  setProjectRepoBootstrapWorkspaceSubdir,
  setProjectRepoBootstrapDefaultRepoName,
  setProjectRepoBootstrapDefaultBranch,
  setProjectRepoBootstrapRemoteVisibility,
  setProjectRepoBootstrapGithubOwner,
  setProjectRepoBootstrapGithubOwnerType,
  setProjectRepoBootstrapBitbucketProjectKey,
}: RepositoryBootstrapDraftSetters) {
  setProjectRepoBootstrapEnabled(true);
  setProjectRepoBootstrapProvider("local");
  setProjectRepoBootstrapAutoOnSessionStart(false);
  setProjectRepoBootstrapWorkspaceSubdir("");
  setProjectRepoBootstrapDefaultRepoName("");
  setProjectRepoBootstrapDefaultBranch("main");
  setProjectRepoBootstrapRemoteVisibility("private");
  setProjectRepoBootstrapGithubOwner("");
  setProjectRepoBootstrapGithubOwnerType("org");
  setProjectRepoBootstrapBitbucketProjectKey("");
}

export function hydrateProjectRepositoryBootstrapDrafts(
  project: AdminProjectQuality,
  setters: RepositoryBootstrapDraftSetters,
) {
  const repositoryBootstrap =
    typeof project.repository_bootstrap === "object" &&
    project.repository_bootstrap
      ? (project.repository_bootstrap as Record<string, unknown>)
      : {};

  setters.setProjectRepoBootstrapEnabled(
    Boolean(repositoryBootstrap.enabled ?? true),
  );
  setters.setProjectRepoBootstrapProvider(
    String(repositoryBootstrap.provider || "local"),
  );
  setters.setProjectRepoBootstrapAutoOnSessionStart(
    Boolean(repositoryBootstrap.auto_bootstrap_on_session_start ?? false),
  );
  setters.setProjectRepoBootstrapWorkspaceSubdir(
    String(repositoryBootstrap.workspace_subdir || ""),
  );
  setters.setProjectRepoBootstrapDefaultRepoName(
    String(repositoryBootstrap.default_repo_name || ""),
  );
  setters.setProjectRepoBootstrapDefaultBranch(
    String(repositoryBootstrap.default_branch || "main"),
  );
  setters.setProjectRepoBootstrapRemoteVisibility(
    String(repositoryBootstrap.remote_visibility || "private"),
  );
  setters.setProjectRepoBootstrapGithubOwner(
    String(repositoryBootstrap.github_owner || ""),
  );
  setters.setProjectRepoBootstrapGithubOwnerType(
    String(repositoryBootstrap.github_owner_type || "org"),
  );
  setters.setProjectRepoBootstrapBitbucketProjectKey(
    String(repositoryBootstrap.bitbucket_project_key || ""),
  );
}

export function buildProjectRepositoryBootstrapPayload({
  projectRepoBootstrapEnabled,
  projectRepoBootstrapProvider,
  projectRepoBootstrapAutoOnSessionStart,
  projectRepoBootstrapWorkspaceSubdir,
  projectRepoBootstrapDefaultRepoName,
  projectRepoBootstrapDefaultBranch,
  projectRepoBootstrapRemoteVisibility,
  projectRepoBootstrapGithubOwner,
  projectRepoBootstrapGithubOwnerType,
  projectRepoBootstrapBitbucketProjectKey,
}: {
  projectRepoBootstrapEnabled: boolean;
  projectRepoBootstrapProvider: string;
  projectRepoBootstrapAutoOnSessionStart: boolean;
  projectRepoBootstrapWorkspaceSubdir: string;
  projectRepoBootstrapDefaultRepoName: string;
  projectRepoBootstrapDefaultBranch: string;
  projectRepoBootstrapRemoteVisibility: string;
  projectRepoBootstrapGithubOwner: string;
  projectRepoBootstrapGithubOwnerType: string;
  projectRepoBootstrapBitbucketProjectKey: string;
}) {
  const parsed: Record<string, unknown> = {
    enabled: projectRepoBootstrapEnabled,
    provider: projectRepoBootstrapProvider,
    auto_bootstrap_on_session_start: projectRepoBootstrapAutoOnSessionStart,
    default_branch: projectRepoBootstrapDefaultBranch.trim() || "main",
    remote_visibility: projectRepoBootstrapRemoteVisibility,
  };
  if (projectRepoBootstrapWorkspaceSubdir.trim()) {
    parsed.workspace_subdir = projectRepoBootstrapWorkspaceSubdir.trim();
  }
  if (projectRepoBootstrapDefaultRepoName.trim()) {
    parsed.default_repo_name = projectRepoBootstrapDefaultRepoName.trim();
  }
  if (projectRepoBootstrapProvider === "github") {
    if (projectRepoBootstrapGithubOwner.trim()) {
      parsed.github_owner = projectRepoBootstrapGithubOwner.trim();
    }
    parsed.github_owner_type = projectRepoBootstrapGithubOwnerType;
  }
  if (
    projectRepoBootstrapProvider === "bitbucket" &&
    projectRepoBootstrapBitbucketProjectKey.trim()
  ) {
    parsed.bitbucket_project_key =
      projectRepoBootstrapBitbucketProjectKey.trim();
  }
  return parsed;
}

export function parseJsonObjectDraft(draft: string, errorMessage: string) {
  try {
    return JSON.parse(draft || "{}") as Record<string, unknown>;
  } catch {
    throw new Error(errorMessage);
  }
}

export function applyUpdatedProjectQuality(
  setAdminProjects: SetProjectQualityList,
  updated: AdminProjectQuality,
) {
  setAdminProjects((prev) =>
    prev.map((project) => (project.id === updated.id ? updated : project)),
  );
}

export function applyUpdatedConfiguringProjectQuality(
  setConfiguringProjectQuality: SetProjectQualityCurrent,
  updated: AdminProjectQuality,
) {
  setConfiguringProjectQuality((prev) =>
    prev && prev.id === updated.id ? updated : prev,
  );
}
