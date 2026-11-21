import type { FormEvent } from "react";

import type { AdminCodeRepository } from "../types/projectQualityTypes.code";
import {
  deleteCodeRepository,
  fillCodeRepositoryForm,
  resetCodeRepositoryForm,
  runCodeIndex,
  saveCodeRepository,
} from "./projectCodeRepositoryActions";
import type { UseAdminProjectQualityCoreArgs } from "./useAdminProjectQualityCore.types";

export function useAdminProjectQualityCodeRepositories(
  args: UseAdminProjectQualityCoreArgs,
) {
  const resetProjectCodeRepositoryForm = () => resetCodeRepositoryForm(args);

  const handleEditProjectCodeRepository = (
    repo?: AdminCodeRepository | null,
  ) => {
    if (!repo) {
      resetProjectCodeRepositoryForm();
      return;
    }
    fillCodeRepositoryForm(args, repo);
  };

  const handleSaveProjectCodeRepository = (event: FormEvent) => saveCodeRepository(args, event);
  const handleDeleteProjectCodeRepository = (repoId: string) => deleteCodeRepository(args, repoId);
  const handleRunProjectCodeIndex = (repoId: string) => runCodeIndex(args, repoId);

  return {
    resetProjectCodeRepositoryForm,
    handleEditProjectCodeRepository,
    handleSaveProjectCodeRepository,
    handleDeleteProjectCodeRepository,
    handleRunProjectCodeIndex,
  };
}
