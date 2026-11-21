// A link from Problems names a connector as `?connector=<tool_name>`; the connectors page opens that one.

export function focusedConnectorName(search: string | undefined): string {
  try {
    return new URLSearchParams(search ?? "").get("connector")?.trim() ?? "";
  } catch {
    return "";
  }
}

/** The visible connector the link names, if any (matched by tool_name). */
export function connectorToFocus<T extends { tool_name: string }>(connectors: T[], search: string | undefined): T | null {
  const name = focusedConnectorName(search);
  return name ? connectors.find((connector) => connector.tool_name === name) ?? null : null;
}
