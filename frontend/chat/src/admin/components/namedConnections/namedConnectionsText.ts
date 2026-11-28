import { formatDateTime } from "../../utils/dateTime";
import type { ConnectionUsage, LastTest, NamedConnection, NamedConnector } from "./namedConnectionsTypes";
import { scopeLabel } from "./namedConnectionsForm";

export function refusalText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "The request failed.";
}

export function storedSecretsText(connection: Pick<NamedConnection, "secretStatus">): string {
  const stored = Object.entries(connection.secretStatus).filter(([, value]) => value).length;
  return stored ? "Credential stored" : "No credential stored";
}

const AUTH_MODE_LABELS: Record<string, string> = {
  cloud_api_token: "Atlassian Cloud (API token)",
  basic: "Username and password",
  bearer_pat: "Personal access token",
  bearer_token: "Bearer token",
  oauth_password: "OAuth (username and password)",
  oidc_client_credentials: "OpenID Connect (client credentials)",
};

export function connectionTarget(connector: NamedConnector, fields: Record<string, unknown>): string | null {
  const value = fields[connector.urlField];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function authModeLabel(connector: NamedConnector, fields: Record<string, unknown>): string {
  const mode = connector.fields.find((field) => field.kind === "select" && field.name.endsWith("_auth_mode"));
  if (!mode) return "Sign-in by its own credential";
  const value = fields[mode.name];
  if (typeof value !== "string" || !value) return "Sign-in not set";
  return AUTH_MODE_LABELS[value] ?? value;
}

export function lastTestText(lastTest: LastTest | null): string {
  if (!lastTest) return "Not tested since the last change";
  const when = lastTest.at ? ` (${formatDateTime(lastTest.at, lastTest.at)})` : "";
  const said = lastTest.summary ? `: ${lastTest.summary}` : "";
  return `${lastTest.ok ? "Last test passed" : "Last test failed"}${when}${said}`;
}

export function usageLines(usage: ConnectionUsage | null, connector: NamedConnector): string[] {
  if (!usage) return [];
  const label = scopeLabel(connector).plural.toLowerCase();
  const lines = usage.workspaces.map(
    (workspace) => `Workspace "${workspace.name}" (${label}: ${workspace.scopes.join(", ")})`,
  );
  for (const item of usage.knowledgeConnectors) {
    const pin = item.pinned ? (item.pinMismatch ? ", pinned — runs refused: its items resolve elsewhere" : ", pinned") : "";
    const keys = item.scopes.length ? ` (${label}: ${item.scopes.join(", ")})` : "";
    lines.push(`Knowledge connector "${item.connectorKey}" in "${item.workspaceName}"${keys}${pin}`);
  }
  for (const item of usage.workIntakes ?? []) lines.push(`Work intake "${item.name}" in "${item.workspaceName}"`);
  return lines;
}

export function deleteConsequence(connection: NamedConnection, connector: NamedConnector): string {
  const label = scopeLabel(connector);
  const users = usageLines(connection.usage, connector);
  const after = connection.scope === "global"
    ? `Its ${label.plural.toLowerCase()} then use a Workspace's default connection only where that allows them.`
    : `Its ${label.plural.toLowerCase()} then use the default connection only if it allows them.`;
  const used = users.length ? ` Used by: ${users.join("; ")}.` : " Nothing uses it right now.";
  const pinned = connection.usage?.knowledgeConnectors.some((item) => item.pinned)
    ? " Knowledge connectors pinned to it are refused until they are pinned to another connection."
    : "";
  const intakes = connection.usage?.workIntakes?.length
    ? " Work intakes on it stop until another connection is picked."
    : "";
  return `Delete "${connection.name}" (${connection.id}) and its stored secret?${used} ${after}${pinned}${intakes}`;
}
