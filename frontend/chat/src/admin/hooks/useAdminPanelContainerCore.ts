// Admin panel container state: the current tab (kept in the URL), users, providers, load state, the state slices
// and agent forms, then the controllers (with the tab-load effects) and the derived tab contexts.
import { useEffect, useState } from "react";
import { adminAgentFormsArgs } from "./adminAgentFormsArgs";
import { useAdminAgentForms } from "./useAdminAgentForms";
import { useAdminPanelContainerControllers } from "./useAdminPanelContainerControllers";
import { useAdminPanelContainerDerived } from "./useAdminPanelContainerDerived";
import { useAdminPanelContainerEffects } from "./useAdminPanelContainerEffects";
import { useAdminPanelContainerSlices } from "./useAdminPanelContainerSlices";
import {
  readJson,
  sanitizeOfficeTemplateKey,
} from "../utils/adminPanelHelpers";
import { resolveAdminAreaTab, type AdminAreaKey } from "../config/adminPanelAreas";
import { writeAreaTabToUrl } from "../../chat/areaNavigation";
import type { AdminProvider, AdminUser } from "../types/adminPanelTypes.usersProviders";
import type { AdminTab } from "../types/adminPanelTypes.governance";
import type { ProjectOption } from "../../chatOptionTypes";

export function useAdminPanelCore(area: AdminAreaKey, initialTab: AdminTab, isAdmin: boolean) {
  const [tab, setTabState] = useState<AdminTab>(() =>
    resolveAdminAreaTab(area, initialTab, isAdmin),
  );
  const setTab = (next: AdminTab) => {
    setTabState(next);
    writeAreaTabToUrl(next);
  };
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [providers, setProviders] = useState<AdminProvider[]>([]);
  const [loadingTab, setLoadingTab] = useState(false);
  const [tabError, setTabError] = useState<string | null>(null);

  const slices = useAdminPanelContainerSlices(readJson, isAdmin);
  const { agentState, connectorCoreState } = slices;

  useEffect(() => {
    const resolved = resolveAdminAreaTab(area, initialTab, isAdmin);
    setTabState(resolved);
    writeAreaTabToUrl(resolved);
  }, [area, initialTab, isAdmin]);

  const agentForms = useAdminAgentForms(
    adminAgentFormsArgs(readJson, connectorCoreState.agentModes, agentState),
  );

  return {
    tab, setTab, users, setUsers, providers, setProviders, loadingTab, setLoadingTab, tabError, setTabError,
    slices, agentForms,
  };
}

type AdminPanelCore = ReturnType<typeof useAdminPanelCore>;

export function useAdminPanelControllers(
  core: AdminPanelCore,
  onApprovalStateChanged: ((sessionId?: string | null) => void) | undefined,
) {
  const { providers, setProviders, setLoadingTab, setTabError, setTab, users, setUsers, agentForms, tab } = core;
  const s = core.slices;
  const controllers = useAdminPanelContainerControllers({
    onApprovalStateChanged,
    providers,
    setProviders,
    setLoadingTab,
    setTabError,
    setTab,
    users,
    setUsers,
    agentForms,
    agentState: s.agentState,
    channelState: s.channelState,
    connectorCoreState: s.connectorCoreState,
    connectorFormState: s.connectorFormState,
    corpIdentity: s.corpIdentity,
    createUserState: s.createUserState,
    knowledgeState: s.knowledgeState,
    localBootstrapState: s.localBootstrapState,
    mcpState: s.mcpState,
    modeScenarioState: s.modeScenarioState,
    officeTemplates: s.officeTemplates,
    projectState: s.projectState,
    providerState: s.providerState,
    runtimeState: s.runtimeState,
    taskState: s.taskState,
    usageBrandingState: s.usageBrandingState,
    webhookState: s.webhookState,
    workflowState: s.workflowState,
    readJson,
    sanitizeOfficeTemplateKey,
  });

  useAdminPanelContainerEffects({
    mcpWorkspaceId: s.mcpState.mcpWorkspaceId,
    loadTab: controllers.loadTab,
    tab,
  });
  return controllers;
}

export function useAdminPanelDerived(
  core: AdminPanelCore,
  controllers: ReturnType<typeof useAdminPanelControllers>,
  { onClose, projects, currentUserId }: { onClose: () => void; projects: ProjectOption[]; currentUserId?: string },
) {
  const { providers, tab, users, agentForms } = core;
  const s = core.slices;
  return useAdminPanelContainerDerived({
    onClose,
    projects,
    providers,
    tab,
    users,
    currentUserId,
    agentForms,
    agentState: s.agentState,
    channelState: s.channelState,
    connectorCoreState: s.connectorCoreState,
    connectorFormState: s.connectorFormState,
    controllers,
    corpIdentity: s.corpIdentity,
    createUserState: s.createUserState,
    knowledgeState: s.knowledgeState,
    localBootstrapState: s.localBootstrapState,
    mcpState: s.mcpState,
    modeScenarioState: s.modeScenarioState,
    officeTemplates: s.officeTemplates,
    projectState: s.projectState,
    providerState: s.providerState,
    runtimeState: s.runtimeState,
    taskState: s.taskState,
    usageBrandingState: s.usageBrandingState,
    webhookState: s.webhookState,
    workflowState: s.workflowState,
    readJson,
  });
}
