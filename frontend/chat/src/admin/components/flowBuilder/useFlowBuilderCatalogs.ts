// Flow Builder: load the published capabilities, the node catalog and the agents, tools and node contracts.
import { useEffect } from "react";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type { ToolRow } from "./flowBuilderDefaults";
import type { FlowNodeCatalogPayload, FlowNodeRegistryPayload } from "./flowBuilderTypes";
import type { FlowBuilderState } from "./useFlowBuilderState";

type FlowBuilderCatalogsInput = FlowBuilderState & {
  readJson: ReadJsonFn;
  loadFlowCapabilities: () => Promise<void>;
};

export function useFlowBuilderCatalogs({
  readJson, loadFlowCapabilities, projectId, flowScopeProjectId, setNodeCatalogLoading, setNodeCatalogItems,
  setComponentsLoading, setAgentRows, setTools, setNodeContracts,
}: FlowBuilderCatalogsInput) {
  useEffect(() => {
    void loadFlowCapabilities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    setNodeCatalogLoading(true);
    const params = new URLSearchParams({ include_disabled: "true" });
    if (flowScopeProjectId) {
      params.set("project_id", flowScopeProjectId);
    }
    readJson<FlowNodeCatalogPayload>(`/api/v1/flows/node-catalog?${params.toString()}`)
      .then((payload) => {
        setNodeCatalogItems(Array.isArray(payload.items) ? payload.items : []);
      })
      .catch((err: unknown) => {
        console.error("Failed to load flow node catalog", err);
        setNodeCatalogItems([]);
      })
      .finally(() => setNodeCatalogLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowScopeProjectId]);

  // Load system components for node inspector reference
  useEffect(() => {
    setComponentsLoading(true);
    Promise.allSettled([
      readJson<Array<Record<string, unknown>>>("/admin/chat/api/panel/agents"),
      readJson<ToolRow[]>("/admin/chat/api/panel/tool-catalog"),
      readJson<FlowNodeRegistryPayload>("/api/v1/flows/node-registry"),
    ])
      .then(([agentResult, toolResult, registryResult]) => {
        if (agentResult.status === "fulfilled" && Array.isArray(agentResult.value)) setAgentRows(agentResult.value);
        if (toolResult.status === "fulfilled" && Array.isArray(toolResult.value)) {
          setTools(
            toolResult.value.map((t) => ({
              name: t.name,
              description: t.description,
              is_core: t.is_core,
            })),
          );
        }
        if (
          registryResult.status === "fulfilled" &&
          Array.isArray(registryResult.value.items)
        ) {
          setNodeContracts(registryResult.value.items);
        }
      })
      .finally(() => setComponentsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
