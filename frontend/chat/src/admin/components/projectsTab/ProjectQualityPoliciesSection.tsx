import type { ComponentProps } from "react";

import { ProjectRepoQualityForm } from "./policies/ProjectRepoQualityForm";
import { ProjectRepositoryBootstrapForm } from "./policies/ProjectRepositoryBootstrapForm";

type ProjectQualityPoliciesSectionProps = {
  ctx: Record<string, unknown>;
};

export function ProjectQualityPoliciesSection({
  ctx,
}: ProjectQualityPoliciesSectionProps) {
  const {
    handleSaveProjectQuality,
    projectQualityDraft,
    setProjectQualityDraft,
    projectQualityError,
    projectQualityLoading,
  } = ctx as Record<string, any>;

  return (
    <>
      <ProjectRepoQualityForm
        projectQualityDraft={projectQualityDraft}
        setProjectQualityDraft={setProjectQualityDraft}
        projectQualityError={projectQualityError}
        projectQualityLoading={projectQualityLoading}
        onSubmit={handleSaveProjectQuality}
      />
      <ProjectRepositoryBootstrapForm {...bootstrapFormProps(ctx as Record<string, any>)} />
    </>
  );
}

// The repository bootstrap form's values and setters, read from the Workspace settings context.
function bootstrapFormProps(c: Record<string, any>): ComponentProps<typeof ProjectRepositoryBootstrapForm> {
  return {
    projectRepoBootstrapProvider: c.projectRepoBootstrapProvider,
    setProjectRepoBootstrapProvider: c.setProjectRepoBootstrapProvider,
    projectRepoBootstrapDefaultBranch: c.projectRepoBootstrapDefaultBranch,
    setProjectRepoBootstrapDefaultBranch: c.setProjectRepoBootstrapDefaultBranch,
    projectRepoBootstrapDefaultRepoName: c.projectRepoBootstrapDefaultRepoName,
    setProjectRepoBootstrapDefaultRepoName: c.setProjectRepoBootstrapDefaultRepoName,
    projectRepoBootstrapWorkspaceSubdir: c.projectRepoBootstrapWorkspaceSubdir,
    setProjectRepoBootstrapWorkspaceSubdir: c.setProjectRepoBootstrapWorkspaceSubdir,
    projectRepoBootstrapRemoteVisibility: c.projectRepoBootstrapRemoteVisibility,
    setProjectRepoBootstrapRemoteVisibility: c.setProjectRepoBootstrapRemoteVisibility,
    projectRepoBootstrapGithubOwner: c.projectRepoBootstrapGithubOwner,
    setProjectRepoBootstrapGithubOwner: c.setProjectRepoBootstrapGithubOwner,
    projectRepoBootstrapGithubOwnerType: c.projectRepoBootstrapGithubOwnerType,
    setProjectRepoBootstrapGithubOwnerType: c.setProjectRepoBootstrapGithubOwnerType,
    projectRepoBootstrapBitbucketProjectKey: c.projectRepoBootstrapBitbucketProjectKey,
    setProjectRepoBootstrapBitbucketProjectKey: c.setProjectRepoBootstrapBitbucketProjectKey,
    projectRepoBootstrapEnabled: c.projectRepoBootstrapEnabled,
    setProjectRepoBootstrapEnabled: c.setProjectRepoBootstrapEnabled,
    projectRepoBootstrapAutoOnSessionStart: c.projectRepoBootstrapAutoOnSessionStart,
    setProjectRepoBootstrapAutoOnSessionStart: c.setProjectRepoBootstrapAutoOnSessionStart,
    projectQualityLoading: c.projectQualityLoading,
    onSubmit: c.handleSaveProjectRepositoryBootstrap,
    onUseImplicitLocalFallback: c.handleClearProjectRepositoryBootstrap,
  };
}
