import type { FormEvent } from "react";

import type { AdminCodeRepository } from "../types/projectQualityTypes.code";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type { UseAdminProjectQualityCoreArgs } from "./useAdminProjectQualityCore.types";

type Args = UseAdminProjectQualityCoreArgs;
type RepoList = AdminCodeRepository[];

export function resetCodeRepositoryForm(args: Args) {
  args.setEditingProjectCodeRepositoryId(null);
  args.setProjectCodeRepositoryName("");
  args.setProjectCodeRepositoryDescription("");
  args.setProjectCodeRepositoryRoot("");
  args.setProjectCodeRepositoryProvider("local");
  args.setProjectCodeRepositoryRemoteUrl("");
  args.setProjectCodeRepositoryBranch("main");
  args.setProjectCodeRepositoryIndexBackend("auto");
  args.setProjectCodeRepositorySemanticBackend("auto");
  args.setProjectCodeRepositoryStructureBackend("auto");
  args.setProjectCodeRepositoryGraphBackend("disabled");
  args.setProjectCodeRepositoryActive(true);
}

export function fillCodeRepositoryForm(args: Args, repo: AdminCodeRepository) {
  args.setEditingProjectCodeRepositoryId(repo.id);
  args.setProjectCodeRepositoryName(repo.name || "");
  args.setProjectCodeRepositoryDescription(repo.description || "");
  args.setProjectCodeRepositoryRoot(repo.repo_root || "");
  args.setProjectCodeRepositoryProvider(repo.provider || "local");
  args.setProjectCodeRepositoryRemoteUrl(repo.remote_url || "");
  args.setProjectCodeRepositoryBranch(repo.default_branch || "main");
  args.setProjectCodeRepositoryIndexBackend(repo.index_backend || "auto");
  args.setProjectCodeRepositorySemanticBackend(repo.semantic_backend || "auto");
  args.setProjectCodeRepositoryStructureBackend(repo.structure_backend || "auto");
  args.setProjectCodeRepositoryGraphBackend(repo.graph_backend || "disabled");
  args.setProjectCodeRepositoryActive(Boolean(repo.is_active));
}

function codeRepositoryPayload(args: Args, projectId: AdminProjectQuality["id"]) {
  return {
    project_id: projectId,
    name: args.projectCodeRepositoryName.trim(),
    description: args.projectCodeRepositoryDescription.trim(),
    repo_root: args.projectCodeRepositoryRoot.trim(),
    provider: args.projectCodeRepositoryProvider,
    remote_url: args.projectCodeRepositoryRemoteUrl.trim() || null,
    default_branch: args.projectCodeRepositoryBranch.trim() || "main",
    index_backend: args.projectCodeRepositoryIndexBackend,
    semantic_backend: args.projectCodeRepositorySemanticBackend,
    structure_backend: args.projectCodeRepositoryStructureBackend,
    graph_backend: args.projectCodeRepositoryGraphBackend,
    config_json: {},
    is_active: args.projectCodeRepositoryActive,
  };
}

// Applies a change of the configured project's repository list to the project list and the open drawer.
function updateRepositories(args: Args, projectId: AdminProjectQuality["id"], change: (current: RepoList) => RepoList) {
  const applyToProject = (project: AdminProjectQuality): AdminProjectQuality => {
    if (project.id !== projectId) return project;
    return { ...project, code_repositories: change(project.code_repositories || []) };
  };
  args.setAdminProjects((prev) => prev.map(applyToProject));
  args.setConfiguringProjectQuality((prev) => (prev ? applyToProject(prev) : prev));
}

const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

export async function saveCodeRepository(args: Args, event: FormEvent) {
  event.preventDefault();
  const project = args.configuringProjectQuality;
  if (!project) return;
  args.setProjectCodeRepositoryLoading(true);
  args.setProjectQualityError(null);
  try {
    const payload = codeRepositoryPayload(args, project.id);
    if (!payload.name || !payload.repo_root) {
      throw new Error("Repository name and repo root are required");
    }
    const editingId = args.editingProjectCodeRepositoryId;
    const endpoint = editingId
      ? `/admin/chat/api/panel/code-repositories/${editingId}`
      : "/admin/chat/api/panel/code-repositories";
    const method = editingId ? "PUT" : "POST";
    const saved = await args.readJson<AdminCodeRepository>(endpoint, { method, body: JSON.stringify(payload) });
    updateRepositories(args, project.id, (current) =>
      method === "PUT" ? current.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...current],
    );
    resetCodeRepositoryForm(args);
  } catch (error) {
    args.setProjectQualityError(errorText(error, "Failed to save code repository"));
  } finally {
    args.setProjectCodeRepositoryLoading(false);
  }
}

export async function deleteCodeRepository(args: Args, repoId: string) {
  const project = args.configuringProjectQuality;
  if (!project) return;
  args.setProjectCodeRepositoryLoading(true);
  args.setProjectQualityError(null);
  try {
    await args.readJson(`/admin/chat/api/panel/code-repositories/${repoId}`, { method: "DELETE" });
    updateRepositories(args, project.id, (current) => current.filter((item) => item.id !== repoId));
    if (args.editingProjectCodeRepositoryId === repoId) {
      resetCodeRepositoryForm(args);
    }
  } catch (error) {
    args.setProjectQualityError(errorText(error, "Failed to delete code repository"));
  } finally {
    args.setProjectCodeRepositoryLoading(false);
  }
}

export async function runCodeIndex(args: Args, repoId: string) {
  const project = args.configuringProjectQuality;
  if (!project) return;
  args.setProjectCodeRepositoryRunningId(repoId);
  args.setProjectQualityError(null);
  try {
    const result = await args.readJson<{ repository: AdminCodeRepository }>(
      `/admin/chat/api/panel/code-repositories/${repoId}/index`,
      { method: "POST", body: JSON.stringify({ force: true }) },
    );
    const updatedRepo = result.repository;
    updateRepositories(args, project.id, (current) =>
      current.map((item) => (item.id === updatedRepo.id ? updatedRepo : item)),
    );
  } catch (error) {
    args.setProjectQualityError(errorText(error, "Failed to index repository"));
  } finally {
    args.setProjectCodeRepositoryRunningId(null);
  }
}
