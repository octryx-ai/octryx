import type { UseAdminProjectQualityCoreArgs } from "./useAdminProjectQualityCore.types";

export type UseAdminProjectQualityConfigActionsArgs = {
  args: UseAdminProjectQualityCoreArgs;
  resetProjectDesignArtifactForm: () => void;
  resetProjectDesignTraceForm: () => void;
  resetProjectCodeRepositoryForm: () => void;
};
