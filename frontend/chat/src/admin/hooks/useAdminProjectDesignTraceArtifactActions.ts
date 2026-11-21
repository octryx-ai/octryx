// Project design artifact actions: save, delete, bootstrap and create tasks; trace link actions are composed in.
import type { FormEvent } from "react";
import type { AdminDesignArtifact } from "../types/projectQualityTypes.design";
import type { UseAdminProjectDesignTraceArgs } from "./useAdminProjectDesignTrace.types";
import { createProjectDesignTraceLinkActions } from "./projectDesignTraceLinkActions";
import {
  bootstrapProjectDesignArtifacts,
  createTaskFromDesignArtifact,
  deleteProjectDesignArtifact,
  saveProjectDesignArtifact,
} from "./projectDesignArtifactActions";

export function createProjectDesignTraceArtifactActions(
  args: UseAdminProjectDesignTraceArgs,
) {
  const { handleCreateProjectDesignTraceLink, handleDeleteProjectDesignTraceLink } =
    createProjectDesignTraceLinkActions(args);

  return {
    handleSaveProjectDesignArtifact: (event: FormEvent) => saveProjectDesignArtifact(args, event),
    handleDeleteProjectDesignArtifact: (artifact: AdminDesignArtifact) => deleteProjectDesignArtifact(args, artifact),
    handleBootstrapProjectDesignArtifacts: (includeOptional: boolean) =>
      bootstrapProjectDesignArtifacts(args, includeOptional),
    handleCreateProjectDesignTraceLink,
    handleCreateTaskFromDesignArtifact: (artifact: AdminDesignArtifact) => createTaskFromDesignArtifact(args, artifact),
    handleDeleteProjectDesignTraceLink,
  };
}
