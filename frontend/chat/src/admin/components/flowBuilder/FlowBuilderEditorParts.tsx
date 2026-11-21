// The Flow Builder editor's parts: the top bar, the workflow details, the run and results dock and the editor
// layout with the canvas and the step inspector.
import { ReactFlowProvider } from "@xyflow/react";
import { promptTextsHref } from "../../editorLinks";
import { safeKey } from "./flowBuilderDefinition";
import type { FlowBuilderTabActions } from "./flowBuilderTabActions";
import { FlowBuilderEditorActions } from "./FlowBuilderHeaderActions";
import { FlowReadiness } from "./FlowBuilderPanels";
import { FlowCanvas } from "./FlowCanvas";
import { FlowCapabilityPanel } from "./FlowCapabilityPanel";
import { FlowInspector } from "./FlowInspector";
import { FlowInspectorPanel } from "./FlowInspectorPanel";
import { flowStatusClass } from "./flowLibraryRows";
import { FlowQualityPanel } from "./FlowQualityPanel";
import { FlowRunInputSection } from "./FlowRunInputSection";
import { FlowRunWorkspaceField } from "./FlowRunWorkspaceField";
import { FlowRunPanel } from "./FlowRunPanel";
import { flowRunHeading } from "./flowRunResult";
import { FlowTestCasesPanel } from "./FlowTestCasesPanel";
import { FlowTracePanel } from "./FlowTracePanel";
import type { FlowBuilderState } from "./useFlowBuilderState";

type PartProps = { state: FlowBuilderState; actions: FlowBuilderTabActions };

