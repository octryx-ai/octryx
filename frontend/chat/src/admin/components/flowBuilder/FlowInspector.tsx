import type {
  FlowDefinitionEdge,
  FlowDefinitionNode,
  FlowNodeCatalogItem,
  FlowNodeContract,
} from "./flowBuilderTypes";
import { FlowRouterInspector } from "./FlowRouterInspector";
import { ConfigSchemaForm, NodeSchemaEditor } from "./FlowSchemaEditors";
import { AgentStepInspector, SupervisorInspector, type AgentRow } from "./FlowInspectorAgentSections";
import {
  GenericConfigInspector,
  RawConfigInspector,
  ToolStepInspector,
  TriggerInspector,
  type ToolRow,
} from "./FlowInspectorConfigSections";

type FlowInspectorProps = {
  node: FlowDefinitionNode | null;
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
  onValidateConfig?: () => void;
  agents?: AgentRow[];
  tools?: ToolRow[];
  nodeContracts?: FlowNodeContract[];
  nodeCatalogItems?: FlowNodeCatalogItem[];
  // The workflow's connections and steps; the If / else inspector shows where each branch goes.
  edges?: FlowDefinitionEdge[];
  nodes?: FlowDefinitionNode[];
};

function shortType(value: string): string {
  return value.replaceAll("_", " ");
}

// The step's contract and catalog binding, and whether its config is edited through the binding's schema form.
function nodeBinding(node: FlowDefinitionNode, nodeContracts: FlowNodeContract[], nodeCatalogItems: FlowNodeCatalogItem[]) {
  const contract = nodeContracts.find((item) => item.type === node.type);
  const catalogItem = node.catalog_binding
    ? nodeCatalogItems.find((item) => item.id === node.catalog_binding?.id)
    : null;
  const configSchema = catalogItem?.config_schema ?? contract?.config_schema;
  const hasSchemaConfig =
    Boolean(configSchema) &&
    Boolean((configSchema?.properties as Record<string, unknown> | undefined));
  const usesSpecializedConfig = ["agent_step", "trigger", "router", "supervisor"].includes(node.type);
  const showSchemaConfig = hasSchemaConfig && !usesSpecializedConfig;
  return { contract, catalogItem, configSchema, showSchemaConfig };
}

/* ── Main FlowInspector ──────────────────────────────────────────────────── */
export function FlowInspector({
  node,
  onUpdate,
  onValidateConfig,
  agents = [],
  tools = [],
  nodeContracts = [],
  nodeCatalogItems = [],
  edges = [],
  nodes = [],
}: FlowInspectorProps) {
  if (!node) {
    return (
      <aside className="flow-inspector">
        <div className="flow-inspector__empty">
          <p>
            Select a node on the canvas to inspect it. In the profile graph
            editor, nodes reference existing system components — agents, tools,
            or triggers.
          </p>
        </div>
      </aside>
    );
  }

  const { contract, catalogItem, configSchema, showSchemaConfig } = nodeBinding(node, nodeContracts, nodeCatalogItems);
  return (
    <aside className="flow-inspector">
      <div className="flow-inspector__header">
        <span className="flow-inspector__node-type">{shortType(node.type)}</span>
        <span className="flow-inspector__node-id">{node.id}</span>
      </div>

      <label className="admin-panel__field">
        <span>Label</span>
        <input type="text" value={node.label ?? ""} onChange={(e) => onUpdate({ label: e.target.value })} className="flow-inspector__input" />
      </label>

      {showSchemaConfig ? (
        <ConfigSchemaForm schema={configSchema} config={node.config ?? {}} onChange={(config) => onUpdate({ config })} />
      ) : null}

      <StepKindInspector node={node} showSchemaConfig={showSchemaConfig} agents={agents} tools={tools} edges={edges} nodes={nodes}
        onUpdate={onUpdate} />

      {contract ? <ContractSection contract={contract} /> : null}
      {catalogItem ? <CatalogSection catalogItem={catalogItem} /> : null}

      <NodeSchemaEditor node={node} schemaKey="input_schema" onUpdate={onUpdate} />
      <NodeSchemaEditor node={node} schemaKey="output_schema" onUpdate={onUpdate} />

      {onValidateConfig ? (
        <button type="button" className="flow-inspector__validate-btn" onClick={onValidateConfig}>
          Validate config
        </button>
      ) : null}
    </aside>
  );
}


function StepKindInspector({
  node,
  showSchemaConfig,
  agents,
  tools,
  edges,
  nodes,
  onUpdate,
}: {
  node: FlowDefinitionNode;
  showSchemaConfig: boolean;
  agents: AgentRow[];
  tools: ToolRow[];
  edges: FlowDefinitionEdge[];
  nodes: FlowDefinitionNode[];
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
}) {
  return node.type === "agent_step" ? (
    <AgentStepInspector node={node} agents={agents} onUpdate={onUpdate} />
  ) : node.type === "tool_step" && !showSchemaConfig ? (
    <ToolStepInspector node={node} tools={tools} onUpdate={onUpdate} />
  ) : node.type === "trigger" ? (
    <TriggerInspector node={node} onUpdate={onUpdate} />
  ) : node.type === "router" ? (
    <FlowRouterInspector node={node} onUpdate={onUpdate} edges={edges} nodes={nodes} />
  ) : node.type === "supervisor" ? (
    <SupervisorInspector node={node} agents={agents} onUpdate={onUpdate} />
  ) : !showSchemaConfig ? (
    <GenericConfigInspector node={node} onUpdate={onUpdate} />
  ) : (
    <RawConfigInspector node={node} onUpdate={onUpdate} />
  );
}

function ContractSection({ contract }: { contract: FlowNodeContract }) {
  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Node Contract</div>
      <p className="flow-inspector__hint">{contract.description}</p>
      <div className="flow-inspector__contract-grid">
        <span>{contract.category}</span>
        {contract.can_start ? <span>can start</span> : null}
        {contract.can_end ? <span>can end</span> : null}
        {contract.can_pause ? <span>can pause</span> : null}
        {contract.calls_tools ? <span>tools</span> : null}
        {contract.calls_llm ? <span>LLM</span> : null}
      </div>
      {contract.required_config_keys.length ||
      contract.required_config_any.length ? (
        <p className="flow-inspector__hint">
          Required config:{" "}
          {[
            ...contract.required_config_keys,
            contract.required_config_any.length
              ? `one of ${contract.required_config_any.join(", ")}`
              : "",
          ]
            .filter(Boolean)
            .join("; ")}
        </p>
      ) : null}
      {contract.security_requirements.length ? (
        <ul className="flow-inspector__contract-list">
          {contract.security_requirements.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function CatalogSection({ catalogItem }: { catalogItem: FlowNodeCatalogItem }) {
  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Catalog Binding</div>
      <p className="flow-inspector__hint">{catalogItem.description}</p>
      <div className="flow-inspector__contract-grid">
        <span>{catalogItem.binding_type}</span>
        <span>{catalogItem.binding_ref}</span>
        <span>{catalogItem.availability_status}</span>
        <span>{catalogItem.token_cost_risk} cost</span>
      </div>
      {catalogItem.disabled_reason ? (
        <p className="flow-inspector__hint flow-inspector__hint--warning">
          {catalogItem.disabled_reason}
        </p>
      ) : null}
      <p className="flow-inspector__hint">{catalogItem.evidence_behavior}</p>
      <p className="flow-inspector__hint">{catalogItem.audit_behavior}</p>
    </div>
  );
}
