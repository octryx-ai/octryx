// Flow Builder: editor state, derived views of the open workflow and its validation feedback.
import { useMemo, useRef, useState } from "react";
import { flowAuthoringState } from "./flowAuthoringState";
import { parseJsonObject } from "./flowBuilderDefinition";
import { EMPTY_DEFINITION, EMPTY_REPORT, prettyJson, type ProjectOption, type ToolRow } from "./flowBuilderDefaults";
import type { FlowCapability, FlowDefinitionJson, FlowDefinitionRow, FlowDefinitionNode, FlowDefinitionVersion, FlowNodeCatalogItem, FlowNodeContract, FlowValidationReport } from "./flowBuilderTypes";
import type { FlowQualitySummary, FlowRunTracePayload, FlowTestCase } from "./flowRunTypes";
import { useFlowValidationFeedback } from "./flowValidationFeedback";
import { flowNextAction } from "./flowNextAction";
import { flowAgentOptions } from "./flowPaletteModel";
import type { FlowCreateRequest } from "./useFlowCreateHandoff";

export type FlowBuilderState = ReturnType<typeof useFlowBuilderState>;

/** The open workflow and its editor: identity, JSON, validation report, selection and drawers. */
function useFlowDraftState() {
  const defaultProjectId = "";
  const [editorOpen, setEditorOpen] = useState(false);
  const flowDetailRequest = useRef(0);
  const [selectedFlow, setSelectedFlow] = useState<FlowDefinitionRow | null>(
    null,
  );
  const [projectId, setProjectId] = useState(defaultProjectId);
  const [name, setName] = useState("Untitled Flow");
  const [key, setKey] = useState("untitled-flow");
  const [description, setDescription] = useState(
    "Executable Flow Definition draft for visual workflow authoring.",
  );
  const [expertJson, setExpertJson] = useState(prettyJson(EMPTY_DEFINITION));
  const [validationReport, setValidationReport] =
    useState<FlowValidationReport>(EMPTY_REPORT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [authoringVersionId, setAuthoringVersionId] = useState<string | null>(null);
  const [publishGateOpen, setPublishGateOpen] = useState(false);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  return {
    editorOpen, setEditorOpen, flowDetailRequest, selectedFlow, setSelectedFlow, projectId, setProjectId,
    name, setName, key, setKey, description, setDescription, expertJson, setExpertJson,
    validationReport, setValidationReport, busy, setBusy, error, setError, selectedNodeId, setSelectedNodeId,
    authoringVersionId, setAuthoringVersionId, publishGateOpen, setPublishGateOpen,
    versionHistoryOpen, setVersionHistoryOpen,
  };
}

/** Catalogs, panels, runs, test cases and quality of the open workflow. */
function useFlowPanelState() {
  const [agentRows, setAgentRows] = useState<Array<Record<string, unknown>>>([]);
  const [tools, setTools] = useState<ToolRow[]>([]);
  const [componentsLoading, setComponentsLoading] = useState(false);
  const [nodeCatalogLoading, setNodeCatalogLoading] = useState(false);
  const [flowDetailsOpen, setFlowDetailsOpen] = useState(false);
  const [createDrawerOpen, setCreateDrawerOpen] = useState(false);
  // A create request from Workspace settings: preselected workspace or why there is none.
  const [createRequest, setCreateRequest] = useState<FlowCreateRequest | null>(null);
  const [newDraftGuide, setNewDraftGuide] = useState(false);
  const [operationsOpen, setOperationsOpen] = useState(false);
  const [nodeContracts, setNodeContracts] = useState<FlowNodeContract[]>([]);
  const [nodeCatalogItems, setNodeCatalogItems] = useState<FlowNodeCatalogItem[]>([]);
  const [runTrace, setRunTrace] = useState<FlowRunTracePayload | null>(null);
  const [selectedTraceNodeRunId, setSelectedTraceNodeRunId] = useState<string | null>(null);
  const [traceInputJson, setTraceInputJson] = useState(
    prettyJson({ request: "Manual Flow Builder test run" }),
  );
  const [runBusy, setRunBusy] = useState(false);
  const [testCases, setTestCases] = useState<FlowTestCase[]>([]);
  const [testBusy, setTestBusy] = useState(false);
  const [qualitySummary, setQualitySummary] = useState<FlowQualitySummary | null>(null);
  const [qualityBusy, setQualityBusy] = useState(false);
  const [flowCapabilities, setFlowCapabilities] = useState<FlowCapability[]>([]);
  // The Workspace a run of a Workspace-less (platform) flow starts in; a Workspace's flow runs in its own.
  const [runProjectId, setRunProjectId] = useState("");

  return {
    agentRows, setAgentRows, tools, setTools,
    componentsLoading, setComponentsLoading, nodeCatalogLoading, setNodeCatalogLoading,
    flowDetailsOpen, setFlowDetailsOpen, createDrawerOpen, setCreateDrawerOpen, createRequest, setCreateRequest,
    newDraftGuide, setNewDraftGuide, operationsOpen, setOperationsOpen, nodeContracts, setNodeContracts,
    nodeCatalogItems, setNodeCatalogItems, runTrace, setRunTrace, selectedTraceNodeRunId, setSelectedTraceNodeRunId,
    traceInputJson, setTraceInputJson, runBusy, setRunBusy, testCases, setTestCases, testBusy, setTestBusy,
    qualitySummary, setQualitySummary, qualityBusy, setQualityBusy, flowCapabilities, setFlowCapabilities,
    runProjectId, setRunProjectId,
  };
}

/** Views derived from the editor state: the parsed definition, the selection, readiness and run statuses. */
function useFlowDerivedState(
  projects: ProjectOption[],
  { selectedFlow, projectId, name, description, expertJson, validationReport, selectedNodeId, authoringVersionId }: ReturnType<typeof useFlowDraftState>,
  { agentRows, runTrace, runBusy, flowCapabilities, runProjectId }: ReturnType<typeof useFlowPanelState>,
) {
  const activeDefinition = useMemo(() => {
    try {
      return parseJsonObject<FlowDefinitionJson>(expertJson);
    } catch {
      return EMPTY_DEFINITION;
    }
  }, [expertJson]);

  const selectedNode = useMemo<FlowDefinitionNode | null>(
    () => activeDefinition.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [activeDefinition.nodes, selectedNodeId],
  );

  const flowVersions = useMemo<FlowDefinitionVersion[]>(
    () => selectedFlow?.versions ?? [],
    [selectedFlow?.versions],
  );

  const authoring = flowAuthoringState(selectedFlow, authoringVersionId, name, description, activeDefinition);
  const validation = useFlowValidationFeedback({ flowId: selectedFlow?.id ?? null, versionId: authoringVersionId, definitionJson: expertJson });
  const nextAction = flowNextAction({ hasFlow: Boolean(selectedFlow), flowArchived: selectedFlow?.status === "archived", version: authoring.version,
    dirty: authoring.dirty, report: validationReport, nodeCount: activeDefinition.nodes.length, running: runBusy });
  // The open workflow's scope (or the library filter for a new one) gates agents and catalog tools.
  const flowScopeProjectId = selectedFlow ? selectedFlow.project_id : projectId || null;
  const runWorkspaceId = selectedFlow?.project_id || runProjectId || null;
  const publishReady =
    authoring.publishable && validationReport.valid &&
    activeDefinition.nodes.length > 0 &&
    Boolean(name.trim());
  const projectNameById = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const agents = useMemo(() => flowAgentOptions(agentRows, flowScopeProjectId, projectNameById), [agentRows, flowScopeProjectId, projectNameById]);

  const nodeRunStatuses = useMemo(() => {
    const entries =
      runTrace?.node_runs?.map((nodeRun) => [nodeRun.node_id, nodeRun.status] as const) ?? [];
    return Object.fromEntries(entries);
  }, [runTrace?.node_runs]);

  const selectedCapability = useMemo(
    () =>
      flowCapabilities.find(
        (capability) =>
          capability.version_id === selectedFlow?.current_version_id ||
          capability.flow_id === selectedFlow?.id,
      ) ?? null,
    [flowCapabilities, selectedFlow?.current_version_id, selectedFlow?.id],
  );

  return {
    activeDefinition, selectedNode, flowVersions, authoring, validation, nextAction, flowScopeProjectId,
    publishReady, agents, nodeRunStatuses, selectedCapability, runWorkspaceId, runWorkspaceOptions: projects,
  };
}

export function useFlowBuilderState(projects: ProjectOption[]) {
  const draft = useFlowDraftState();
  const panels = useFlowPanelState();
  const derived = useFlowDerivedState(projects, draft, panels);
  return { ...draft, ...panels, ...derived };
}
