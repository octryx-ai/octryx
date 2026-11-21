import type { PanelTaskRow } from "../components/taskTypes";
import type {
  AdminDesignArtifact,
  AdminDesignArtifactTemplate,
  AdminDesignReadiness,
  AdminDesignTraceability,
  AdminDesignTraceSyncWorkflow,
  PanelScheduler,
} from "./projectQualityTypes.design";
import type { AdminCodeRepository } from "./projectQualityTypes.code";
import type {
  AdminProjectAgentCatalogItem,
  AdminProjectAgentRoleSummary,
} from "./projectQualityTypes.agents";

export type AdminProjectQuality = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  source_type?: string;
  template_key?: string | null;
  template_version?: string | null;
  template_metadata?: Record<string, unknown>;
  is_system?: boolean;
  // The Instance's default workspace: where people start when they have not chosen one.
  is_default?: boolean;
  repo_code_quality: Record<string, unknown>;
  repository_bootstrap: Record<string, unknown>;
  runtime_policy: Record<string, unknown>;
  effective_runtime_policy: Record<string, unknown>;
  code_repositories?: AdminCodeRepository[];
  design_artifacts?: AdminDesignArtifact[];
  design_artifact_templates?: AdminDesignArtifactTemplate[];
  design_readiness?: AdminDesignReadiness;
  design_traceability?: AdminDesignTraceability;
  design_trace_sync_templates?: AdminDesignTraceSyncWorkflow[];
  design_trace_sync_custom_templates?: AdminDesignTraceSyncWorkflow[];
  design_trace_sync_workflows?: AdminDesignTraceSyncWorkflow[];
  design_trace_sync_tasks?: PanelTaskRow[];
  design_trace_sync_schedulers?: PanelScheduler[];
  project_agent_catalog?: AdminProjectAgentCatalogItem[];
  project_agent_role_summary?: AdminProjectAgentRoleSummary[];
};
