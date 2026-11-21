import { useState } from "react";
import type { AdminProjectQuality } from "../types/projectQualityTypes";

// Project list, quality draft and repository bootstrap form.
function useProjectRepoBootstrapState() {
  const [adminProjects, setAdminProjects] = useState<AdminProjectQuality[]>([]);
  const [configuringProjectQuality, setConfiguringProjectQuality] =
    useState<AdminProjectQuality | null>(null);
  const [projectQualityDraft, setProjectQualityDraft] = useState("{\n  \n}");
  const [projectRepoBootstrapEnabled, setProjectRepoBootstrapEnabled] =
    useState(true);
  const [projectRepoBootstrapProvider, setProjectRepoBootstrapProvider] =
    useState("local");
  const [
    projectRepoBootstrapAutoOnSessionStart,
    setProjectRepoBootstrapAutoOnSessionStart,
  ] = useState(false);
  const [
    projectRepoBootstrapWorkspaceSubdir,
    setProjectRepoBootstrapWorkspaceSubdir,
  ] = useState("");
  const [
    projectRepoBootstrapDefaultRepoName,
    setProjectRepoBootstrapDefaultRepoName,
  ] = useState("");
  const [
    projectRepoBootstrapDefaultBranch,
    setProjectRepoBootstrapDefaultBranch,
  ] = useState("main");
  const [
    projectRepoBootstrapRemoteVisibility,
    setProjectRepoBootstrapRemoteVisibility,
  ] = useState("private");
  const [projectRepoBootstrapGithubOwner, setProjectRepoBootstrapGithubOwner] =
    useState("");
  const [
    projectRepoBootstrapGithubOwnerType,
    setProjectRepoBootstrapGithubOwnerType,
  ] = useState("org");
  const [
    projectRepoBootstrapBitbucketProjectKey,
    setProjectRepoBootstrapBitbucketProjectKey,
  ] = useState("");
  return {
    adminProjects, setAdminProjects,
    configuringProjectQuality, setConfiguringProjectQuality,
    projectQualityDraft, setProjectQualityDraft,
    projectRepoBootstrapEnabled, setProjectRepoBootstrapEnabled,
    projectRepoBootstrapProvider, setProjectRepoBootstrapProvider,
    projectRepoBootstrapAutoOnSessionStart, setProjectRepoBootstrapAutoOnSessionStart,
    projectRepoBootstrapWorkspaceSubdir, setProjectRepoBootstrapWorkspaceSubdir,
    projectRepoBootstrapDefaultRepoName, setProjectRepoBootstrapDefaultRepoName,
    projectRepoBootstrapDefaultBranch, setProjectRepoBootstrapDefaultBranch,
    projectRepoBootstrapRemoteVisibility, setProjectRepoBootstrapRemoteVisibility,
    projectRepoBootstrapGithubOwner, setProjectRepoBootstrapGithubOwner,
    projectRepoBootstrapGithubOwnerType, setProjectRepoBootstrapGithubOwnerType,
    projectRepoBootstrapBitbucketProjectKey, setProjectRepoBootstrapBitbucketProjectKey,
  };
}

// Code repository form.
function useProjectCodeRepositoryState() {
  const [editingProjectCodeRepositoryId, setEditingProjectCodeRepositoryId] =
    useState<string | null>(null);
  const [projectCodeRepositoryName, setProjectCodeRepositoryName] =
    useState("");
  const [
    projectCodeRepositoryDescription,
    setProjectCodeRepositoryDescription,
  ] = useState("");
  const [projectCodeRepositoryRoot, setProjectCodeRepositoryRoot] =
    useState("");
  const [projectCodeRepositoryProvider, setProjectCodeRepositoryProvider] =
    useState("local");
  const [projectCodeRepositoryRemoteUrl, setProjectCodeRepositoryRemoteUrl] =
    useState("");
  const [projectCodeRepositoryBranch, setProjectCodeRepositoryBranch] =
    useState("main");
  const [
    projectCodeRepositoryIndexBackend,
    setProjectCodeRepositoryIndexBackend,
  ] = useState("auto");
  const [
    projectCodeRepositorySemanticBackend,
    setProjectCodeRepositorySemanticBackend,
  ] = useState("auto");
  const [
    projectCodeRepositoryStructureBackend,
    setProjectCodeRepositoryStructureBackend,
  ] = useState("auto");
  const [
    projectCodeRepositoryGraphBackend,
    setProjectCodeRepositoryGraphBackend,
  ] = useState("disabled");
  const [projectCodeRepositoryActive, setProjectCodeRepositoryActive] =
    useState(true);
  return {
    editingProjectCodeRepositoryId, setEditingProjectCodeRepositoryId,
    projectCodeRepositoryName, setProjectCodeRepositoryName,
    projectCodeRepositoryDescription, setProjectCodeRepositoryDescription,
    projectCodeRepositoryRoot, setProjectCodeRepositoryRoot,
    projectCodeRepositoryProvider, setProjectCodeRepositoryProvider,
    projectCodeRepositoryRemoteUrl, setProjectCodeRepositoryRemoteUrl,
    projectCodeRepositoryBranch, setProjectCodeRepositoryBranch,
    projectCodeRepositoryIndexBackend, setProjectCodeRepositoryIndexBackend,
    projectCodeRepositorySemanticBackend, setProjectCodeRepositorySemanticBackend,
    projectCodeRepositoryStructureBackend, setProjectCodeRepositoryStructureBackend,
    projectCodeRepositoryGraphBackend, setProjectCodeRepositoryGraphBackend,
    projectCodeRepositoryActive, setProjectCodeRepositoryActive,
  };
}

