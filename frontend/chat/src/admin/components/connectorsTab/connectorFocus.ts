export function focusedConnectorName(search: string | undefined): string {
  try {
    return new URLSearchParams(search ?? "").get("connector")?.trim() ?? "";
  } catch {
    return "";
  }
}

export function connectorToFocus<T extends { tool_name: string }>(connectors: T[], search: string | undefined): T | null {
  const name = focusedConnectorName(search);
  return name ? connectors.find((connector) => connector.tool_name === name) ?? null : null;
}
