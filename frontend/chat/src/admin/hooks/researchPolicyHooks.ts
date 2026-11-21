// Research policy sub-hooks: derived selection, loading effects and the saving create/publish actions.
import { useCallback, useEffect, useMemo } from "react";
import { readJson } from "../utils/adminPanelHelpers";
import type {
  ResearchPolicyProfile,
  ResearchPolicyVersion,
  WorkspaceResearchPolicyPayload,
} from "../types/researchPolicyTypes";
import { formatSpec, parseSpecDraft } from "./researchPolicyDrafts";
import type { ResearchPolicyState } from "./useAdminResearchPolicies";
import {
  fetchResearchPolicies,
  postResearchPolicyProfile,
  runResearchPolicySaving,
} from "./researchPolicyRequests";

type RunSaving = (action: () => Promise<void>, success: string) => Promise<boolean>;

export function useResearchPolicySelection({ payload, selectedProfileId, selectedVersionId }: ResearchPolicyState) {
  const selectedProfile = useMemo(
    () =>
      payload.profiles.find((profile) => profile.id === selectedProfileId) ||
      payload.profiles[0] ||
      null,
    [payload.profiles, selectedProfileId],
  );
  const selectedVersion = useMemo(() => {
    if (!selectedProfile) return null;
    return (
      selectedProfile.versions.find((version) => version.id === selectedVersionId) ||
      selectedProfile.versions[0] ||
      null
    );
  }, [selectedProfile, selectedVersionId]);
  const publishedVersions = useMemo(
    () =>
      payload.profiles.flatMap((profile) =>
        profile.versions
          .filter((version) => version.status === "published" && version.diagnostics.status === "valid")
          .map((version) => ({ profile, version })),
      ),
    [payload.profiles],
  );
  return { selectedProfile, selectedVersion, publishedVersions };
}

export function useResearchPolicyLoading(state: ResearchPolicyState, selectedVersion: ResearchPolicyVersion | null) {
  const { selectedProfileId, selectedVersionId, selectedProjectId, setPayload, setLoading, setError } = state;
  const { setSelectedProfileId, setSelectedVersionId, setSpecDraft, setWorkspacePolicy } = state;
  const loadPolicies = useCallback(
    () => fetchResearchPolicies(
      { setPayload, setLoading, setError, setSelectedProfileId, setSelectedVersionId, setSpecDraft },
      selectedProfileId,
      selectedVersionId,
    ),
    [selectedProfileId, selectedVersionId, setPayload, setLoading, setError, setSelectedProfileId,
      setSelectedVersionId, setSpecDraft],
  );

  const loadWorkspacePolicy = useCallback(
    async (projectId = selectedProjectId) => {
      if (!projectId) {
        setWorkspacePolicy(null);
        return;
      }
      const next = await readJson<WorkspaceResearchPolicyPayload>(
        `/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/research-policy`,
      );
      setWorkspacePolicy(next);
    },
    [selectedProjectId, setWorkspacePolicy],
  );

  useEffect(() => {
    void loadPolicies();
  }, [loadPolicies]);

  useEffect(() => {
    if (!selectedVersion) return;
    setSpecDraft(formatSpec(selectedVersion.spec));
  }, [selectedVersion, setSpecDraft]);

  useEffect(() => {
    if (!selectedProjectId) {
      setWorkspacePolicy(null);
      return;
    }
    loadWorkspacePolicy().catch((workspaceError) => {
      setWorkspacePolicy(null);
      setError(workspaceError instanceof Error ? workspaceError.message : "Failed to load workspace policy.");
    });
  }, [loadWorkspacePolicy, selectedProjectId, setWorkspacePolicy, setError]);
  return loadPolicies;
}

export function useResearchPolicyCreateProfile(state: ResearchPolicyState, loadPolicies: () => Promise<void>) {
  const { setSaving, setError, setNotice, setSelectedProfileId, setSelectedVersionId } = state;
  const { createAsPublished, newProfileKey, newProfileName, newVersionNotes, specDraft } = state;
  const { setNewProfileKey, setNewProfileName, setNewVersionNotes } = state;
  const runSavingAction = useCallback<RunSaving>(
    (action, success) => runResearchPolicySaving({ setSaving, setError, setNotice }, action, success),
    [setSaving, setError, setNotice],
  );

  const createProfile = useCallback(
    () =>
      runSavingAction(async () => {
        const created = await postResearchPolicyProfile({
          newProfileKey, newProfileName, newVersionNotes, specDraft, createAsPublished,
        });
        setSelectedProfileId(created.id);
        setSelectedVersionId(created.versions[0]?.id || "");
        setNewProfileKey("");
        setNewProfileName("");
        setNewVersionNotes("");
        await loadPolicies();
      }, "Research policy profile created."),
    [createAsPublished, loadPolicies, newProfileKey, newProfileName, newVersionNotes, runSavingAction, specDraft,
      setSelectedProfileId, setSelectedVersionId, setNewProfileKey, setNewProfileName, setNewVersionNotes],
  );
  return { runSavingAction, createProfile };
}

export function useResearchPolicyVersionActions(
  { specDraft, newVersionNotes, setNewVersionNotes }: ResearchPolicyState,
  loadPolicies: () => Promise<void>,
  runSavingAction: RunSaving,
  selectedProfile: ResearchPolicyProfile | null,
  selectedVersion: ResearchPolicyVersion | null,
) {
  const createVersion = useCallback(
    (status: "draft" | "published") =>
      runSavingAction(
        async () => {
          if (!selectedProfile) throw new Error("Select a research policy profile first.");
          await readJson<ResearchPolicyProfile>(
            `/admin/chat/api/panel/research-policies/${encodeURIComponent(selectedProfile.id)}/versions`,
            { method: "POST", body: JSON.stringify({ spec: parseSpecDraft(specDraft), status, notes: newVersionNotes.trim() }) },
          );
          setNewVersionNotes("");
          await loadPolicies();
        },
        status === "published" ? "Published a new research policy version." : "Draft version created.",
      ),
    [loadPolicies, newVersionNotes, runSavingAction, selectedProfile, specDraft, setNewVersionNotes],
  );

  const publishSelectedVersion = useCallback(
    () =>
      runSavingAction(async () => {
        if (!selectedProfile || !selectedVersion) throw new Error("Select a version first.");
        await readJson<ResearchPolicyProfile>(
          `/admin/chat/api/panel/research-policies/${encodeURIComponent(selectedProfile.id)}/versions/${encodeURIComponent(selectedVersion.id)}`,
          { method: "PUT", body: JSON.stringify({ status: "published" }) },
        );
        await loadPolicies();
      }, "Research policy version published."),
    [loadPolicies, runSavingAction, selectedProfile, selectedVersion],
  );
  return { createVersion, publishSelectedVersion };
}
