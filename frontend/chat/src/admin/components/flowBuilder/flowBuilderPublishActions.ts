// Flow Builder: publish the saved revision, unpublish its capability or reject (archive) the workflow.
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { EMPTY_REPORT } from "./flowBuilderDefaults";
import type { FlowDefinitionRow } from "./flowBuilderTypes";
import type { FlowBuilderState } from "./useFlowBuilderState";

type FlowBuilderPublishActionsInput = FlowBuilderState & {
  readJson: ReadJsonFn;
  loadFlowCapabilities: () => Promise<void>;
};

async function publishFlow({
  readJson, loadFlowCapabilities, authoring, setError, setBusy, description, name, activeDefinition, setSelectedFlow,
  setValidationReport, setRunTrace, setSelectedTraceNodeRunId, setQualitySummary, setPublishGateOpen,
}: FlowBuilderPublishActionsInput) {
  if (!authoring.publishable) { setError("Save the draft before publishing this revision."); return; }
  const versionId = authoring.version?.id;
  if (!versionId) {
    setError("Select or create a flow draft before publishing.");
    return;
  }
  setBusy(true);
  setError(null);
  try {
    const published = await readJson<FlowDefinitionRow>(
      `/api/v1/flows/versions/${versionId}/publish`,
      {
        method: "POST",
        body: JSON.stringify({
          publish_metadata: {
            purpose: description.trim() || name.trim(),
            llm_visible: true,
            capability_enabled: true,
            evidence_contract:
              typeof activeDefinition.evidence_contract === "object"
                ? activeDefinition.evidence_contract
                : {},
          },
        }),
      },
    );
    setSelectedFlow(published);
    setValidationReport(
      published.versions?.find((version) => version.id === versionId)?.validation_report || EMPTY_REPORT,
    );
    setRunTrace(null);
    setSelectedTraceNodeRunId(null);
    setQualitySummary(null);
    setPublishGateOpen(false);
    await loadFlowCapabilities();
  } catch (err) {
    setError(err instanceof Error ? err.message : "Publish failed");
  } finally {
    setBusy(false);
  }
}

async function unpublishCapability({
  readJson, loadFlowCapabilities, setError, setBusy, setSelectedFlow, setValidationReport, setRunTrace,
  setSelectedTraceNodeRunId, setQualitySummary, selectedCapability, selectedFlow,
}: FlowBuilderPublishActionsInput) {
  const versionId = selectedCapability?.version_id ?? selectedFlow?.current_version_id;
  if (!versionId) {
    setError("Select a published flow capability before unpublishing.");
    return;
  }
  setBusy(true);
  setError(null);
  try {
    const updated = await readJson<FlowDefinitionRow>(
      `/api/v1/flows/versions/${versionId}/unpublish`,
      {
        method: "POST",
        body: JSON.stringify({ reason: "Unpublished from Flow Builder" }),
      },
    );
    setSelectedFlow(updated);
    setValidationReport(updated.versions?.[0]?.validation_report || EMPTY_REPORT);
    setRunTrace(null);
    setSelectedTraceNodeRunId(null);
    setQualitySummary(null);
    await loadFlowCapabilities();
  } catch (err) {
    setError(err instanceof Error ? err.message : "Unpublish failed");
  } finally {
    setBusy(false);
  }
}

async function rejectFlow({
  readJson, setError, setBusy, setSelectedFlow, setValidationReport, selectedFlow,
}: FlowBuilderPublishActionsInput) {
  if (!selectedFlow?.id) {
    setError("Select a flow draft before rejecting it.");
    return;
  }
  setBusy(true);
  setError(null);
  try {
    const archived = await readJson<FlowDefinitionRow>(
      `/api/v1/flows/${selectedFlow.id}/archive`,
      { method: "POST" },
    );
    setSelectedFlow(archived);
    setValidationReport(
      archived.versions?.[0]?.validation_report || EMPTY_REPORT,
    );
  } catch (err) {
    setError(err instanceof Error ? err.message : "Reject failed");
  } finally {
    setBusy(false);
  }
}

export function flowBuilderPublishActions(input: FlowBuilderPublishActionsInput) {
  async function publishSelectedFlow() {
    return publishFlow(input);
  }

  async function unpublishSelectedCapability() {
    return unpublishCapability(input);
  }

  async function rejectSelectedFlow() {
    return rejectFlow(input);
  }

  return { publishSelectedFlow, unpublishSelectedCapability, rejectSelectedFlow };
}
