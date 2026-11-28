import { resolveAdminTabLabel } from "../config/adminPanelTabs";
import {
  CONNECTOR_COLORS,
  CONNECTOR_ICONS,
  getChannelIconColor,
  getMcpIconColor,
  renderChannelIcon,
  renderMcpIcon,
} from "../config/adminPanelVisuals";
import {
  connectorHealthStatusClass,
  formatConnectorHealthStatus,
  formatDateTime,
  formatRelativeTime,
  getAgentModeLabel,
} from "../utils/formatters";
import { OUTBOUND_WEBHOOK_EVENT_OPTIONS } from "../types/adminPanelTypes.governance";
import { RUNTIME_PANEL_SECTIONS } from "../types/adminPanelTypes.runtimeCorp";
import { buildAdminPanelTabContexts } from "./useAdminPanelTabContexts";
import { useAdminCatalogFilters } from "./useAdminCatalogFilters";
import { useAdminUsageAndUiActions } from "./useAdminUsageAndUiActions";
import type { ReadJsonFn } from "./useAdminTabLoader.types";
import type { AdminTab } from "../types/adminPanelTypes.governance";

type ContainerDerivedParams = {
  onClose: () => void;
  projects: any[];
  providers: any[];
  tab: AdminTab;
  users: any[];
  currentUserId?: string;
  agentForms: Record<string, any>;
  agentState: Record<string, any>;
  channelState: Record<string, any>;
  connectorCoreState: Record<string, any>;
  connectorFormState: Record<string, any>;
  controllers: {
    bootstrapControllers: Record<string, any>;
    connectorControllers: Record<string, any>;
    mcpControllers: Record<string, any>;
    projectDesignTrace: Record<string, any>;
    projectQualityCore: Record<string, any>;
    providerManagement: Record<string, any>;
    runtimeManagement: Record<string, any>;
    taskWorkflowControllers: Record<string, any>;
    loadTab: (tab: AdminTab) => Promise<void>;
  };
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
};

export function useAdminPanelContainerDerived(params: ContainerDerivedParams) {
  const flatParams = {
    CONNECTOR_COLORS,
    CONNECTOR_ICONS,
    OUTBOUND_WEBHOOK_EVENT_OPTIONS,
    RUNTIME_PANEL_SECTIONS,
    connectorHealthStatusClass,
    formatConnectorHealthStatus,
    formatDateTime,
    formatRelativeTime,
    getAgentModeLabel,
    getChannelIconColor,
    getMcpIconColor,
    onClose: params.onClose,
    projects: params.projects,
    providers: params.providers,
    readJson: params.readJson,
    renderChannelIcon,
    renderMcpIcon,
    tab: params.tab,
    users: params.users,
    currentUserId: params.currentUserId,
    ...params.agentForms,
    ...params.agentState,
    ...params.channelState,
    ...params.connectorCoreState,
    ...params.connectorFormState,
    ...params.controllers.bootstrapControllers,
    ...params.controllers.connectorControllers,
    ...params.controllers.mcpControllers,
    ...params.controllers.projectDesignTrace,
    ...params.controllers.projectQualityCore,
    ...params.controllers.providerManagement,
    ...params.controllers.runtimeManagement,
    ...params.controllers.taskWorkflowControllers,
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
    loadTab: params.controllers.loadTab,
  };

  const usageActions = useAdminUsageAndUiActions(flatParams as any);
  const catalogFilters = useAdminCatalogFilters(flatParams as any);

  const activeRuntimePanelSection =
    RUNTIME_PANEL_SECTIONS.find(
      (section) => section.id === params.runtimeState.runtimePanelSection,
    ) || RUNTIME_PANEL_SECTIONS[0];

  const providersTabCtx = {
    ...params.controllers.providerManagement,
    ...params.providerState,
    providers: params.providers,
  };

  const runtimesTabCtx = {
    ...params.controllers.runtimeManagement,
    ...params.officeTemplates,
    ...params.runtimeState,
    activeRuntimePanelSection,
    formatRelativeTime,
    projects: params.projects,
    providers: params.providers,
    readJson: params.readJson,
    RUNTIME_PANEL_SECTIONS,
  };

  const otherTabContexts = buildAdminPanelTabContexts({
    ...flatParams,
    ...usageActions,
    ...catalogFilters,
    agentForms: params.agentForms,
    channelState: params.channelState,
    taskState: params.taskState,
    usageBrandingState: params.usageBrandingState,
    webhookState: params.webhookState,
  } as any);

  return {
    ...catalogFilters,
    ...otherTabContexts,
    ...usageActions,
    currentTabLabel: resolveAdminTabLabel(params.tab as AdminTab),
    providersTabCtx,
    runtimesTabCtx,
  };
}
