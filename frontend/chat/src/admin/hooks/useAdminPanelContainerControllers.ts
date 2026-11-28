import { useAdminBootstrapUserApproval } from "./useAdminBootstrapUserApproval";
import { useAdminConnectorManagement } from "./useAdminConnectorManagement";
import { useAdminMcpManagement } from "./useAdminMcpManagement";
import { useAdminProjectDesignTrace } from "./useAdminProjectDesignTrace";
import { useAdminProjectQualityCore } from "./useAdminProjectQualityCore";
import { useAdminProviderManagement } from "./useAdminProviderManagement";
import { useAdminRuntimeManagement } from "./useAdminRuntimeManagement";
import { useAdminTabLoader } from "./useAdminTabLoader";
import { useAdminTaskWorkflow } from "./useAdminTaskWorkflow";
import type { ReadJsonFn } from "./useAdminTabLoader.types";

type ContainerControllersParams = {
  onApprovalStateChanged?: (sessionId?: string | null) => void;
  providers: any[];
  setProviders: (value: any[]) => void;
  setLoadingTab: (value: boolean) => void;
  setTabError: (value: string | null) => void;
  users: any[];
  setUsers: (value: any[]) => void;
  agentForms: Record<string, any>;
  agentState: Record<string, any>;
  channelState: Record<string, any>;
  connectorCoreState: Record<string, any>;
  connectorFormState: Record<string, any>;
  corpIdentity: Record<string, any>;
  createUserState: Record<string, any>;
  knowledgeState: Record<string, any>;
  mcpState: Record<string, any>;
  officeTemplates: Record<string, any>;
  projectState: Record<string, any>;
  providerState: Record<string, any>;
  runtimeState: Record<string, any>;
  taskState: Record<string, any>;
  usageBrandingState: Record<string, any>;
  webhookState: Record<string, any>;
  workflowState: Record<string, any>;
  readJson: ReadJsonFn;
  sanitizeOfficeTemplateKey: (value: string) => string;
};

export function useAdminPanelContainerControllers(
  params: ContainerControllersParams,
) {
  const baseParams = {
    onApprovalStateChanged: params.onApprovalStateChanged,
    providers: params.providers,
    setProviders: params.setProviders,
    setLoadingTab: params.setLoadingTab,
    setTabError: params.setTabError,
    users: params.users,
    setUsers: params.setUsers,
    readJson: params.readJson,
    sanitizeOfficeTemplateKey: params.sanitizeOfficeTemplateKey,
    ...params.agentForms,
    ...params.agentState,
    ...params.channelState,
    ...params.connectorCoreState,
    ...params.connectorFormState,
    ...params.corpIdentity,
    ...params.createUserState,
    ...params.knowledgeState,
    ...params.mcpState,
    ...params.officeTemplates,
    ...params.projectState,
    ...params.providerState,
    ...params.runtimeState,
    ...params.taskState,
    ...params.usageBrandingState,
    ...params.webhookState,
    ...params.workflowState,
  };

  const loadTab = useAdminTabLoader(baseParams as any);

  const bootstrapControllers = useAdminBootstrapUserApproval({
    ...baseParams,
    loadTab,
  } as any);

  const mcpControllers = useAdminMcpManagement({
    ...baseParams,
    loadTab,
  } as any);

  const projectQualityCore = useAdminProjectQualityCore(baseParams as any);
  const projectDesignTrace = useAdminProjectDesignTrace({
    ...baseParams,
    resetProjectDesignArtifactForm:
      projectQualityCore.resetProjectDesignArtifactForm,
    resetProjectDesignTraceForm: projectQualityCore.resetProjectDesignTraceForm,
  } as any);

  const providerManagement = useAdminProviderManagement(baseParams as any);
  const connectorControllers = useAdminConnectorManagement(baseParams as any);
  const runtimeManagement = useAdminRuntimeManagement(baseParams as any);
  const taskWorkflowControllers = useAdminTaskWorkflow({
    ...baseParams,
    loadTab,
  } as any);

  return {
    bootstrapControllers,
    connectorControllers,
    loadTab: loadTab as (tab: string) => Promise<void>,
    mcpControllers,
    projectDesignTrace,
    projectQualityCore,
    providerManagement,
    runtimeManagement,
    taskWorkflowControllers,
  };
}
