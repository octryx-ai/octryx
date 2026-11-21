// The status line of a configured connector card. Pure: no React.
//
// "Connected" is a claim about the connection, so it needs a successful health check: a failing check shows
// the problem instead ("Connection failing: HTTP 401 …"), and no check yet says so. "Credentials stored" (the
// line below) stays factual either way. Health comes from the connector health API (status "ok" | "error").

export type ConnectorStatusTone = "ok" | "error" | "neutral";

export type ConnectorStatusLine = {
  text: string;
  tone: ConnectorStatusTone;
  /** The health error is already in the status line, so the "Last checked" line leaves it out. */
  errorInStatus: boolean;
};

type ConnectorLike = {
  tool_name?: unknown;
  configured?: unknown;
  is_active?: unknown;
  // How many Workspace connections (named or own default) the connector has; a card without a global entry.
  workspace_connections?: number;
  // Whether the platform has a connection test for this preset.
  connection_test_available?: unknown;
};
type HealthLike = { status?: unknown; error?: unknown } | null | undefined;

/**
 * Whether this preset can be tested at all. The explicit `connection_test_available` wins; without it, a
 * preset whose recorded health error is the fixed "not implemented" text of
 * connector_test_service.run_connector_connection_test for this tool (matched exactly, never a substring) is not
 * testable.
 */
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

/** Automation → Connectors shows a card for a connector with a global entry, one that Workspaces hold accounts for
 * (their connections are listed read-only in its drawer), and the one being opened. */
export function connectorCardShown(connector: ConnectorLike, expanded: string | null | undefined): boolean {
  return Boolean(connector.configured) || (connector.workspace_connections ?? 0) > 0
    || (expanded != null && expanded === connector.tool_name);
}
