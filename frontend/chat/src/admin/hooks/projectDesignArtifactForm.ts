import type { AdminDesignArtifact } from "../types/projectQualityTypes.design";
import type { UseAdminProjectQualityCoreArgs } from "./useAdminProjectQualityCore.types";

// Resets and fills the design artifact and design trace forms of the project quality drawer.
export function createProjectDesignFormActions(args: UseAdminProjectQualityCoreArgs) {
  const resetProjectDesignArtifactForm = () => {
    args.setEditingProjectDesignArtifactId(null);
    args.setProjectDesignArtifactKind("outcome_brief");
    args.setProjectDesignArtifactTitle("");
    args.setProjectDesignArtifactStatus("draft");
    args.setProjectDesignArtifactSummary("");
    args.setProjectDesignArtifactContent("");
    args.setProjectDesignArtifactLinkedRepositoryIds([]);
    args.setProjectDesignArtifactDependsOnArtifactIds([]);
    args.setProjectDesignArtifactRequired(false);
    args.setProjectDesignArtifactOrder("100");
  };

  const resetProjectDesignTraceForm = () => {
    args.setProjectDesignTraceArtifactId("");
    args.setProjectDesignTraceTargetType("task");
    args.setProjectDesignTraceTargetId("");
    args.setProjectDesignTraceTitle("");
    args.setProjectDesignTraceStatus("active");
    args.setProjectDesignTraceUrl("");
  };

  const handleEditProjectDesignArtifact = (
    artifact?: AdminDesignArtifact | null,
  ) => {
    if (!artifact) {
      resetProjectDesignArtifactForm();
      return;
    }
    args.setEditingProjectDesignArtifactId(artifact.id);
    args.setProjectDesignArtifactKind(artifact.artifact_kind || "outcome_brief");
    args.setProjectDesignArtifactTitle(artifact.title || "");
    args.setProjectDesignArtifactStatus(artifact.status || "draft");
    args.setProjectDesignArtifactSummary(artifact.summary || "");
    args.setProjectDesignArtifactContent(artifact.content_markdown || "");
    args.setProjectDesignArtifactLinkedRepositoryIds(
      artifact.linked_repository_ids || [],
    );
    args.setProjectDesignArtifactDependsOnArtifactIds(
      artifact.depends_on_artifact_ids || [],
    );
    args.setProjectDesignArtifactRequired(Boolean(artifact.is_required));
    args.setProjectDesignArtifactOrder(String(artifact.order_index || 100));
  };

  return { resetProjectDesignArtifactForm, resetProjectDesignTraceForm, handleEditProjectDesignArtifact };
}
