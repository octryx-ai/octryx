// Admin research policies tab: research profile table, create panel, profile editor panel and Workspace assignment.
import { useMemo, type FormEvent } from "react";
import { useAdminResearchPolicies } from "../hooks/useAdminResearchPolicies";
import { ResearchProfileCreatePanel, ResearchProfileEditPanel } from "./AdminResearchProfilePanels";
import { ResearchWorkspaceAssignment } from "./researchPolicies/ResearchWorkspaceAssignment";
import { researchProfileSummary } from "./researchPolicies/researchProfileSummary";
import { parsePolicySpecDraft } from "./researchPolicies/researchPolicySpecHelpers";
import type { ProjectOption } from "../../chatOptionTypes";
import { LoadingState } from "../../layout/LoadingState";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import { AdminHeaderActions } from "./AdminHeaderSlot";
import type { ResearchPolicyProfile } from "../types/researchPolicyTypes";

type AdminResearchPoliciesTabProps = {
  projects: ProjectOption[];
};

// A profile's lifecycle in words ("active" → "Active").
function lifecycleWords(status: string): string {
  const words = String(status || "").replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown";
}

type ResearchPoliciesState = ReturnType<typeof useAdminResearchPolicies>;

// The research profile columns: name, what the published version allows, version count and lifecycle.
const PROFILE_COLUMNS: DataTableColumn<ResearchPolicyProfile>[] = [
  // The name on one line; the profile key is no column of its own (it is the tooltip and the
  // panel's subtitle).
  { key: "name", header: "Name", nowrap: true, render: (profile) => <strong title={profile.key}>{profile.name}</strong> },
  {
    key: "allows",
    header: "Allows",
    grow: true,
    render: (profile) => {
      const published =
        profile.versions.find((version) => version.id === profile.latest_published_version_id) || profile.versions[0];
      return <span className="admin-panel__cell--muted">{researchProfileSummary(published?.spec)}</span>;
    },
  },
  { key: "versions", header: "Versions", width: "6rem", align: "end", render: (profile) => profile.versions.length },
  {
    key: "status",
    header: "Status",
    width: "8rem",
    nowrap: true,
    render: (profile) => <StatusLabel label={lifecycleWords(profile.lifecycle_status)} />,
  },
];

function ResearchProfilesTable({ state, onOpen }: { state: ResearchPoliciesState; onOpen: (profile: ResearchPolicyProfile) => void }) {
  return (
    <DataTable<ResearchPolicyProfile>
      label="Research profiles"
      testId="research-profiles-table"
      rows={state.payload.profiles}
      rowKey={(profile) => profile.id}
      onOpen={onOpen}
      selectedKey={state.editingProfileId || null}
      empty={{ text: "No research profiles yet.", action: { label: "New profile", onClick: () => state.setShowCreateProfile(true) } }}
      columns={PROFILE_COLUMNS}
    />
  );
}

// Refresh and the create flow's entry, in the admin page header.
function ResearchHeaderActions({ state }: { state: ResearchPoliciesState }) {
  return (
    <AdminHeaderActions>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => void state.loadPolicies()}
        disabled={state.saving}
      >
        Refresh
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={() => state.setShowCreateProfile(true)}
        data-testid="research-profile-new"
      >
        New profile
      </button>
    </AdminHeaderActions>
  );
}

// Creating a profile closes its panel once created; a row opens the profile at its published (or first) version.
function researchProfileHandlers(state: ResearchPoliciesState) {
  const handleCreateProfile = (e?: FormEvent) => {
    e?.preventDefault();
    void state.createProfile().then((created) => { if (created) state.setShowCreateProfile(false); });
  };
  const openProfile = (profile: ResearchPolicyProfile) => {
    state.setSelectedProfileId(profile.id);
    state.setEditingProfileId(profile.id);
    state.setSelectedVersionId(profile.latest_published_version_id || profile.versions[0]?.id || "");
  };
  const closeEditor = () => state.setEditingProfileId("");
  return { handleCreateProfile, openProfile, closeEditor };
}

export function AdminResearchPoliciesTab({
  projects,
}: AdminResearchPoliciesTabProps) {
  const state = useAdminResearchPolicies(projects);

  const selectedSpec = useMemo(() => {
    try {
      return parsePolicySpecDraft(state.specDraft);
    } catch {
      return state.selectedVersion?.spec || {};
    }
  }, [state.selectedVersion?.spec, state.specDraft]);

  const { handleCreateProfile, openProfile, closeEditor } = researchProfileHandlers(state);

  if (state.loading) {
    return (
      <LoadingState label="research profiles" variant="cards" rows={3} />
    );
  }

  return (
    <div className="admin-users">
      <ResearchHeaderActions state={state} />

      {state.error ? (
        <div className="admin-panel__error">{state.error}</div>
      ) : null}
      {state.notice ? (
        <div className="admin-panel__success">{state.notice}</div>
      ) : null}

      {state.showCreateProfile ? (
        <ResearchProfileCreatePanel state={state} onCreate={handleCreateProfile} />
      ) : null}

      {/* A row opens the profile in the side panel, where it is edited (no Edit buttons in rows). */}
      <ResearchProfilesTable state={state} onOpen={openProfile} />

      {/* ── Edit panel ── */}
      {state.editingProfileId && state.selectedProfile ? (
        <ResearchProfileEditPanel state={state} profile={state.selectedProfile} selectedSpec={selectedSpec} onClose={closeEditor} />
      ) : null}

      <ResearchWorkspaceAssignment
        projects={projects}
        selectedProjectId={state.selectedProjectId}
        workspacePolicy={state.workspacePolicy}
        publishedVersions={state.publishedVersions}
        saving={state.saving}
        onAssign={(versionId) => void state.assignWorkspacePolicy(versionId)}
        onClear={() => void state.clearWorkspacePolicy()}
      />
    </div>
  );
}