// Code repository request status, runtime policy draft and quality request status.
function useProjectQualityRequestState() {
  const [projectCodeRepositoryLoading, setProjectCodeRepositoryLoading] =
    useState(false);
  const [projectCodeRepositoryRunningId, setProjectCodeRepositoryRunningId] =
    useState<string | null>(null);
  const [projectRuntimePolicyDraft, setProjectRuntimePolicyDraft] =
    useState("{\n  \n}");
  const [projectQualityLoading, setProjectQualityLoading] = useState(false);
  const [projectQualityError, setProjectQualityError] = useState<string | null>(
    null,
  );
  return {
    projectCodeRepositoryLoading, setProjectCodeRepositoryLoading,
    projectCodeRepositoryRunningId, setProjectCodeRepositoryRunningId,
    projectRuntimePolicyDraft, setProjectRuntimePolicyDraft,
    projectQualityLoading, setProjectQualityLoading,
    projectQualityError, setProjectQualityError,
  };
}

// Design artifact form.
function useProjectDesignArtifactState() {
  const [editingProjectDesignArtifactId, setEditingProjectDesignArtifactId] =
    useState<string | null>(null);
  const [projectDesignArtifactKind, setProjectDesignArtifactKind] =
    useState("outcome_brief");
  const [projectDesignArtifactTitle, setProjectDesignArtifactTitle] =
    useState("");
  const [projectDesignArtifactStatus, setProjectDesignArtifactStatus] =
    useState("draft");
  const [projectDesignArtifactSummary, setProjectDesignArtifactSummary] =
    useState("");
  const [projectDesignArtifactContent, setProjectDesignArtifactContent] =
    useState("");
  const [
    projectDesignArtifactLinkedRepositoryIds,
    setProjectDesignArtifactLinkedRepositoryIds,
  ] = useState<string[]>([]);
  const [
    projectDesignArtifactDependsOnArtifactIds,
    setProjectDesignArtifactDependsOnArtifactIds,
  ] = useState<string[]>([]);
  const [projectDesignArtifactRequired, setProjectDesignArtifactRequired] =
    useState(false);
  const [projectDesignArtifactOrder, setProjectDesignArtifactOrder] =
    useState("100");
  return {
    editingProjectDesignArtifactId, setEditingProjectDesignArtifactId,
    projectDesignArtifactKind, setProjectDesignArtifactKind,
    projectDesignArtifactTitle, setProjectDesignArtifactTitle,
    projectDesignArtifactStatus, setProjectDesignArtifactStatus,
    projectDesignArtifactSummary, setProjectDesignArtifactSummary,
    projectDesignArtifactContent, setProjectDesignArtifactContent,
    projectDesignArtifactLinkedRepositoryIds, setProjectDesignArtifactLinkedRepositoryIds,
    projectDesignArtifactDependsOnArtifactIds, setProjectDesignArtifactDependsOnArtifactIds,
    projectDesignArtifactRequired, setProjectDesignArtifactRequired,
    projectDesignArtifactOrder, setProjectDesignArtifactOrder,
  };
}

// Design trace form.
function useProjectDesignTraceState() {
  const [projectDesignTraceArtifactId, setProjectDesignTraceArtifactId] =
    useState("");
  const [projectDesignTraceTargetType, setProjectDesignTraceTargetType] =
    useState("task");
  const [projectDesignTraceTargetId, setProjectDesignTraceTargetId] =
    useState("");
  const [projectDesignTraceTitle, setProjectDesignTraceTitle] = useState("");
  const [projectDesignTraceStatus, setProjectDesignTraceStatus] =
    useState("active");
  const [projectDesignTraceUrl, setProjectDesignTraceUrl] = useState("");
  return {
    projectDesignTraceArtifactId, setProjectDesignTraceArtifactId,
    projectDesignTraceTargetType, setProjectDesignTraceTargetType,
    projectDesignTraceTargetId, setProjectDesignTraceTargetId,
    projectDesignTraceTitle, setProjectDesignTraceTitle,
    projectDesignTraceStatus, setProjectDesignTraceStatus,
    projectDesignTraceUrl, setProjectDesignTraceUrl,
  };
}

export function useAdminProjectState() {
  return {
    ...useProjectRepoBootstrapState(),
    ...useProjectCodeRepositoryState(),
    ...useProjectQualityRequestState(),
    ...useProjectDesignArtifactState(),
    ...useProjectDesignTraceState(),
  };
}
