// Connector catalog presentation. The catalog payload has no
// category field, so entries are listed alphabetically; the credential line is
// read from each preset's own `secret_fields`, never inferred from tool names.

type ConnectorTemplateLike = {
  tool_name: string;
  label: string;
  secret_fields?: string[] | null;
  tools?: unknown[] | null;
};

export function sortConnectorCatalog<T extends ConnectorTemplateLike>(
  connectors: ReadonlyArray<T>,
): T[] {
  return [...connectors].sort((left, right) =>
    (left.label || left.tool_name).localeCompare(right.label || right.tool_name, "en", {
      sensitivity: "base",
    }),
  );
}

function secretFieldLabel(toolName: string, field: string): string {
  const prefix = `${toolName}_`;
  const bare = field.startsWith(prefix) ? field.slice(prefix.length) : field;
  return bare.replace(/_/g, " ").trim() || field;
}

/** "Secrets: token, password" from the preset's secret fields. */
export function connectorCredentialSummary(connector: ConnectorTemplateLike): string {
  const fields = (connector.secret_fields || []).filter((field) => String(field || "").trim());
  if (fields.length === 0) return "No stored secret";
  const labels = Array.from(new Set(fields.map((field) => secretFieldLabel(connector.tool_name, field))));
  return `Secrets: ${labels.join(", ")}`;
}

export function connectorToolCount(connector: ConnectorTemplateLike): string {
  const count = (connector.tools || []).length;
  return `${count} tool${count === 1 ? "" : "s"}`;
}
