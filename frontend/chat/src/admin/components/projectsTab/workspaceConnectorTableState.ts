// Connector table cells of a Workspace: platform connector state and what serves the Workspace.
/** The platform connector's state in one word for the connector table; the sentence (globalConnectorStatus) is its
 * tooltip. */
export function platformConnectorState(access: { global_configured: boolean; global_active: boolean }): {
  label: string;
  tone: "neutral" | "attention";
} {
  if (!access.global_configured) return { label: "Not set up", tone: "neutral" };
  return access.global_active ? { label: "Ready", tone: "neutral" } : { label: "Off", tone: "attention" };
}

/** The global status as a sentence; for Jira/Confluence without a global entry it points to the own connection. */
export function globalConnectorStatus(
  access: { global_configured: boolean; global_active: boolean },
  ownConnectionPossible: boolean,
): string {
  if (access.global_configured)
    return access.global_active
      ? "configured and active"
      : "configured but inactive";
  return ownConnectionPossible
    ? "not configured · this Workspace can use its own connection"
    : "not configured";
}
/** A named connection of one connector type available in the Workspace (Admin › Connections), for the table below. */
export type AvailableConnection = { type: string; name: string; state: string };

/** The connector table's "In this Workspace" and "Platform connector" cells. A named connection available here serves
 * the Workspace whatever the platform connector says (fresh-install test: GitHub read "Off · Not set up"
 * beside a working "GitHub (demo)" connection). */
export function connectorWorkspaceState(
  access: { connector_name: string; project_enabled: boolean; global_configured: boolean; global_active: boolean },
  connections: AvailableConnection[],
): { workspace: { label: string; tone: "neutral" | "attention"; title?: string };
     platform: { label: string; tone: "neutral" | "attention"; title?: string } } {
  const own = connections.filter((row) => row.type === access.connector_name);
  const serving = own.find((row) => row.state === "ok") ?? own[0];
  if (serving) {
    const working = serving.state === "ok";
    return {
      workspace: { label: `Via ${serving.name}`, tone: working ? "neutral" : "attention",
        title: working ? `The connection ${serving.name} serves this Workspace.`
          : `The connection ${serving.name} serves this Workspace; its last test did not pass.` },
      platform: access.global_configured ? platformConnectorState(access)
        : { label: "Not needed", tone: "neutral", title: "This Workspace uses its connection; no platform connector is needed." },
    };
  }
  return { workspace: { label: access.project_enabled ? "On" : "Off", tone: "neutral" }, platform: platformConnectorState(access) };
}
