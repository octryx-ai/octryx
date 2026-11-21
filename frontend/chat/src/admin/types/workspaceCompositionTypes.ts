export type WorkspaceCapabilityType = {
  id: string;
  kind: string;
  key: string;
  name: string;
  description: string;
  lifecycle_status: string;
  contract: Record<string, unknown>;
  is_active: boolean;
};

export type WorkspaceCapabilityBinding = {
  id: string;
  workspace_id: string;
  capability_type_id: string;
  capability_kind: string;
  binding_key: string;
  display_name: string;
  binding_status: "active" | "hidden" | string;
  is_enabled: boolean;
  is_default: boolean;
  intent_scopes: string[];
  binding_config: Record<string, unknown>;
  policy_config: Record<string, unknown>;
  source_entity_type: string | null;
  source_entity_id: string | null;
  capability_type: WorkspaceCapabilityType | null;
};

export type WorkspaceCompositionPolicy = {
  default_bindings: Record<string, string>;
  routing_policy: Record<string, unknown>;
  delegation_policy: Record<string, unknown>;
  runtime_policy: Record<string, unknown>;
};

export type WorkspaceAssignmentControls = {
  agent_assignment_mode: "all_installed" | "selected_only" | string;
  runtime_assignment_mode: "all_installed" | "selected_only" | string;
  default_agent_binding_key: string;
  default_runtime_binding_key: string;
  available_agent_binding_keys: string[];
  available_runtime_binding_keys: string[];
};

export type WorkspaceCompositionSummary = {
  binding_counts: Record<string, number>;
  enabled_binding_counts: Record<string, number>;
  default_binding_keys: Record<string, string>;
};

export type WorkspaceDiagnosticsWarning = {
  code: string;
  severity: string;
  message: string;
};

export type WorkspaceCompositionDiagnostics = {
  warnings: WorkspaceDiagnosticsWarning[];
};

export type WorkspaceSummaryItem = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
};

export type WorkspaceCompositionPayload = {
  workspace: WorkspaceSummaryItem;
  bindings: WorkspaceCapabilityBinding[];
  policy: WorkspaceCompositionPolicy;
  assignment_controls: WorkspaceAssignmentControls;
  summary: WorkspaceCompositionSummary;
  diagnostics: WorkspaceCompositionDiagnostics;
};

export type WorkspaceBindingUpdatePayload = {
  display_name?: string;
  binding_status?: "active" | "hidden";
  is_enabled?: boolean;
  is_default?: boolean;
  intent_scopes?: string[];
  binding_config?: Record<string, unknown>;
  policy_config?: Record<string, unknown>;
};

export type WorkspacePolicyUpdatePayload = {
  default_bindings?: Record<string, string>;
  routing_policy?: Record<string, unknown>;
  delegation_policy?: Record<string, unknown>;
  runtime_policy?: Record<string, unknown>;
};

export type WorkspaceAssignmentControlsUpdatePayload = {
  agent_assignment_mode?: "all_installed" | "selected_only";
  runtime_assignment_mode?: "all_installed" | "selected_only";
  default_agent_binding_key?: string;
  default_runtime_binding_key?: string;
};
