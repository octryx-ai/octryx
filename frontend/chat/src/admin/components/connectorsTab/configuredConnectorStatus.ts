// "Connected" needs a successful health check; a failing check shows the problem instead.

export type ConnectorStatusTone = "ok" | "error" | "neutral";

export type ConnectorStatusLine = {
  text: string;
  tone: ConnectorStatusTone;
  errorInStatus: boolean;
};

type ConnectorLike = {
  tool_name?: unknown;
  configured?: unknown;
  is_active?: unknown;
  workspace_connections?: number;
  connection_test_available?: unknown;
};
type HealthLike = { status?: unknown; error?: unknown } | null | undefined;

/** Without `connection_test_available`, the fixed "not implemented" health error (matched exactly) means untestable. */
export function connectionTestAvailable(
  connector: ConnectorLike,
  health: HealthLike,
): boolean {
  if (typeof connector.connection_test_available === "boolean")
    return connector.connection_test_available;
  const tool =
    typeof connector.tool_name === "string" ? connector.tool_name : "";
  const error = typeof health?.error === "string" ? health.error.trim() : "";
  return !(tool && error === `Connection test is not implemented for ${tool}.`);
}

export function configuredConnectorStatus(
  connector: ConnectorLike,
  health: HealthLike,
): ConnectorStatusLine {
  const workspaceConnections = connector.workspace_connections ?? 0;
  if (!connector.configured && workspaceConnections > 0)
    return { text: `Workspace connections only (${workspaceConnections})`, tone: "neutral", errorInStatus: false };
  if (!connector.configured)
    return { text: "Not configured", tone: "neutral", errorInStatus: false };
  if (!connector.is_active)
    return {
      text: "Configured (inactive)",
      tone: "neutral",
      errorInStatus: false,
    };
  // Not "failing": the platform simply has no test for this preset (neutral, the error line is not repeated).
  if (!connectionTestAvailable(connector, health))
    return {
      text: "No connection test available",
      tone: "neutral",
      errorInStatus: true,
    };
  const status = String(health?.status ?? "").toLowerCase();
  if (status === "error") {
    const error = typeof health?.error === "string" ? health.error.trim() : "";
    return {
      text: error ? `Connection failing: ${error}` : "Connection failing",
      tone: "error",
      errorInStatus: Boolean(error),
    };
  }
  if (status === "ok")
    return { text: "Connected", tone: "ok", errorInStatus: false };
  return {
    text: "Configured · connection not checked yet",
    tone: "neutral",
    errorInStatus: false,
  };
}

export function connectorCardShown(connector: ConnectorLike, expanded: string | null | undefined): boolean {
  return Boolean(connector.configured) || (connector.workspace_connections ?? 0) > 0
    || (expanded != null && expanded === connector.tool_name);
}
