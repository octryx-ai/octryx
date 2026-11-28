import type { NamedConnection, NamedConnector } from "./namedConnectionsTypes";

export function scopeLabel(connector: NamedConnector): { plural: string; one: string } {
  return { plural: connector.binding.plural, one: connector.binding.label };
}

// An unbound inherited connection is the default and serves the Workspace's allowed list.
export function inheritedServesText(connection: Pick<NamedConnection, "boundScopes" | "servedHere" | "overriddenHere">,
  connector: NamedConnector): string {
  const { plural, one } = scopeLabel(connector);
  const overridden = connection.overriddenHere.length ? ` Overridden by this Workspace: ${connection.overriddenHere.join(", ")}.` : "";
  if (!connection.boundScopes.length) {
    return `Not bound to any ${one.toLowerCase()}: here it is the default and reads this Workspace's allowed ${plural.toLowerCase()} (Workspace settings › Connector settings).`;
  }
  if (connection.servedHere.length) return `Serves here: ${connection.servedHere.join(", ")}.${overridden}`;
  return `Serves nothing here: every ${one.toLowerCase()} it binds is bound by a Workspace connection.${overridden}`;
}

export const boundScopesFact = (connection: Pick<NamedConnection, "boundScopes">, connector: NamedConnector) =>
  `${scopeLabel(connector).plural}: ${connection.boundScopes.length ? connection.boundScopes.join(", ") : "not bound"}`;

export function canonical(connector: NamedConnector, raw: string): string {
  const key = raw.trim();
  if (connector.binding.case === "lower") return key.toLowerCase();
  if (connector.binding.case === "exact") return key;
  return key.toUpperCase();
}

export function parseScopes(connector: NamedConnector, value: string): string[] {
  const keys: string[] = [];
  for (const raw of value.split(/[\s,]+/)) {
    const key = canonical(connector, raw);
    if (key && !keys.includes(key)) keys.push(key);
  }
  return keys;
}

export function scopesProblem(connector: NamedConnector, value: string): string | null {
  const keys = parseScopes(connector, value);
  const label = scopeLabel(connector);
  if (keys.length === 0) return `Enter at least one ${label.one} this connection serves.`;
  const pattern = new RegExp(`^(?:${connector.binding.pattern})$`);
  const bad = keys.find((key) => !pattern.test(key));
  return bad ? `"${bad}" is not a valid ${label.one} key.` : null;
}

export function boundElsewhere(
  connector: NamedConnector,
  connections: NamedConnection[],
  ownId: string | null,
  value: string,
): string[] {
  const keys = parseScopes(connector, value);
  const clashes: string[] = [];
  for (const other of connections) {
    if (other.id === ownId) continue;
    for (const key of keys) if (other.boundScopes.includes(key)) clashes.push(`${key} (${other.name})`);
  }
  return clashes;
}

const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export function nameProblem(value: string, connections: NamedConnection[], ownId: string | null): string | null {
  const name = value.trim();
  if (!NAME.test(name)) return "Name: letters, digits, '.', '_' or '-' (up to 64), starting with a letter or digit.";
  if (name.toLowerCase() === "default") return "\"default\" is the connector's own connection; choose another name.";
  if (connections.some((other) => other.id !== ownId && other.name.toLowerCase() === name.toLowerCase()))
    return "Another connection already has this name.";
  return null;
}

// The models use tool_name only for input ids, so the named form gets its own beside the Workspace form.
export function namedAsConnector(connectorName: string, connection: NamedConnection | null) {
  return {
    tool_name: `${connectorName}-named`,
    configured: connection !== null,
    public_fields: connection ? connection.publicFields : {},
    secret_status: connection ? connection.secretStatus : {},
  };
}

export function namedDraft(connection: NamedConnection | null): Record<string, string> {
  const draft: Record<string, string> = {};
  for (const [field, value] of Object.entries(connection?.publicFields ?? {})) {
    if (typeof value === "string") draft[field] = value;
    else if (typeof value === "boolean") draft[field] = value ? "true" : "false";
    else if (Array.isArray(value) && value.every((item) => typeof item === "string")) draft[field] = value.join(", ");
  }
  return draft;
}

