import type { FormEvent } from "react";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type { UseAdminProjectQualityConfigActionsArgs } from "./useAdminProjectQualityConfigActions.types";
import {
  hydrateProjectRepositoryBootstrapDrafts,
  resetProjectRepositoryBootstrapDrafts,
} from "./useAdminProjectQualityConfigActions.helpers";
import {
  clearProjectRepositoryBootstrap,
  saveProjectQuality,
  saveProjectRepositoryBootstrap,
  saveProjectRuntimePolicy,
} from "./projectQualityConfigRequests";

export function useAdminProjectQualityConfigActions({
  args,
  resetProjectDesignArtifactForm,
  resetProjectDesignTraceForm,
  resetProjectCodeRepositoryForm,
}: UseAdminProjectQualityConfigActionsArgs) {
  const closeProjectQualityForm = () => {
    args.setConfiguringProjectQuality(null);
    args.setProjectQualityError(null);
    resetProjectRepositoryBootstrapDrafts(args);
    resetProjectDesignArtifactForm();
    resetProjectDesignTraceForm();
    resetProjectCodeRepositoryForm();
    args.setProjectRuntimePolicyDraft("{\n  \n}");
  };

  const handleOpenProjectQualityForm = (project: AdminProjectQuality) => {
    args.setConfiguringProjectQuality(project);
    args.setProjectQualityDraft(JSON.stringify(project.repo_code_quality || {}, null, 2));
    hydrateProjectRepositoryBootstrapDrafts(project, args);
    resetProjectDesignArtifactForm();
    resetProjectDesignTraceForm();
    args.setProjectDesignTraceArtifactId(String(project.design_artifacts?.[0]?.id || ""));
    resetProjectCodeRepositoryForm();
    args.setProjectRuntimePolicyDraft(JSON.stringify(project.runtime_policy || {}, null, 2));
    args.setProjectQualityError(null);
  };

  return {
    closeProjectQualityForm,
    handleOpenProjectQualityForm,
    handleSaveProjectQuality: (event: FormEvent) => saveProjectQuality(args, event, closeProjectQualityForm),
    handleSaveProjectRepositoryBootstrap: (event: FormEvent) => saveProjectRepositoryBootstrap(args, event),
    handleClearProjectRepositoryBootstrap: () => clearProjectRepositoryBootstrap(args),
    handleSaveProjectRuntimePolicy: (event: FormEvent) => saveProjectRuntimePolicy(args, event),
  };
}
