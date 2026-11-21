import { useMemo } from "react";

import { useAdminWorkspaceComposition } from "../../hooks/useAdminWorkspaceComposition";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import type { ProjectSettingsTab } from "./projectSettingsSections";
import { WorkspaceCapabilityBindingCard } from "./workspaceComposition/WorkspaceCapabilityBindingCard";
import { WorkspaceDiagnosticsPanel } from "./workspaceComposition/WorkspaceDiagnosticsPanel";
import { WorkspaceAssignmentControlsPanel } from "./workspaceComposition/WorkspaceAssignmentControlsPanel";
import { useAdminNavigation } from "../../adminNavigation";
import "../workflowSurfaces/areaPurpose.css";

type AdminWorkspaceCompositionSectionProps = {
  ctx: Record<string, unknown>;
  // The Workflows and MCP-capabilities mirrors and the policy JSON editors left the Workspace page.
  view: "agents" | "diagnostics";
  // Lets diagnostics link a fix to another workspace settings section.
  onOpenSection?: (section: ProjectSettingsTab) => void;
};

// A Workspace's agent assignments (Agents & skills) and its configuration diagnostics, from the composition payload.
export function AdminWorkspaceCompositionSection({
  ctx,
  view,
  onOpenSection,
}: AdminWorkspaceCompositionSectionProps) {
  const { configuringProjectQuality, readJson } = ctx as {
    configuringProjectQuality: AdminProjectQuality | null;
    readJson: ReadJsonFn;
  };
  const workspaceId = configuringProjectQuality?.id || null;
  const {
    payload,
    loading,
    error,
    bindingsByKind,
    reload,
    savingBindingId,
    savingAssignmentControls,
    updateBinding,
    updateAssignmentControls,
  } = useAdminWorkspaceComposition({ workspaceId, readJson });

  const agentBindings = useMemo(
    () => bindingsByKind.find(([kind]) => kind === "agent")?.[1] ?? [],
    [bindingsByKind],
  );
  const agents = view === "agents";
  const allInstalled = payload?.assignment_controls.agent_assignment_mode !== "selected_only";

  return (
    <section className="admin-panel__card">
      <div className="admin-panel__section-header">
        <span>{agents ? "Agents" : "Diagnostics"}</span>
        <button type="button" className="admin-panel__action-btn" onClick={() => void reload()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <p className="admin-panel__hint">
        {agents
          ? "Whether this Workspace can use every installed agent or only the selected enabled agents."
          : "Configuration problems in this Workspace, what they cause and how to fix them."}
      </p>
      {error ? <div className="admin-panel__empty-state">{error}</div> : null}
      {loading && !payload ? <div className="admin-panel__empty-state">Loading…</div> : null}
      {payload && !agents ? (
        <WorkspaceDiagnosticsPanel
          warnings={payload.diagnostics.warnings}
          runtimeAssignmentMode={payload.assignment_controls.runtime_assignment_mode}
          onOpenSection={onOpenSection}
        />
      ) : null}
      {payload && agents ? (
        <AgentAssignments payload={payload} allInstalled={allInstalled} agentBindings={agentBindings}
          savingBindingId={savingBindingId} savingAssignmentControls={savingAssignmentControls} updateBinding={updateBinding}
          updateAssignmentControls={updateAssignmentControls} />
      ) : null}
    </section>
  );
}

type Composition = ReturnType<typeof useAdminWorkspaceComposition>;

// The agent assignments: the mode, then the pinned agents (or why there are none).
function AgentAssignments({
  payload,
  allInstalled,
  agentBindings,
  savingBindingId,
  savingAssignmentControls,
  updateBinding,
  updateAssignmentControls,
}: {
  payload: NonNullable<Composition["payload"]>;
  allInstalled: boolean;
  agentBindings: Composition["bindingsByKind"][number][1];
  savingBindingId: Composition["savingBindingId"];
  savingAssignmentControls: Composition["savingAssignmentControls"];
  updateBinding: Composition["updateBinding"];
  updateAssignmentControls: Composition["updateAssignmentControls"];
}) {
  return (
    <>
      <CatalogLinkNote allInstalled={allInstalled} />
      <WorkspaceAssignmentControlsPanel
        controls={payload.assignment_controls}
        bindings={payload.bindings}
        view="agents"
        isSaving={savingAssignmentControls}
        onSave={updateAssignmentControls}
      />
      {agentBindings.length === 0 ? (
        <div className="admin-panel__empty-state">
          {allInstalled
            ? "No agent is pinned to this Workspace. In “All installed” mode every active agent is available here."
            : "No agent assignment is configured for this Workspace yet."}
        </div>
      ) : (
        <div className="connector-grid">
          {agentBindings.map((binding) => (
            <WorkspaceCapabilityBindingCard
              key={binding.id}
              binding={binding}
              isSaving={savingBindingId === binding.id}
              onSave={updateBinding}
            />
          ))}
        </div>
      )}
    </>
  );
}

// Where agents are defined: the workspace only assigns them; authoring lives
// in Agents & workflows.
function CatalogLinkNote({ allInstalled }: { allInstalled: boolean }) {
  const { openAdminTab } = useAdminNavigation();
  return (
    <p className="admin-panel__hint">
      {allInstalled
        ? "Every active agent of the catalog is available in this Workspace. Switch to “Selected only” to restrict it."
        : "Only the agents enabled below are available in this Workspace."}
      {" "}
      <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab("agents")}>
        Open agents
      </button>
    </p>
  );
}
