// Workspace resources state: the loaded payload, the derived policy and mount drafts and the save actions.
import { useCallback, useEffect, useMemo, useState } from "react";

import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type {
  KnowledgeMountUpdate,
  ProjectResourcePayload,
  RepositoryPolicyUpdate,
  RepositoryResource,
} from "./projectResourcesTypes";

type KnowledgeAccessDraft = { mode: string; default_workspace_access: boolean };

const resourcesUrl = (projectId: string) =>
  `/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/resources`;

const failure = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

export function useProjectResourceState(projectId: string, readJson: ReadJsonFn) {
  const [payload, setPayload] = useState<ProjectResourcePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedMountProjectId, setSelectedMountProjectId] = useState("");
  const [mountLabel, setMountLabel] = useState("");

  const loadResources = useCallback(async () => {
    if (!projectId) {
      setPayload(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setPayload(await readJson<ProjectResourcePayload>(resourcesUrl(projectId)));
    } catch (loadError) {
      setError(failure(loadError, "Failed to load project resources."));
    } finally {
      setLoading(false);
    }
  }, [projectId, readJson]);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

  return {
    payload, setPayload, loading, saving, setSaving, error, setError, selectedMountProjectId,
    setSelectedMountProjectId, mountLabel, setMountLabel,
  };
}

export type ProjectResourceState = ReturnType<typeof useProjectResourceState>;

export function useResourceDrafts(payload: ProjectResourcePayload | null) {
  const repositoryPolicies = useMemo(
    () =>
      (payload?.repositories || []).map((repo) => ({
        repository_id: repo.id,
        operations: repo.operation_policy,
      })),
    [payload],
  );

  const knowledgeMounts = useMemo(
    () =>
      (payload?.knowledge_mounts || []).map((mount) => ({
        source_project_id: mount.source_project_id,
        mount_label: mount.mount_label,
      })),
    [payload],
  );
  const availableKnowledgeBases = useMemo(() => {
    const mountedIds = new Set(
      knowledgeMounts.map((mount) => mount.source_project_id),
    );
    return (payload?.available_knowledge_bases || []).filter(
      (option) => !mountedIds.has(option.project_id),
    );
  }, [knowledgeMounts, payload]);
  const knowledgeAccess = useMemo(
    () => ({
      mode: payload?.knowledge_access?.mode || "default",
      default_workspace_access:
        payload?.knowledge_access?.default_workspace_access !== false,
    }),
    [payload],
  );
  return { repositoryPolicies, knowledgeMounts, availableKnowledgeBases, knowledgeAccess };
}

type ResourceDrafts = ReturnType<typeof useResourceDrafts>;

/** Saves the given policies, mounts and access and stores the answer; on success the mount form is cleared. */
async function saveResources(
  projectId: string,
  readJson: ReadJsonFn,
  state: ProjectResourceState,
  next: { policies: RepositoryPolicyUpdate[]; mounts: KnowledgeMountUpdate[]; access: KnowledgeAccessDraft },
) {
  if (!projectId) return;
  state.setSaving(true);
  state.setError(null);
  try {
    const saved = await readJson<ProjectResourcePayload>(resourcesUrl(projectId), {
      method: "PUT",
      body: JSON.stringify({
        repository_policies: next.policies,
        knowledge_access: next.access,
        knowledge_mounts: next.mounts,
      }),
    });
    state.setPayload(saved);
    state.setSelectedMountProjectId("");
    state.setMountLabel("");
  } catch (saveError) {
    state.setError(failure(saveError, "Failed to save project resources."));
  } finally {
    state.setSaving(false);
  }
}

/** The view actions; each saves the full resource set with one part changed. */
export function resourceActions(projectId: string, readJson: ReadJsonFn, state: ProjectResourceState, drafts: ResourceDrafts) {
  const { repositoryPolicies, knowledgeMounts, knowledgeAccess } = drafts;
  const save = (policies = repositoryPolicies, mounts = knowledgeMounts, access: KnowledgeAccessDraft = knowledgeAccess) =>
    void saveResources(projectId, readJson, state, { policies, mounts, access });
  return {
    toggleRepositoryOperation: (repository: RepositoryResource, operationKey: string) =>
      save(repositoryPolicies.map((policy) =>
        policy.repository_id === repository.id
          ? { ...policy, operations: { ...policy.operations, [operationKey]: !repository.operation_policy[operationKey] } }
          : policy,
      )),
    addKnowledgeMount: () => {
      const { selectedMountProjectId, mountLabel } = state;
      if (!selectedMountProjectId) return;
      if (knowledgeMounts.some((mount) => mount.source_project_id === selectedMountProjectId)) return;
      save(repositoryPolicies, [...knowledgeMounts, { source_project_id: selectedMountProjectId, mount_label: mountLabel.trim() }]);
    },
    toggleWorkspaceKnowledgeAccess: () => {
      const enabled = !knowledgeAccess.default_workspace_access;
      save(repositoryPolicies, knowledgeMounts, { mode: enabled ? "default" : "limited", default_workspace_access: enabled });
    },
    removeKnowledgeMount: (sourceProjectId: string) =>
      save(repositoryPolicies, knowledgeMounts.filter((mount) => mount.source_project_id !== sourceProjectId)),
  };
}
