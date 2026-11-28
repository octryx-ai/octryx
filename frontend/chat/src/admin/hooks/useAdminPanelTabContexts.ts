import {
  buildBrandingTabCtx,
  buildChannelsTabCtx,
  buildMcpTabCtx,
  buildTtsTabCtx,
  buildWebhooksTabCtx,
} from "./useAdminTabContextsIntegration";
import {
  buildKnowledgeTabCtx,
  buildUsersTabCtx,
} from "./useAdminTabContextsGovernance";
import {
  buildAgentsTabCtx,
  buildProjectsTabCtx,
} from "./useAdminTabContextsProjectAgent";
import {
  buildConnectorsTabCtx,
  buildSchedulersTabCtx,
  buildTasksTabCtx,
  buildToolCatalogTabCtx,
} from "./useAdminTabContextsOperations";

// The tasks tab reads the task state plus the step form fields and the task and step handlers.
function tasksTabInput(p: Record<string, any>) {
  return {
    ...p.taskState,
    editingStep: p.editingStep,
    agentModeNameByKey: p.agentForms.agentModeNameByKey,
    availableAgentModes: p.agentForms.availableAgentModes,
    loadTaskRuns: p.loadTaskRuns,
    onAddTaskDependency: p.handleAddTaskDependency,
    onCancelRun: p.handleCancelRun,
    onCloseTaskForm: p.closeTaskForm,
    onDeleteStep: p.handleDeleteStep,
    onDeleteTask: p.handleDeleteTask,
    onDeleteTaskDependency: p.handleDeleteTaskDependency,
    onExpandSteps: p.handleExpandSteps,
    onExpandTask: p.handleExpandTask,
    onMoveStep: p.handleMoveStep,
    onOpenStepForm: p.handleOpenStepForm,
    onOpenTaskForm: p.handleOpenTaskForm,
    onSaveStep: p.handleSaveStep,
    onSaveTask: p.handleSaveTask,
    onToggleTask: p.handleToggleTask,
    onTriggerTask: p.handleTriggerTask,
    panelAgents: p.panelAgents,
    projects: p.projects,
    setEditingStep: p.setEditingStep,
    setShowStepForm: p.setShowStepForm,
    setStepFormAgentId: p.setStepFormAgentId,
    setStepFormConnector: p.setStepFormConnector,
    setStepFormConnectorAction: p.setStepFormConnectorAction,
    setStepFormConnectorParams: p.setStepFormConnectorParams,
    setStepFormContextFields: p.setStepFormContextFields,
    setStepFormInstructions: p.setStepFormInstructions,
    setStepFormMaxFix: p.setStepFormMaxFix,
    setStepFormName: p.setStepFormName,
    setStepFormTimeout: p.setStepFormTimeout,
    setStepFormType: p.setStepFormType,
    showStepForm: p.showStepForm,
    stepFormAgentId: p.stepFormAgentId,
    stepFormConnector: p.stepFormConnector,
    stepFormConnectorAction: p.stepFormConnectorAction,
    stepFormConnectorParams: p.stepFormConnectorParams,
    stepFormContextFields: p.stepFormContextFields,
    stepFormError: p.stepFormError,
    stepFormInstructions: p.stepFormInstructions,
    stepFormLoading: p.stepFormLoading,
    stepFormMaxFix: p.stepFormMaxFix,
    stepFormName: p.stepFormName,
    stepFormTimeout: p.stepFormTimeout,
    stepFormType: p.stepFormType,
    taskSteps: p.taskSteps,
  };
}

