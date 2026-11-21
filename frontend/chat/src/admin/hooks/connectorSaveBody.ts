import { atlassianAuthSaveFields } from "../components/connectorsTab/atlassianAuthModel";
import { authOwnedFields } from "../components/connectorsTab/atlassianAuthModes";
import { jiraSaveFields } from "../components/connectorsTab/jiraConnectorSetupModel";
import { serviceNowApiOwnedFields, serviceNowApiSaveFields } from "../components/connectorsTab/serviceNowApiModel";
import { serviceNowAuthSaveFields, serviceNowOwnedFields } from "../components/connectorsTab/serviceNowAuthModel";
import { LIMIT_FIELDS, serviceNowGroupsSaveFields } from "../components/connectorsTab/serviceNowGroupsModel";
import type { AdminConnector } from "../types/adminPanelTypes.usersProviders";
import type { ConnectorPolicyDraft } from "./useAdminConnectorManagement.types";

// The JSON body of the admin connector save (PUT /admin/chat/api/panel/connectors/{tool}), built from the draft.
// An empty field is left out; a blank secret field therefore keeps the stored secret. Jira is built by its
// guided setup model, which can also send an explicit clear (""). Confluence's URL and sign-in come
// from the shared Atlassian model, ServiceNow's from its sign-in, API and assignment-group models;
// their other fields keep the generic handling below.

const JSON_CONFIG_FIELDS = new Set([
  "knowledge_import_scope",
  "knowledge_import_limits",
  "knowledge_import_retention",
]);

const BOOLEAN_CONFIG_FIELDS = new Set([
  "k8s_use_kubectl",
  "k8s_verify_tls",
  "knowledge_import_enabled",
]);

function isJsonConfigField(field: string) {
  return (
    field.includes("_allowed_") ||
    field.includes("_repos") ||
    field.includes("_spaces") ||
    field.includes("_pages") ||
    JSON_CONFIG_FIELDS.has(field)
  );
}

function parseBooleanConfigValue(value: unknown) {
  return String(value ?? "")
    .trim()
    .toLowerCase() === "true";
}

export function buildConnectorSaveBody(
  connector: AdminConnector,
  draft: Record<string, string>,
  policyDraft: ConnectorPolicyDraft,
): Record<string, unknown> {
  const body: Record<string, unknown> = { is_active: true };
  if (connector.tool_name === "jira") Object.assign(body, jiraSaveFields(connector, draft));
  if (connector.tool_name === "confluence") Object.assign(body, atlassianAuthSaveFields("confluence", connector, draft));
  if (connector.tool_name === "servicenow") {
    Object.assign(
      body,
      serviceNowAuthSaveFields(connector, draft),
      serviceNowApiSaveFields(connector, draft),
      serviceNowGroupsSaveFields(connector, draft),
    );
  }
  const guided =
    connector.tool_name === "confluence"
      ? new Set(authOwnedFields("confluence"))
      : connector.tool_name === "servicenow"
        ? new Set([...serviceNowOwnedFields(), ...serviceNowApiOwnedFields(), ...LIMIT_FIELDS])
        : null;
  const genericFields =
    connector.tool_name === "jira" ? [] : connector.fields.filter((field) => !guided?.has(field));
  for (const field of genericFields) {
    const val = draft[field];
    if (val === undefined || val === "") continue;
    if (BOOLEAN_CONFIG_FIELDS.has(field)) {
      body[field] = parseBooleanConfigValue(val);
      continue;
    }
    if (isJsonConfigField(field)) {
      try {
        body[field] = JSON.parse(val);
        continue;
      } catch {
        // Keep as string if JSON parse fails.
      }
    }
    body[field] = val;
  }
  body.tool_policy = {
    tool_instructions: policyDraft.tool_instructions,
    extra_tools: policyDraft.extra_tools,
    disabled_tools: policyDraft.disabled_tools,
  };
  body.policy_active = true;
  return body;
}
