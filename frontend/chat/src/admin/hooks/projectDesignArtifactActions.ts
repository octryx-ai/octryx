// Project design artifact requests: save, delete, bootstrap and create-task, each updating the project lists.
import type { FormEvent } from "react";
import type { AdminDesignArtifact, AdminDesignReadiness, AdminDesignTraceability } from "../types/projectQualityTypes.design";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type { UseAdminProjectDesignTraceArgs } from "./useAdminProjectDesignTrace.types";
import { TASK_DEFINITION_BINDING } from "../components/automation/actionDispatchBinding";
import { withProjectQualityLoading } from "./projectQualityLoading";

type Args = UseAdminProjectDesignTraceArgs;
type Project = AdminProjectQuality;

const EMPTY_READINESS = (): NonNullable<Project["design_readiness"]> => ({
  required_total: 0,
  approved_required_total: 0,
  required_approval_rate: 0,
  readiness_score: 0,
  missing_required_kinds: [],
  pending_required_kinds: [],
  approved_required_kinds: [],
  blockers: [],
  artifact_coverage: {},
  repository_traceability: {
    total_repositories: 0,
    linked_repositories: 0,
    linked_repository_ids: [],
    coverage_rate: 0,
  },
});

function applyToProjects(a: Args, applyToProject: (project: Project) => Project) {
  a.setAdminProjects((prev) => prev.map(applyToProject));
  a.setConfiguringProjectQuality((prev) => (prev ? applyToProject(prev) : prev));
}

async function refreshReadiness(a: Args, projectId: Project["id"]) {
  const readiness = await a.readJson<AdminDesignReadiness>(
    `/admin/chat/api/panel/projects/${projectId}/design-readiness`,
  );
  a.setAdminProjects((prev) =>
    prev.map((project) => (project.id === projectId ? { ...project, design_readiness: readiness } : project)),
  );
  a.setConfiguringProjectQuality((prev) => (prev ? { ...prev, design_readiness: readiness } : prev));
}

function artifactPayload(a: Args, title: string) {
  return {
    artifact_kind: a.projectDesignArtifactKind,
    title,
    status: a.projectDesignArtifactStatus,
    summary: a.projectDesignArtifactSummary.trim(),
    content_markdown: a.projectDesignArtifactContent,
    linked_repository_ids: a.projectDesignArtifactLinkedRepositoryIds,
    depends_on_artifact_ids: a.projectDesignArtifactDependsOnArtifactIds,
    is_required: a.projectDesignArtifactRequired,
    order_index: Number(a.projectDesignArtifactOrder || 100),
    metadata_json: {},
  };
}

// Puts the saved artifact into the project's list (replace on PUT, append on POST), ordered by index then title.
function withSavedArtifact(project: Project, saved: AdminDesignArtifact, method: string): Project {
  const current = project.design_artifacts || [];
  const next = method === "PUT"
    ? current.map((item) => (item.id === saved.id ? saved : item))
    : [...current, saved];
  next.sort(
    (left, right) =>
      (left.order_index || 100) - (right.order_index || 100) ||
      (left.title || "").localeCompare(right.title || ""),
  );
  return { ...project, design_artifacts: next, design_readiness: project.design_readiness || EMPTY_READINESS() };
}

export async function saveProjectDesignArtifact(a: Args, event: FormEvent) {
  event.preventDefault();
  const project = a.configuringProjectQuality;
  if (!project) return;
  await withProjectQualityLoading(a, "Failed to save design artifact", async () => {
    const title = a.projectDesignArtifactTitle.trim();
    if (!title) {
      throw new Error("Artifact title is required");
    }
    const payload = artifactPayload(a, title);
    const editingId = a.editingProjectDesignArtifactId;
    const endpoint = editingId
      ? `/admin/chat/api/panel/projects/${project.id}/design-artifacts/${editingId}`
      : `/admin/chat/api/panel/projects/${project.id}/design-artifacts`;
    const method = editingId ? "PUT" : "POST";
    const saved = await a.readJson<AdminDesignArtifact>(endpoint, { method, body: JSON.stringify(payload) });
    applyToProjects(a, (item) => (item.id !== project.id ? item : withSavedArtifact(item, saved, method)));
    await refreshReadiness(a, project.id);
    a.resetProjectDesignArtifactForm();
  });
}

export async function deleteProjectDesignArtifact(a: Args, artifact: AdminDesignArtifact) {
  const project = a.configuringProjectQuality;
  if (!project) return;
  if (!window.confirm(`Delete design artifact "${artifact.title}"?`)) return;
  await withProjectQualityLoading(a, "Failed to delete design artifact", async () => {
    await a.readJson(
      `/admin/chat/api/panel/projects/${project.id}/design-artifacts/${artifact.id}`,
      { method: "DELETE" },
    );
    applyToProjects(a, (item) => (item.id !== project.id ? item : {
      ...item,
      design_artifacts: (item.design_artifacts || []).filter((entry) => entry.id !== artifact.id),
    }));
    await refreshReadiness(a, project.id);
    if (a.editingProjectDesignArtifactId === artifact.id) {
      a.resetProjectDesignArtifactForm();
    }
  });
}

export async function bootstrapProjectDesignArtifacts(a: Args, includeOptional: boolean) {
  const project = a.configuringProjectQuality;
  if (!project) return;
  await withProjectQualityLoading(a, "Failed to seed design artifacts", async () => {
    const result = await a.readJson<{ items: AdminDesignArtifact[] }>(
      `/admin/chat/api/panel/projects/${project.id}/design-artifacts/bootstrap`,
      { method: "POST", body: JSON.stringify({ include_optional: includeOptional }) },
    );
    const readiness = await a.readJson<AdminDesignReadiness>(
      `/admin/chat/api/panel/projects/${project.id}/design-readiness`,
    );
    applyToProjects(a, (item) => (item.id === project.id
      ? { ...item, design_artifacts: result.items || [], design_readiness: readiness }
      : item));
    a.resetProjectDesignArtifactForm();
  });
}

export async function createTaskFromDesignArtifact(a: Args, artifact: AdminDesignArtifact) {
  const project = a.configuringProjectQuality;
  if (!project) return;
  await withProjectQualityLoading(a, "Failed to create task from design artifact", async () => {
    await a.readJson(
      `/admin/chat/api/panel/projects/${project.id}/design-artifacts/${artifact.id}/create-task`,
      {
        method: "POST",
        // The created Action runs its own definition until an admin binds it to an agent or workflow.
        body: JSON.stringify({
          name: artifact.title,
          description: artifact.summary || "",
          agent_type: "coding",
          dispatch_binding: TASK_DEFINITION_BINDING,
        }),
      },
    );
    const traceability = await a.readJson<AdminDesignTraceability>(
      `/admin/chat/api/panel/projects/${project.id}/design-traceability`,
    );
    applyToProjects(a, (item) => (item.id === project.id ? { ...item, design_traceability: traceability } : item));
  });
}
