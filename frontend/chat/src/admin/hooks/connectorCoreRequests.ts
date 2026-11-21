// Connector requests: expand (draft + health history), save with the secret rebind refusal, test, delete, pause.
import type { AdminConnector, AdminConnectorHealthLog } from "../types/adminPanelTypes.usersProviders";
import type { UseAdminConnectorManagementArgs } from "./useAdminConnectorManagement.types";
import { SECRET_REBIND_REQUIRED, SecretRebindRequiredError } from "../secretRebind/secretRebindModel";
import type { SecretRebindRefusal } from "../secretRebind/secretRebindModel";

type Args = UseAdminConnectorManagementArgs;

// A save either stores the connector, is refused with the explicit secret_rebind_required state (the refused body
// travels back so the confirm step can resend it unchanged), or fails with an already reported error.
export type ConnectorSaveOutcome =
  | { state: "saved" }
  | { state: typeof SECRET_REBIND_REQUIRED; refusal: SecretRebindRefusal; body: Record<string, unknown> }
  | { state: "failed" };

function withoutKey<T>(prev: Record<string, T>, key: string) {
  const next = { ...prev };
  delete next[key];
  return next;
}

// Public fields as editable text: scalars as strings, lists and objects as indented JSON.
function connectorFieldDraft(connector: AdminConnector) {
  const draft: Record<string, string> = {};
  for (const [key, value] of Object.entries(connector.public_fields)) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      draft[key] = String(value);
    } else if (value !== null && value !== undefined) {
      draft[key] = JSON.stringify(value, null, 2);
    }
  }
  return draft;
}

async function loadConnectorHealthHistory(a: Args, toolName: string) {
  a.setConnectorHealthLoading(toolName);
  try {
    const history = await a.readJson<AdminConnectorHealthLog[]>(
      `/admin/chat/api/panel/connectors/${toolName}/health-log`,
    );
    a.setConnectorHealthHistory((prev) => ({ ...prev, [toolName]: history }));
  } catch {
    a.setConnectorHealthHistory((prev) => ({ ...prev, [toolName]: [] }));
  } finally {
    a.setConnectorHealthLoading((current) => (current === toolName ? null : current));
  }
}

export function expandConnector(
  a: Args,
  toolName: string,
  connector: AdminConnector,
  loadGithubRepositories: () => Promise<void>,
) {
  if (a.expandedConnector === toolName) {
    a.setExpandedConnector(null);
    return;
  }
  a.setExpandedConnector(toolName);
  const draft = connectorFieldDraft(connector);
  a.setConnectorDraft((prev) => ({ ...prev, [toolName]: draft }));
  a.setConnectorPolicyDraft((prev) => ({
    ...prev,
    [toolName]: {
      tool_instructions: connector.tool_policy.tool_instructions || "",
      extra_tools: [...(connector.tool_policy.extra_tools || [])],
      disabled_tools: [...(connector.tool_policy.disabled_tools || [])],
    },
  }));
  if (!(toolName in a.connectorHealthHistory)) {
    void loadConnectorHealthHistory(a, toolName);
  }
  if (toolName === "github" && connector.configured && a.githubConnectorRepositories.length === 0) {
    void loadGithubRepositories();
  }
}

export async function saveConnector(
  a: Args,
  toolName: string,
  connector: AdminConnector,
  buildBody: () => Record<string, unknown>,
): Promise<ConnectorSaveOutcome> {
  a.setConnectorSaving(toolName);
  const body = buildBody();
  try {
    const updated = await a.readJson<AdminConnector>(
      `/admin/chat/api/panel/connectors/${toolName}`,
      { method: "PUT", body: JSON.stringify(body) },
    );
    a.setConnectors((prev) => prev.map((item) => (item.tool_name === toolName ? updated : item)));
    // A stored secret is never kept in the draft: the next save keeps it unless a new value is typed.
    a.setConnectorDraft((prev) => {
      const next = { ...(prev[toolName] || {}) };
      for (const field of connector.secret_fields) delete next[field];
      return { ...prev, [toolName]: next };
    });
    a.setConnectorTestResult((prev) => withoutKey(prev, toolName));
    return { state: "saved" };
  } catch (err) {
    if (err instanceof SecretRebindRequiredError) {
      return { state: SECRET_REBIND_REQUIRED, refusal: err.refusal, body };
    }
    alert(err instanceof Error ? err.message : "Save failed");
    return { state: "failed" };
  } finally {
    a.setConnectorSaving(null);
  }
}

export async function testConnector(a: Args, toolName: string) {
  a.setConnectorTesting(toolName);
  try {
    const result = await a.readJson<{ ok: boolean; summary: string; details?: string }>(
      `/admin/chat/api/panel/connectors/${toolName}/test`,
      { method: "POST" },
    );
    a.setConnectorTestResult((prev) => ({ ...prev, [toolName]: result }));
    const connectorData = await a.readJson<AdminConnector[]>("/admin/chat/api/panel/connectors");
    a.setConnectors(connectorData);
    const history = await a.readJson<AdminConnectorHealthLog[]>(
      `/admin/chat/api/panel/connectors/${toolName}/health-log`,
    );
    a.setConnectorHealthHistory((prev) => ({ ...prev, [toolName]: history }));
  } catch (err) {
    a.setConnectorTestResult((prev) => ({
      ...prev,
      [toolName]: { ok: false, summary: err instanceof Error ? err.message : "Test failed" },
    }));
  } finally {
    a.setConnectorTesting(null);
  }
}

// Confirmed in the shared ConfirmDialog (typed name); the server refuses while the connector is
// used. A refusal is thrown to the dialog, which shows it in place.
export async function deleteConnector(a: Args, toolName: string, confirmName: string) {
  await a.readJson(
    `/admin/chat/api/panel/connectors/${toolName}?confirm_name=${encodeURIComponent(confirmName)}`,
    { method: "DELETE" },
  );
  a.setExpandedConnector(null);
  a.setConnectors((prev) =>
    prev.map((item) =>
      item.tool_name === toolName
        ? {
            ...item,
            configured: false,
            is_active: false,
            policy_id: null,
            tool_policy: { tool_instructions: "", extra_tools: [], disabled_tools: [] },
            tools: item.builtin_tools,
            public_fields: {},
            secret_status: {},
          }
        : item,
    ),
  );
  a.setConnectorDraft((prev) => withoutKey(prev, toolName));
  a.setConnectorPolicyDraft((prev) => withoutKey(prev, toolName));
  a.setConnectorTestResult((prev) => withoutKey(prev, toolName));
  a.setConnectorHealthHistory((prev) => withoutKey(prev, toolName));
}

// Pause/Resume flips only is_active (a full save would rewrite the connector's policy).
export async function setConnectorActive(a: Args, toolName: string, isActive: boolean) {
  const updated = await a.readJson<{ is_active: boolean }>(
    `/admin/chat/api/panel/connectors/${toolName}/active`,
    { method: "POST", body: JSON.stringify({ is_active: isActive }) },
  );
  a.setConnectors((prev) =>
    prev.map((item) => (item.tool_name === toolName ? { ...item, is_active: updated.is_active } : item)),
  );
}
