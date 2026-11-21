import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { ProjectKnowledgeAccessView } from "./ProjectKnowledgeAccessView";
import { ProjectRepositoryPolicyView } from "./ProjectRepositoryPolicyView";
import { resourceActions, useProjectResourceState, useResourceDrafts } from "./useProjectResources";

type ProjectResourcesSectionProps = {
  ctx: Record<string, unknown>;
  view: "repositories" | "knowledge";
};

export function ProjectResourcesSection({
  ctx,
  view,
}: ProjectResourcesSectionProps) {
  const { configuringProjectQuality, readJson } = ctx as {
    configuringProjectQuality: AdminProjectQuality | null;
    readJson: ReadJsonFn;
  };
  const projectId = configuringProjectQuality?.id || "";
  const state = useProjectResourceState(projectId, readJson);
  const { payload, loading, saving, error, selectedMountProjectId, setSelectedMountProjectId, mountLabel, setMountLabel } = state;
  const drafts = useResourceDrafts(payload);
  const { availableKnowledgeBases, knowledgeAccess } = drafts;
  const actions = resourceActions(projectId, readJson, state, drafts);

  if (loading && !payload) {
    return <div className="admin-panel__empty-state">Loading resources…</div>;
  }

  return (
    <section className="admin-modal__stack" style={{ marginTop: 20 }}>
      {error ? <div className="admin-panel__empty-state">{error}</div> : null}
      {view === "repositories" && payload ? (
        <ProjectRepositoryPolicyView
          payload={payload}
          saving={saving}
          toggleRepositoryOperation={actions.toggleRepositoryOperation}
        />
      ) : null}
      {view === "knowledge" && payload ? (
        <ProjectKnowledgeAccessView
          payload={payload}
          saving={saving}
          knowledgeAccess={knowledgeAccess}
          toggleWorkspaceKnowledgeAccess={actions.toggleWorkspaceKnowledgeAccess}
          removeKnowledgeMount={actions.removeKnowledgeMount}
          selectedMountProjectId={selectedMountProjectId}
          setSelectedMountProjectId={setSelectedMountProjectId}
          mountLabel={mountLabel}
          setMountLabel={setMountLabel}
          availableKnowledgeBases={availableKnowledgeBases}
          addKnowledgeMount={actions.addKnowledgeMount}
        />
      ) : null}
    </section>
  );
}