// Webhooks, channels, MCP and text-to-speech tabs, built in this order.
function integrationTabContexts(p: Record<string, any>) {
  const webhooksTabCtx = buildWebhooksTabCtx({
    ...p.webhookState,
    availableAgentModes: p.agentForms.availableAgentModes,
    formatDateTime: p.formatDateTime,
    outboundWebhookEventOptions: p.OUTBOUND_WEBHOOK_EVENT_OPTIONS,
    projects: p.projects,
    readJson: p.readJson,
    loadTab: p.loadTab,
  });
  const channelsTabCtx = buildChannelsTabCtx({
    ...p.channelState,
    filteredAvailableChannels: p.filteredAvailableChannels,
    formatRelativeTime: p.formatRelativeTime,
    getChannelIconColor: p.getChannelIconColor,
    projects: p.projects,
    readJson: p.readJson,
    loadTab: p.loadTab,
    renderChannelIcon: p.renderChannelIcon,
  });
  const mcpTabCtx = buildMcpTabCtx(p as any);
  const ttsTabCtx = buildTtsTabCtx({
    onSaveSecrets: p.handleSaveTtsSecrets,
    onToggleGlobal: p.handleToggleTtsGlobal,
    onToggleProvider: p.handleToggleTtsProvider,
    setTtsSecrets: p.setTtsSecrets,
    ttsConfig: p.ttsConfig,
    ttsFormError: p.ttsFormError,
    ttsFormLoading: p.ttsFormLoading,
    ttsFormSaved: p.ttsFormSaved,
    ttsSecrets: p.ttsSecrets,
    readJson: p.readJson,
    loadTab: p.loadTab,
  });
  return { webhooksTabCtx, channelsTabCtx, mcpTabCtx, ttsTabCtx };
}

// Projects, users, knowledge and branding tabs, built in this order.
function workspaceTabContexts(p: Record<string, any>) {
  const projectsTabCtx = buildProjectsTabCtx({
    ...p,
    onClose: p.onClose,
  } as any);
  const usersTabCtx = buildUsersTabCtx({
    ...p,
    onCreateUser: p.handleCreateUser,
    onDeactivateUser: p.handleDeactivateUser,
    onResetUserPassword: p.handleResetUserPassword,
    onRoleChange: p.handleRoleChange,
    onUpdateUser: p.handleUpdateUser,
  } as any);
  const knowledgeTabCtx = buildKnowledgeTabCtx({
    ...p,
  });
  const brandingTabCtx = buildBrandingTabCtx({
    ...p,
    onSaveBranding: p.handleSaveBranding,
  });
  return {
    projectsTabCtx,
    usersTabCtx,
    knowledgeTabCtx,
    brandingTabCtx,
  };
}

export function buildAdminPanelTabContexts(params: Record<string, unknown>) {
  const p = params as Record<string, any>;
  const connectorsTabCtx = buildConnectorsTabCtx(p as any);
  const toolCatalogTabCtx = buildToolCatalogTabCtx(p as any);
  const agentsTabCtx = buildAgentsTabCtx(p as any);
  const schedulersTabCtx = buildSchedulersTabCtx({
    ...p,
    onCloseSchedulerForm: p.closeSchedulerForm,
    onCreateScheduler: p.handleCreateScheduler,
    onDeleteScheduler: p.handleDeleteScheduler,
    onOpenSchedulerForm: p.handleOpenSchedulerForm,
    onSaveScheduler: p.handleSaveScheduler,
    onToggleScheduler: p.handleToggleScheduler,
  });
  const tasksTabCtx = buildTasksTabCtx(tasksTabInput(p));
  const { webhooksTabCtx, channelsTabCtx, mcpTabCtx, ttsTabCtx } =
    integrationTabContexts(p);
  const skillsTabCtx = {
    readJson: p.readJson,
  };
  const {
    projectsTabCtx,
    usersTabCtx,
    knowledgeTabCtx,
    brandingTabCtx,
  } = workspaceTabContexts(p);

  return {
    connectorsTabCtx,
    toolCatalogTabCtx,
    agentsTabCtx,
    schedulersTabCtx,
    tasksTabCtx,
    webhooksTabCtx,
    channelsTabCtx,
    mcpTabCtx,
    ttsTabCtx,
    skillsTabCtx,
    projectsTabCtx,
    usersTabCtx,
    knowledgeTabCtx,
    brandingTabCtx,
  };
}