export function FlowBuilderTopbar({ state, actions }: PartProps) {
  const { editorOpen, name, selectedFlow, busy, runBusy, authoring, nextAction, publishReady, operationsOpen, flowDetailsOpen,
    setOperationsOpen, setFlowDetailsOpen, setPublishGateOpen, setVersionHistoryOpen } = state;
  const { returnToLibrary, validateCurrentFlow, createFlowDraft } = actions;
  return (
    <div className="flow-builder__topbar">
      {/* The shell already titles the library page; the editor names the open workflow. */}
      <div className="flow-builder__title-block">
        {editorOpen ? (
          <>
            <span className="admin-panel__eyebrow">Workflow editor</span>
            <div className="flow-builder__title-row">
              <h2 title={name || "Untitled workflow"}>{name || "Untitled workflow"}</h2>
              {selectedFlow ? (
                <span
                  className={`flow-builder__badge ${flowStatusClass(selectedFlow.status || "draft")}`}
                >
                  {selectedFlow.status || "draft"}
                </span>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
      <div className="flow-builder__header-actions">
        {editorOpen ? (
          <FlowBuilderEditorActions
            busy={busy}
            runBusy={runBusy}
            hasFlow={Boolean(selectedFlow)}
            dirty={authoring.dirty}
            runnable={nextAction.canRun}
            publishReady={publishReady}
            operationsOpen={operationsOpen}
            detailsOpen={flowDetailsOpen}
            onBack={returnToLibrary}
            onRun={() => setOperationsOpen(true)}
            onToggleResults={() => setOperationsOpen((current) => !current)}
            onToggleDetails={() => setFlowDetailsOpen((current) => !current)}
            onValidate={() => void validateCurrentFlow({ reveal: true })}
            onCreateDraft={createFlowDraft}
            onPublish={() => setPublishGateOpen(true)}
            onVersions={() => setVersionHistoryOpen(true)}
            textsHref={selectedFlow?.key ? promptTextsHref(`workflow:${selectedFlow.key}`) : null}
          />
        ) : null}
      </div>
    </div>
  );
}

function FlowDetailsPanel({ state, actions }: PartProps) {
  const { name, setName, key, setKey, description, setDescription, selectedFlow, busy, setFlowDetailsOpen } = state;
  const { rejectSelectedFlow } = actions;
  return (
    <section className="flow-builder__details-panel">
      <div className="flow-builder__details-header">
        <span className="flow-builder__mode-label">
          Flow Graph Editor
        </span>
        <button
          type="button"
          onClick={() => setFlowDetailsOpen(false)}
          aria-label="Close workflow details"
        >
          Close
        </button>
      </div>
      <div className="flow-builder__details-grid">
        <label className="admin-panel__field">
          <span>Name</span>
          <input
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              if (!selectedFlow) setKey(safeKey(event.target.value));
            }}
          />
        </label>
        <label className="admin-panel__field">
          <span>Key</span>
          <input
            value={key}
            disabled={Boolean(selectedFlow)}
            onChange={(event) => setKey(event.target.value)}
          />
        </label>
        <label className="admin-panel__field flow-builder__details-description">
          <span>Description</span>
          <textarea
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
      </div>
      <div className="flow-builder__details-actions">
        <button
          type="button"
          onClick={rejectSelectedFlow}
          disabled={busy || !selectedFlow || selectedFlow.status === "archived"}
        >
          Reject
        </button>
      </div>
    </section>
  );
}

function FlowOperationsPanel({ state, actions }: PartProps) {
  const { runTrace, authoring, nextAction, runBusy, validationReport, testCases, setOperationsOpen, validation, activeDefinition,
    traceInputJson, setTraceInputJson, selectedTraceNodeRunId, setSelectedTraceNodeRunId, publishReady, selectedFlow,
    selectedCapability, busy, qualitySummary, qualityBusy, selectedNodeId, testBusy, setSelectedNodeId, runProjectId,
    setRunProjectId, runWorkspaceOptions } = state;
  const { runSelectedFlow, refreshRunTrace, recoverInterruptedRun, resolvePausedRun, cancelPausedRun, focusValidationIssue,
    loadFlowCapabilities, unpublishSelectedCapability, loadRunQuality, evaluateCurrentRun, createTestCase, runTestCase,
    batchRunTestCases, runSelectedNodePartial } = actions;
  return (
    <FlowRunPanel
      heading={flowRunHeading(runTrace, authoring.version?.version)} runKey={runTrace?.run.id}
      nextAction={nextAction} running={runBusy} report={validationReport} testCaseCount={testCases.length}
      onRun={runSelectedFlow} onClose={() => setOperationsOpen(false)}
      revealReadinessKey={validation.revealKey} validationState={validation.state}
      input={<>
        <FlowRunWorkspaceField flowProjectId={selectedFlow?.project_id} runProjectId={runProjectId} options={runWorkspaceOptions}
          onChange={setRunProjectId} />
        <FlowRunInputSection definition={activeDefinition} inputJson={traceInputJson} onInputChange={setTraceInputJson} />
      </>}
      result={<FlowTracePanel trace={runTrace} selectedNodeRunId={selectedTraceNodeRunId} running={runBusy} onRefresh={refreshRunTrace}
        onRecoverInterrupted={recoverInterruptedRun} onResume={resolvePausedRun} onCancel={cancelPausedRun} onSelectNodeRun={setSelectedTraceNodeRunId} />}
      readiness={<>
        <FlowReadiness report={validationReport} publishReady={publishReady} onIssueFocus={focusValidationIssue} />
        <FlowCapabilityPanel flow={selectedFlow} capability={selectedCapability} busy={busy} onRefresh={loadFlowCapabilities} onUnpublish={unpublishSelectedCapability} />
      </>}
      quality={<FlowQualityPanel summary={qualitySummary} busy={qualityBusy} disabled={!runTrace} onRefresh={loadRunQuality} onEvaluate={evaluateCurrentRun} />}
      testCases={<>
        {!authoring.testsAvailable ? <p className="admin-panel__hint">Test cases belong to the saved default revision. Save first; when editing a new draft of a published workflow, use Run to test that draft. Publishing makes it the default revision.</p> : null}
        <FlowTestCasesPanel testCases={testCases} nodes={activeDefinition.nodes} selectedNodeId={selectedNodeId} busy={testBusy || runBusy || !nextAction.canRun}
          casesDisabled={!authoring.testsAvailable} onCreate={createTestCase} onRun={runTestCase} onBatchRun={batchRunTestCases} onNodeSelect={setSelectedNodeId} onPartialRun={runSelectedNodePartial} />
      </>}
    />
  );
}

function FlowCanvasShell({ state, actions }: PartProps) {
  const { activeDefinition, selectedNodeId, setSelectedNodeId, agents, tools, componentsLoading, nodeCatalogLoading,
    nodeContracts, nodeCatalogItems, nodeRunStatuses, newDraftGuide } = state;
  const { handleExpertDefinitionChange } = actions;
  return (
    <div className="flow-builder__canvas-shell">
      <ReactFlowProvider>
        <FlowCanvas
          definition={activeDefinition}
          onChange={handleExpertDefinitionChange}
          selectedNodeId={selectedNodeId}
          onNodeSelect={setSelectedNodeId}
          agents={agents}
          tools={tools}
          agentsLoading={componentsLoading || nodeCatalogLoading}
          nodeContracts={nodeContracts}
          nodeCatalogItems={nodeCatalogItems}
          nodeRunStatuses={nodeRunStatuses}
          paletteStartCollapsed={!newDraftGuide}
        />
      </ReactFlowProvider>
    </div>
  );
}

export function FlowEditorWorkspace({ state, actions }: PartProps) {
  const { flowDetailsOpen, operationsOpen, setOperationsOpen, selectedNode, setSelectedNodeId, agents, tools, nodeContracts,
    nodeCatalogItems, activeDefinition } = state;
  const { handleNodeUpdate } = actions;
  return (
    <div className="flow-builder__layout flow-builder__layout--editor">
      <main className="flow-builder__main">
        {flowDetailsOpen ? <FlowDetailsPanel state={state} actions={actions} /> : null}

        <FlowCanvasShell state={state} actions={actions} />
        <button
          type="button"
          className="flow-builder__dock-toggle"
          onClick={() => setOperationsOpen((current) => !current)}
          aria-expanded={operationsOpen}
        >
          {operationsOpen ? "Hide results" : "Run & results"}
        </button>
        {operationsOpen ? <FlowOperationsPanel state={state} actions={actions} /> : null}
      </main>

      {selectedNode ? (
        <FlowInspectorPanel onClose={() => setSelectedNodeId(null)}>
          <FlowInspector
            node={selectedNode}
            onUpdate={handleNodeUpdate}
            agents={agents}
            tools={tools}
            nodeContracts={nodeContracts}
            nodeCatalogItems={nodeCatalogItems}
            edges={activeDefinition.edges}
            nodes={activeDefinition.nodes}
          />
        </FlowInspectorPanel>
      ) : null}
    </div>
  );
}
