// Research policies admin state: profiles, versions, spec draft, create/publish actions and Workspace assignment.
import { useState } from "react";
import type {
  ResearchPolicyListPayload,
  WorkspaceResearchPolicyPayload,
} from "../types/researchPolicyTypes";
import type { ProjectOption } from "../../chatOptionTypes";
import { useActiveWorkspace } from "../../chat/useActiveWorkspace";
import { EMPTY_POLICY_PAYLOAD } from "./researchPolicyDrafts";
import { useResearchWorkspaceAssignment } from "./useResearchWorkspaceAssignment";
import {
  useResearchPolicyCreateProfile,
  useResearchPolicyLoading,
  useResearchPolicySelection,
  useResearchPolicyVersionActions,
} from "./researchPolicyHooks";

function useResearchPolicyState(projects: ProjectOption[]) {
  const [payload, setPayload] =
    useState<ResearchPolicyListPayload>(EMPTY_POLICY_PAYLOAD);
  const [workspacePolicy, setWorkspacePolicy] =
    useState<WorkspaceResearchPolicyPayload | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [editingProfileId, setEditingProfileId] = useState("");
  // The shared active workspace, never the first project: "" shows
  // an explicit "Select a workspace" state instead of an unrelated workspace.
  const [selectedProjectId, setSelectedProjectId] =
    useActiveWorkspace(projects);
  const [specDraft, setSpecDraft] = useState("{}");
  const [newProfileKey, setNewProfileKey] = useState("");
  const [newProfileName, setNewProfileName] = useState("");
  const [newVersionNotes, setNewVersionNotes] = useState("");
  const [createAsPublished, setCreateAsPublished] = useState(false);
  const [showCreateProfile, setShowCreateProfile] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  return {
    payload, setPayload, workspacePolicy, setWorkspacePolicy, selectedProfileId, setSelectedProfileId,
    selectedVersionId, setSelectedVersionId, editingProfileId, setEditingProfileId, selectedProjectId,
    setSelectedProjectId, specDraft, setSpecDraft, newProfileKey, setNewProfileKey, newProfileName,
    setNewProfileName, newVersionNotes, setNewVersionNotes, createAsPublished, setCreateAsPublished,
    showCreateProfile, setShowCreateProfile, loading, setLoading, saving, setSaving, error, setError,
    notice, setNotice,
  };
}

export type ResearchPolicyState = ReturnType<typeof useResearchPolicyState>;

// The fields the tab reads; internal setters (payload, loading, saving, error, notice) stay private.
function researchPolicyView(s: ResearchPolicyState) {
  return {
    createAsPublished: s.createAsPublished,
    error: s.error,
    loading: s.loading,
    newProfileKey: s.newProfileKey,
    newProfileName: s.newProfileName,
    newVersionNotes: s.newVersionNotes,
    notice: s.notice,
    payload: s.payload,
    saving: s.saving,
    selectedProfileId: s.selectedProfileId,
    selectedProjectId: s.selectedProjectId,
    selectedVersionId: s.selectedVersionId,
    editingProfileId: s.editingProfileId,
    setEditingProfileId: s.setEditingProfileId,
    setCreateAsPublished: s.setCreateAsPublished,
    setNewProfileKey: s.setNewProfileKey,
    setNewProfileName: s.setNewProfileName,
    setNewVersionNotes: s.setNewVersionNotes,
    setSelectedProfileId: s.setSelectedProfileId,
    setSelectedProjectId: s.setSelectedProjectId,
    setSelectedVersionId: s.setSelectedVersionId,
    setShowCreateProfile: s.setShowCreateProfile,
    showCreateProfile: s.showCreateProfile,
    setSpecDraft: s.setSpecDraft,
    specDraft: s.specDraft,
    workspacePolicy: s.workspacePolicy,
  };
}

export function useAdminResearchPolicies(projects: ProjectOption[]) {
  const state = useResearchPolicyState(projects);
  const { selectedProfile, selectedVersion, publishedVersions } = useResearchPolicySelection(state);
  const loadPolicies = useResearchPolicyLoading(state, selectedVersion);
  const { runSavingAction, createProfile } = useResearchPolicyCreateProfile(state, loadPolicies);
  const { createVersion, publishSelectedVersion } =
    useResearchPolicyVersionActions(state, loadPolicies, runSavingAction, selectedProfile, selectedVersion);
  const { assignWorkspacePolicy, clearWorkspacePolicy } = useResearchWorkspaceAssignment({
    runSavingAction,
    selectedProjectId: state.selectedProjectId,
    setWorkspacePolicy: state.setWorkspacePolicy,
  });

  return {
    ...researchPolicyView(state),
    assignWorkspacePolicy,
    clearWorkspacePolicy,
    createProfile,
    createVersion,
    loadPolicies,
    publishedVersions,
    publishSelectedVersion,
    selectedProfile,
    selectedVersion,
  };
}
