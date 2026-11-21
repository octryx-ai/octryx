import { flowDefinitionsEqual } from "./flowDefinitionCanonical";
import type { FlowDefinitionJson, FlowDefinitionRow, FlowDefinitionVersion } from "./flowBuilderTypes";

export function latestFlowVersion(flow: FlowDefinitionRow | null): FlowDefinitionVersion | undefined {
  return flow?.versions?.reduce<FlowDefinitionVersion | undefined>(
    (latest, version) => !latest || version.version > latest.version ? version : latest,
    undefined,
  );
}

export function flowAuthoringState(
  flow: FlowDefinitionRow | null,
  versionId: string | null,
  name: string,
  description: string,
  definition: FlowDefinitionJson,
) {
  const version = versionId ? flow?.versions?.find((item) => item.id === versionId) : latestFlowVersion(flow);
  const dirty = !flow || !version || name.trim() !== (flow.name || "").trim()
    || description.trim() !== (flow.description || "").trim()
    // Canonical comparison: loading a revision into the canvas must not count as an edit.
    || !flowDefinitionsEqual(definition, version.definition);
  const runnable = Boolean(version && !dirty && version.status !== "archived" && flow?.status !== "archived");
  return {
    version,
    dirty,
    runnable,
    publishable: runnable && version?.status === "draft",
    // Test cases are stored and run against the default version. Never silently
    // execute those tests against a different version from the visible authoring snapshot.
    testsAvailable: runnable && version?.id === flow?.current_version_id,
  };
}
