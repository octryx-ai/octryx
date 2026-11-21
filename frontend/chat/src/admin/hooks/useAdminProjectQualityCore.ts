import { createProjectDesignFormActions } from "./projectDesignArtifactForm";
import { useAdminProjectQualityCodeRepositories } from "./useAdminProjectQualityCodeRepositories";
import { useAdminProjectQualityConfigActions } from "./useAdminProjectQualityConfigActions";
import type { UseAdminProjectQualityCoreArgs } from "./useAdminProjectQualityCore.types";

export function useAdminProjectQualityCore(qualityArgs: UseAdminProjectQualityCoreArgs) {
  const {
    resetProjectCodeRepositoryForm,
    handleEditProjectCodeRepository,
    handleSaveProjectCodeRepository,
    handleDeleteProjectCodeRepository,
    handleRunProjectCodeIndex,
  } = useAdminProjectQualityCodeRepositories(qualityArgs);

  const {
    resetProjectDesignArtifactForm,
    resetProjectDesignTraceForm,
    handleEditProjectDesignArtifact,
  } = createProjectDesignFormActions(qualityArgs);

  const {
    closeProjectQualityForm,
    handleOpenProjectQualityForm,
    handleSaveProjectQuality,
    handleSaveProjectRepositoryBootstrap,
    handleClearProjectRepositoryBootstrap,
    handleSaveProjectRuntimePolicy,
  } = useAdminProjectQualityConfigActions({
    args: qualityArgs,
    resetProjectDesignArtifactForm,
    resetProjectDesignTraceForm,
    resetProjectCodeRepositoryForm,
  });

  return {
    closeProjectQualityForm,
    handleClearProjectRepositoryBootstrap,
    handleDeleteProjectCodeRepository,
    handleEditProjectCodeRepository,
    handleEditProjectDesignArtifact,
    handleOpenProjectQualityForm,
    handleRunProjectCodeIndex,
    handleSaveProjectCodeRepository,
    handleSaveProjectQuality,
    handleSaveProjectRepositoryBootstrap,
    handleSaveProjectRuntimePolicy,
    resetProjectCodeRepositoryForm,
    resetProjectDesignArtifactForm,
    resetProjectDesignTraceForm,
  };
}
