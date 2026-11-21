import { useRef } from "react";

import { useAdminBootstrapUserApproval } from "./useAdminBootstrapUserApproval";
import { useAdminConnectorManagement } from "./useAdminConnectorManagement";
import { useAdminMcpManagement } from "./useAdminMcpManagement";
import { useAdminModeScenarioForms } from "./useAdminModeScenarioForms";
import { useAdminProjectDesignTrace } from "./useAdminProjectDesignTrace";
import { useAdminProjectQualityCore } from "./useAdminProjectQualityCore";
import { useAdminProviderManagement } from "./useAdminProviderManagement";
import { useAdminRuntimeManagement } from "./useAdminRuntimeManagement";
import { useAdminTabLoader } from "./useAdminTabLoader";
import { useAdminTaskWorkflow } from "./useAdminTaskWorkflow";
import type { ReadJsonFn } from "./useAdminTabLoader.types";
import type { AdminTab } from "../types/adminPanelTypes.governance";

type ContainerControllersParams = {
  onApprovalStateChanged?: (sessionId?: string | null) => void;
  providers: any[];
  setProviders: (value: any[]) => void;
  setLoadingTab: (value: boolean) => void;
  setTabError: (value: string | null) => void;
  // Lets setup-guide actions open another page of the same area.
  setTab?: (tab: AdminTab) => void;
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
  localBootstrapState: Record<string, any>;
  mcpState: Record<string, any>;
  modeScenarioState: Record<string, any>;
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
    setTab: params.setTab,
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
    ...params.localBootstrapState,
    ...params.mcpState,
    ...params.modeScenarioState,
    ...params.officeTemplates,
    ...params.projectState,
    ...params.providerState,
    ...params.runtimeState,
    ...params.taskState,
    ...params.usageBrandingState,
    ...params.webhookState,
    ...params.workflowState,
  };

  const loadLocalBootstrapStateRef = useRef<() => Promise<void>>(
    async () => {},
  );
  const loadSetupGuideRef = useRef<() => Promise<void>>(async () => {});

  const loadTab = useAdminTabLoader({
    ...baseParams,
    loadLocalBootstrapState: () => loadLocalBootstrapStateRef.current(),
    loadSetupGuide: () => loadSetupGuideRef.current(),
  } as any);

  const bootstrapControllers = useAdminBootstrapUserApproval({
    ...baseParams,
    loadTab,
  } as any);
  loadLocalBootstrapStateRef.current =
    bootstrapControllers.loadLocalBootstrapState;
  loadSetupGuideRef.current = bootstrapControllers.loadSetupGuide;

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

  const modeScenarioControllers = useAdminModeScenarioForms(baseParams as any);
  const providerManagement = useAdminProviderManagement({
    ...baseParams,
    loadLocalBootstrapState: bootstrapControllers.loadLocalBootstrapState,
    loadSetupGuide: bootstrapControllers.loadSetupGuide,
    refreshBootstrapContext: bootstrapControllers.refreshBootstrapContext,
  } as any);
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
    modeScenarioControllers,
    projectDesignTrace,
    projectQualityCore,
    providerManagement,
    runtimeManagement,
    taskWorkflowControllers,
  };
}
