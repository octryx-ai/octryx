// Project quality config requests: repo quality, repository bootstrap (save/clear) and runtime policy.
import type { FormEvent } from "react";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type { UseAdminProjectQualityCoreArgs } from "./useAdminProjectQualityCore.types";
import {
  applyUpdatedConfiguringProjectQuality,
  applyUpdatedProjectQuality,
  buildProjectRepositoryBootstrapPayload,
  parseJsonObjectDraft,
  resetProjectRepositoryBootstrapDrafts,
} from "./useAdminProjectQualityConfigActions.helpers";
import { withProjectQualityLoading } from "./projectQualityLoading";

type Args = UseAdminProjectQualityCoreArgs;

function putProjectConfig(a: Args, projectId: AdminProjectQuality["id"], path: string, body: unknown) {
  return a.readJson<AdminProjectQuality>(
    `/admin/chat/api/panel/projects/${projectId}/${path}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}

export async function saveProjectQuality(a: Args, event: FormEvent, closeForm: () => void) {
  event.preventDefault();
  const project = a.configuringProjectQuality;
  if (!project) return;
  await withProjectQualityLoading(a, "Failed to save project repo quality config", async () => {
    const parsed = parseJsonObjectDraft(a.projectQualityDraft, "Repo quality config must be valid JSON");
    const updated = await putProjectConfig(a, project.id, "repo-quality", { repo_code_quality: parsed });
    applyUpdatedProjectQuality(a.setAdminProjects, updated);
    closeForm();
  });
}

export async function saveProjectRepositoryBootstrap(a: Args, event: FormEvent) {
  event.preventDefault();
  const project = a.configuringProjectQuality;
  if (!project) return;
  await withProjectQualityLoading(a, "Failed to save project repository bootstrap config", async () => {
    const parsed = buildProjectRepositoryBootstrapPayload(a);
    const updated = await putProjectConfig(a, project.id, "repository-bootstrap", { repository_bootstrap: parsed });
    applyUpdatedProjectQuality(a.setAdminProjects, updated);
    applyUpdatedConfiguringProjectQuality(a.setConfiguringProjectQuality, updated);
  });
}

export async function clearProjectRepositoryBootstrap(a: Args) {
  const project = a.configuringProjectQuality;
  if (!project) return;
  await withProjectQualityLoading(a, "Failed to clear project repository bootstrap config", async () => {
    const updated = await putProjectConfig(a, project.id, "repository-bootstrap", { repository_bootstrap: {} });
    applyUpdatedProjectQuality(a.setAdminProjects, updated);
    applyUpdatedConfiguringProjectQuality(a.setConfiguringProjectQuality, updated);
    resetProjectRepositoryBootstrapDrafts(a);
  });
}

export async function saveProjectRuntimePolicy(a: Args, event: FormEvent) {
  event.preventDefault();
  const project = a.configuringProjectQuality;
  if (!project) return;
  await withProjectQualityLoading(a, "Failed to save project runtime policy", async () => {
    const parsed = parseJsonObjectDraft(a.projectRuntimePolicyDraft, "Runtime policy config must be valid JSON");
    const updated = await putProjectConfig(a, project.id, "runtime-policy", { runtime_policy: parsed });
    applyUpdatedProjectQuality(a.setAdminProjects, updated);
    a.setConfiguringProjectQuality(updated);
    a.setProjectRuntimePolicyDraft(JSON.stringify(updated.runtime_policy || {}, null, 2));
  });
}
