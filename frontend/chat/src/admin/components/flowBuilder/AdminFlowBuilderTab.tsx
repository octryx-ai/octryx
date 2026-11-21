import { useEffect } from "react";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { FlowDraftCreateDrawer } from "./FlowDraftCreateDrawer";
import { FlowBuilderTopbar, FlowEditorWorkspace } from "./FlowBuilderEditorParts";
import { useFlowDeepLink } from "./useFlowDeepLink";
import { useFlowCreateHandoff } from "./useFlowCreateHandoff";
import { PublishGateDrawer } from "./PublishGateDrawer";
import { VersionHistoryDrawer } from "./VersionHistoryDrawer";
import type { ProjectOption } from "./flowBuilderDefaults";
import { useFlowBuilderState } from "./useFlowBuilderState";
import { flowBuilderTabActions } from "./flowBuilderTabActions";
import { useFlowBuilderCatalogs } from "./useFlowBuilderCatalogs";
import "./flowBuilder.css";
import "./flowEditorDetails.css";

type AdminFlowBuilderTabProps = {
  projects: ProjectOption[];
  readJson: ReadJsonFn;
  // Embedded in the Workflows page: the page lists the workflows and opens one
  // through `flow_id` (or a create request link); "← All workflows" and a cancelled create hand back to the page.
  onExit: () => void;
  // Reports unsaved edits to the page, which confirms before switching workflows or views.
  onDirtyChange?: (dirty: boolean) => void;
};

export function AdminFlowBuilderTab({
  projects,
  readJson,
  onExit,
  onDirtyChange,
}: AdminFlowBuilderTabProps) {
  const state = useFlowBuilderState(projects);
  const {
    editorOpen, selectedFlow, setProjectId, busy, error, publishGateOpen, setPublishGateOpen, versionHistoryOpen,
    setVersionHistoryOpen, createDrawerOpen, setCreateDrawerOpen, createRequest, setCreateRequest, newDraftGuide, flowVersions,
    authoring, validationReport,
  } = state;

  const actions = flowBuilderTabActions({ state, readJson, onExit });
  const { loadFlowCapabilities, loadFlowDetail, publishSelectedFlow, openCreatedDraft, handleNodeRestore } = actions;

  useFlowDeepLink(loadFlowDetail, editorOpen ? selectedFlow?.id ?? null : null);
  useEffect(() => onDirtyChange?.(editorOpen && authoring.dirty), [editorOpen, authoring.dirty, onDirtyChange]);
  const settleCreateRequest = useFlowCreateHandoff(projects, (request) => {
    if (request.scope) setProjectId(request.scope);
    setCreateRequest(request);
    setCreateDrawerOpen(true);
  });


  useFlowBuilderCatalogs({ ...state, readJson, loadFlowCapabilities });

  return (
    <div className="flow-builder">
      {publishGateOpen ? (
        <PublishGateDrawer report={validationReport} onClose={() => setPublishGateOpen(false)} onPublish={publishSelectedFlow} busy={busy} />
      ) : null}

      {versionHistoryOpen ? (
        <VersionHistoryDrawer versions={flowVersions} onClose={() => setVersionHistoryOpen(false)} onRestore={handleNodeRestore} busy={busy} />
      ) : null}

      <FlowBuilderTopbar state={state} actions={actions} />

      {createDrawerOpen ? <FlowDraftCreateDrawer projects={projects} readJson={readJson} initialScope={createRequest?.scope} scopeNotice={createRequest?.notice} onClose={() => { settleCreateRequest(); setCreateDrawerOpen(false); setCreateRequest(null); if (!editorOpen) onExit(); }} onCreated={(flow) => { settleCreateRequest(); setCreateRequest(null); void openCreatedDraft(flow); }} /> : null}
      {error ? <div className="admin-panel__error">{error}</div> : null}

      {newDraftGuide && editorOpen ? <p className="admin-panel__hint">Your draft is saved. Select a step to edit its settings, or add a step from the palette. Save changes before using Run. Publishing makes the workflow available to others.</p> : null}
      {editorOpen ? <p className="admin-panel__hint" role="status">{authoring.dirty ? "Unsaved changes — save the draft before running or publishing." : `Viewing saved revision ${authoring.version?.version ?? "—"} (${authoring.version?.status ?? "draft"}). Run uses this exact revision.`}</p> : null}

      {!editorOpen ? (
        busy ? <p className="admin-panel__hint" role="status">Loading the workflow…</p> : null
      ) : (
        <FlowEditorWorkspace state={state} actions={actions} />
      )}
    </div>
  );
}
