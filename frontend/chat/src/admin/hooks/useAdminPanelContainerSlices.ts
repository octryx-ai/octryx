import { useAdminAgentState } from "./useAdminAgentState";
import { useAdminChannelState } from "./useAdminChannelState";
import { useAdminConnectorCoreState } from "./useAdminConnectorCoreState";
import { useAdminConnectorFormState } from "./useAdminConnectorFormState";
import { useAdminCorpIdentity } from "./useAdminCorpIdentity";
import { useAdminCreateUserState } from "./useAdminCreateUserState";
import { useAdminEngineeringKnowledgePacks } from "./useAdminEngineeringKnowledgePacks";
import { useAdminKnowledgeState } from "./useAdminKnowledgeState";
import { useAdminLocalBootstrapState } from "./useAdminLocalBootstrapState";
import { useAdminMcpState } from "./useAdminMcpState";
import { useAdminModeScenarioState } from "./useAdminModeScenarioState";
import { useAdminOfficeTemplates } from "./useAdminOfficeTemplates";
import { useAdminProjectState } from "./useAdminProjectState";
import { useAdminProviderState } from "./useAdminProviderState";
import { useAdminRuntimeState } from "./useAdminRuntimeState";
import { useAdminTaskState } from "./useAdminTaskState";
import { useAdminUsageBrandingState } from "./useAdminUsageBrandingState";
import { useAdminWebhookState } from "./useAdminWebhookState";
import { useAdminWorkflowState } from "./useAdminWorkflowState";
import { sanitizeOfficeTemplateKey } from "../utils/adminPanelHelpers";
import type { ReadJsonFn } from "./useAdminTabLoader.types";

// `isAdmin`: only an admin loads the admin-only lists; a member's page never asks for what it may not read (no 403).
export function useAdminPanelContainerSlices(readJson: ReadJsonFn, isAdmin = true) {
  const projectState = useAdminProjectState();
  const localBootstrapState = useAdminLocalBootstrapState();
  const agentState = useAdminAgentState();
  const webhookState = useAdminWebhookState();
  const usageBrandingState = useAdminUsageBrandingState();
  const taskState = useAdminTaskState();
  const baseKnowledgeState = useAdminKnowledgeState();
  const engineeringKnowledgeState = useAdminEngineeringKnowledgePacks(readJson);
  const knowledgeState = {
    ...baseKnowledgeState,
    ...engineeringKnowledgeState,
  };
  const channelState = useAdminChannelState();
  const mcpState = useAdminMcpState();
  const runtimeState = useAdminRuntimeState();
  const connectorCoreState = useAdminConnectorCoreState();
  const modeScenarioState = useAdminModeScenarioState();
  const connectorFormState = useAdminConnectorFormState();
  const workflowState = useAdminWorkflowState();
  const providerState = useAdminProviderState();
  const createUserState = useAdminCreateUserState();
  const officeTemplates = useAdminOfficeTemplates({
    sanitizeTemplateKey: sanitizeOfficeTemplateKey,
  });
  const corpIdentity = useAdminCorpIdentity({ readJson, enabled: isAdmin });

  return {
    projectState,
    localBootstrapState,
    agentState,
    webhookState,
    usageBrandingState,
    taskState,
    knowledgeState,
    channelState,
    mcpState,
    runtimeState,
    connectorCoreState,
    modeScenarioState,
    connectorFormState,
    workflowState,
    providerState,
    createUserState,
    officeTemplates,
    corpIdentity,
  };
}
