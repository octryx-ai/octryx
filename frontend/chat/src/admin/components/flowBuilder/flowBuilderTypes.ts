export type FlowNodeType =
  | "trigger"
  | "input_schema"
  | "policy_gate"
  | "clarification_gate"
  | "retrieval"
  | "router"
  | "agent_step"
  | "tool_step"
  | "approval"
  | "evaluation"
  | "parallel"
  | "join"
  | "human_task"
  | "output"
  | "learning_proposal"
  | "error_handler"
  | "supervisor"
  | "subflow";

export type FlowDefinitionNode = {
  id: string;
  type: FlowNodeType;
  label?: string;
  input_schema?: Record<string, string>;
  output_schema?: Record<string, string>;
  config?: Record<string, unknown>;
  retry_policy?: Record<string, unknown>;
  timeout_policy?: Record<string, unknown>;
  budget_hints?: Record<string, unknown>;
  catalog_binding?: {
    id: string;
    binding_type: string;
    binding_ref: string;
    availability_status: string;
  };
  position?: { x: number; y: number };
};

export type FlowDefinitionEdge = {
  id?: string;
  from_node_id?: string;
  to_node_id?: string;
  source_node_id?: string;
  target_node_id?: string;
  source_field?: string;
  target_field?: string;
  condition?: string | Record<string, unknown>;
};

export type FlowDefinitionJson = {
  schema_version?: string;
  metadata?: Record<string, unknown>;
  nodes: FlowDefinitionNode[];
  edges: FlowDefinitionEdge[];
  io_mappings?: Array<Record<string, unknown>>;
  evidence_contract?: Record<string, unknown>;
  template_metadata?: Record<string, unknown>;
  runtime_settings?: Record<string, unknown>;
  publish_settings?: Record<string, unknown>;
  compatibility?: Record<string, unknown>;
};

export type FlowNodeContract = {
  type: FlowNodeType;
  display_name: string;
  category: string;
  description: string;
  config_schema: Record<string, unknown>;
  input_schema: Record<string, string>;
  output_schema: Record<string, string>;
  can_start: boolean;
  can_end: boolean;
  can_pause: boolean;
  calls_tools: boolean;
  calls_llm: boolean;
  required_config_keys: string[];
  required_config_any: string[];
  security_requirements: string[];
  project_visibility_implications: string[];
};

export type FlowNodeRegistryPayload = {
  schema_version: string;
  items: FlowNodeContract[];
};

export type FlowNodeCatalogItem = {
  id: string;
  node_type: FlowNodeType;
  binding_type: string;
  binding_ref: string;
  display_name: string;
  category: string;
  icon_hint: string;
  description: string;
  config_schema: Record<string, unknown>;
  input_schema: Record<string, string>;
  output_schema: Record<string, string>;
  availability_status: "available" | "disabled";
  disabled_reason?: string | null;
  permission_requirements: string[];
  token_cost_risk: "low" | "medium" | "high" | string;
  evidence_behavior: string;
  audit_behavior: string;
  default_config: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type FlowNodeCatalogPayload = {
  schema_version: string;
  project_id: string | null;
  project_name: string;
  user_id: string;
  include_disabled: boolean;
  items: FlowNodeCatalogItem[];
  counts: {
    total: number;
    available: number;
    disabled: number;
  };
};

export type FlowValidationIssue = {
  code: string;
  message: string;
};

export type FlowValidationReport = {
  valid: boolean;
  errors: FlowValidationIssue[];
  warnings: FlowValidationIssue[];
  node_count: number;
  edge_count: number;
  node_types: string[];
};

export type FlowDefinitionVersion = {
  id: string;
  flow_id: string;
  version: number;
  status: string;
  definition: FlowDefinitionJson;
  validation_report: FlowValidationReport;
  publish_metadata: Record<string, unknown>;
  runtime_settings: Record<string, unknown>;
  policy_bindings: Record<string, unknown>;
  created_at: string | null;
  published_at: string | null;
};

export type FlowCapability = {
  tool_name: string;
  flow_id: string;
  flow_key: string;
  name: string;
  description: string;
  version_id: string;
  version: number;
  project_id: string | null;
  available: boolean;
  hidden_reason?: string | null;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  process_summary?: Array<Record<string, unknown>>;
  purpose: string;
  evidence_contract: Record<string, unknown>;
  limitations: string[];
  examples: string[];
  cost_budget_hint: Record<string, unknown>;
  approval_requirements: Record<string, unknown>;
  publish_metadata: Record<string, unknown>;
};

export type FlowCapabilityListPayload = {
  items: FlowCapability[];
};

export type FlowDefinitionRow = {
  id: string;
  key: string;
  name: string;
  description: string;
  project_id: string | null;
  status: string;
  is_active: boolean;
  current_version_id: string | null;
  latest_version: number | null;
  created_at: string | null;
  updated_at: string | null;
  versions?: FlowDefinitionVersion[];
};
