// Flow Builder: load the open workflow and its capabilities, validate the definition and save a draft.
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { latestFlowVersion } from "./flowAuthoringState";
import { parseJsonObject, safeKey } from "./flowBuilderDefinition";
import { EMPTY_DEFINITION, EMPTY_REPORT, prettyJson } from "./flowBuilderDefaults";
import type { FlowCapabilityListPayload, FlowDefinitionJson, FlowDefinitionRow, FlowValidationReport } from "./flowBuilderTypes";
import type { FlowBuilderState } from "./useFlowBuilderState";

type FlowBuilderFlowActionsInput = FlowBuilderState & {
  readJson: ReadJsonFn;
  loadTestCases: (flowId: string) => Promise<void>;
};

async function loadFlowCapabilities(input: FlowBuilderFlowActionsInput) {
  const { readJson, projectId, setFlowCapabilities, setError } = input;
  try {
    const params = new URLSearchParams({ include_hidden: "true" });
    if (projectId) {
      params.set("project_id", projectId);
    }
    const payload = await readJson<FlowCapabilityListPayload>(
      `/api/v1/flows/capabilities?${params.toString()}`,
    );
    setFlowCapabilities(payload.items || []);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Failed to load flow capabilities");
  }
}

async function loadFlowDetail(input: FlowBuilderFlowActionsInput, flowId: string) {
  const {
    readJson, loadTestCases, setError, flowDetailRequest, setNewDraftGuide, setBusy, setAuthoringVersionId, setSelectedFlow,
    setName, setKey, setDescription, setExpertJson, setValidationReport, setRunTrace, setSelectedTraceNodeRunId,
    setQualitySummary, setOperationsOpen, setFlowDetailsOpen, setEditorOpen,
  } = input;
  // The latest Open wins: an earlier, slower load (a deep link, a double click) never replaces it.
  const request = ++flowDetailRequest.current;
  setNewDraftGuide(false);
  setBusy(true);
  setError(null);
  try {
    const detail = await readJson<FlowDefinitionRow>(
      `/api/v1/flows/${flowId}`,
    );
    if (request !== flowDetailRequest.current) return false;
    const version = latestFlowVersion(detail);
    setAuthoringVersionId(version?.id ?? null);
    setSelectedFlow(detail);
    setName(detail.name);
    setKey(detail.key);
    setDescription(detail.description || "");
    setExpertJson(
      prettyJson(version?.definition || EMPTY_DEFINITION),
    );
    setValidationReport(version?.validation_report || EMPTY_REPORT);
    setRunTrace(null);
    setSelectedTraceNodeRunId(null);
    setQualitySummary(null);
    setOperationsOpen(false);
    setFlowDetailsOpen(false);
    setEditorOpen(true);
    await loadTestCases(detail.id);
    return true;
  } catch (err) {
    if (request === flowDetailRequest.current) setError(err instanceof Error ? err.message : "Failed to load flow");
    return false;
  } finally {
    if (request === flowDetailRequest.current) setBusy(false);
  }
}

async function validateCurrentFlow(input: FlowBuilderFlowActionsInput, { reveal = false }: { reveal?: boolean } = {}) {
  const { readJson, setError, setBusy, setExpertJson, setValidationReport, setOperationsOpen, validation, expertJson, selectedFlow } = input;
  setBusy(true);
  setError(null);
  const request = validation.begin(reveal);
  if (reveal) setOperationsOpen(true);
  try {
    const definition = parseJsonObject<FlowDefinitionJson>(expertJson);
    const report = await readJson<FlowValidationReport>(
      "/api/v1/flows/validate",
      {
        method: "POST",
        body: JSON.stringify(selectedFlow ? { definition, flow_id: selectedFlow.id } : { definition }),
      },
    );
    if (!validation.isCurrent(request)) return validation.settle(request, "stale");
    setValidationReport(report);
    setExpertJson(prettyJson(definition));
    validation.settle(request, "done");
  } catch (err) {
    if (!validation.isCurrent(request)) return validation.settle(request, "stale");
    setValidationReport(EMPTY_REPORT);
    setError(err instanceof Error ? err.message : "Validation failed");
    validation.settle(request, "failed");
  } finally {
    setBusy(false);
  }
}

async function createFlowDraft(input: FlowBuilderFlowActionsInput) {
  const {
    readJson, loadTestCases, projectId, setError, setBusy, setAuthoringVersionId, setSelectedFlow, setValidationReport,
    setRunTrace, setSelectedTraceNodeRunId, setOperationsOpen, setFlowDetailsOpen, setEditorOpen,
    expertJson, selectedFlow, name, key, description,
  } = input;
  const flowName = name.trim();
  if (!flowName) {
    setError("Flow name is required.");
    return;
  }
  setBusy(true);
  setError(null);
  try {
    const definition = parseJsonObject<FlowDefinitionJson>(expertJson);
    const metadata = definition.template_metadata ?? {};
    const templateKey =
      typeof metadata.template_key === "string" ? metadata.template_key : null;
    const created = await readJson<FlowDefinitionRow>(selectedFlow ? `/api/v1/flows/${selectedFlow.id}/drafts` : "/api/v1/flows", {
      method: "POST",
      body: JSON.stringify({
        expected_latest_version_id: latestFlowVersion(selectedFlow)?.id,
        project_id: projectId || null,
        key: safeKey(key || flowName),
        name: flowName,
        description: description.trim(),
        definition,
        runtime_settings: {
          authoring_mode: "visual_builder",
          template_key: templateKey,
        },
        policy_bindings: { validation_required: true },
      }),
    });
    setSelectedFlow(created);
    setAuthoringVersionId(latestFlowVersion(created)?.id ?? null);
    setEditorOpen(true);
    setOperationsOpen(false);
    setFlowDetailsOpen(false);
    setValidationReport(
      latestFlowVersion(created)?.validation_report || EMPTY_REPORT,
    );
    setRunTrace(null);
    setSelectedTraceNodeRunId(null);
    await loadTestCases(created.id);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Flow creation failed");
  } finally {
    setBusy(false);
  }
}

export function flowBuilderFlowActions(input: FlowBuilderFlowActionsInput) {
  return {
    loadFlowCapabilities: () => loadFlowCapabilities(input),
    loadFlowDetail: (flowId: string) => loadFlowDetail(input, flowId),
    validateCurrentFlow: (options: { reveal?: boolean } = {}) => validateCurrentFlow(input, options),
    createFlowDraft: () => createFlowDraft(input),
  };
}
