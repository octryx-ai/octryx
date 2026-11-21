// Project design trace link actions: create and delete links between design artifacts and delivery targets.
import type { FormEvent } from "react";
import type { AdminDesignTraceLink, AdminDesignTraceability } from "../types/projectQualityTypes.design";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type { UseAdminProjectDesignTraceArgs } from "./useAdminProjectDesignTrace.types";

export function createProjectDesignTraceLinkActions(
  args: UseAdminProjectDesignTraceArgs,
) {
  const {
    readJson,
    configuringProjectQuality,
    setAdminProjects,
    setConfiguringProjectQuality,
    setProjectQualityLoading,
    setProjectQualityError,
    projectDesignTraceArtifactId,
    projectDesignTraceTargetType,
    projectDesignTraceTargetId,
    projectDesignTraceTitle,
    projectDesignTraceStatus,
    projectDesignTraceUrl,
    resetProjectDesignTraceForm,
  } = args;

  const handleCreateProjectDesignTraceLink = async (event: FormEvent) => {
    event.preventDefault();
    if (!configuringProjectQuality) return;
    setProjectQualityLoading(true);
    setProjectQualityError(null);
    try {
      if (!projectDesignTraceArtifactId) {
        throw new Error("Select a design artifact");
      }
      const title = projectDesignTraceTitle.trim();
      if (!title) {
        throw new Error("Trace title is required");
      }
      const payload = {
        artifact_id: projectDesignTraceArtifactId,
        target_type: projectDesignTraceTargetType,
        target_id: projectDesignTraceTargetId.trim() || null,
        title,
        status: projectDesignTraceStatus,
        url: projectDesignTraceUrl.trim() || null,
        metadata_json: {},
      };
      await readJson<AdminDesignTraceLink>(
        `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-trace-links`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      const traceability = await readJson<AdminDesignTraceability>(
        `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-traceability`,
      );
      const applyToProject = (
        project: AdminProjectQuality,
      ): AdminProjectQuality =>
        project.id === configuringProjectQuality.id
          ? { ...project, design_traceability: traceability }
          : project;
      setAdminProjects((prev) => prev.map(applyToProject));
      setConfiguringProjectQuality((prev) =>
        prev ? applyToProject(prev) : prev,
      );
      resetProjectDesignTraceForm();
    } catch (error) {
      setProjectQualityError(
        error instanceof Error
          ? error.message
          : "Failed to create design trace link",
      );
    } finally {
      setProjectQualityLoading(false);
    }
  };

  const handleDeleteProjectDesignTraceLink = async (
    link: AdminDesignTraceLink,
  ) => {
    if (!configuringProjectQuality) return;
    if (!window.confirm(`Delete trace link "${link.title}"?`)) return;
    setProjectQualityLoading(true);
    setProjectQualityError(null);
    try {
      await readJson(
        `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-trace-links/${link.id}`,
        { method: "DELETE" },
      );
      const traceability = await readJson<AdminDesignTraceability>(
        `/admin/chat/api/panel/projects/${configuringProjectQuality.id}/design-traceability`,
      );
      const applyToProject = (
        project: AdminProjectQuality,
      ): AdminProjectQuality =>
        project.id === configuringProjectQuality.id
          ? { ...project, design_traceability: traceability }
          : project;
      setAdminProjects((prev) => prev.map(applyToProject));
      setConfiguringProjectQuality((prev) =>
        prev ? applyToProject(prev) : prev,
      );
    } catch (error) {
      setProjectQualityError(
        error instanceof Error
          ? error.message
          : "Failed to delete design trace link",
      );
    } finally {
      setProjectQualityLoading(false);
    }
  };

  return { handleCreateProjectDesignTraceLink, handleDeleteProjectDesignTraceLink };
}
