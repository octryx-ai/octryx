// Named connections: the descriptors and connection lists read strictly from the server, and their panel URLs.
import type {
  ConnectionUsage, LastTest, NamedConnection, NamedConnectionList, NamedDescriptor, NamedFieldKind, WorkspaceConnection,
} from "./namedConnectionsTypes";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const FIELD_KINDS: NamedFieldKind[] = ["text", "url", "secret", "bool", "list", "select"];

/** One descriptor read strictly; null when the answer is not one. */
export function parseDescriptor(value: unknown): NamedDescriptor | null {
  if (!isRecord(value) || typeof value.connector_name !== "string" || !isRecord(value.binding)) return null;
  const binding = value.binding;
  if (typeof binding.pattern !== "string" || typeof binding.label !== "string") return null;
  const fields = (Array.isArray(value.fields) ? value.fields : []).filter(isRecord)
    .filter((item) => typeof item.name === "string")
    .map((item) => ({
      name: String(item.name),
      label: typeof item.label === "string" ? item.label : String(item.name),
      kind: FIELD_KINDS.includes(item.kind as NamedFieldKind) ? (item.kind as NamedFieldKind) : "text",
      required: item.required === true,
      options: Array.isArray(item.options) ? item.options.filter((option): option is string => typeof option === "string") : [],
      placeholder: typeof item.placeholder === "string" ? item.placeholder : "",
    }));
  const caseOf = binding.case === "lower" || binding.case === "exact" ? binding.case : "upper";
  return {
    connector: value.connector_name,
    label: typeof value.label === "string" ? value.label : value.connector_name,
    binding: {
      label: binding.label,
      plural: typeof binding.plural === "string" ? binding.plural : `${binding.label}s`,
      pattern: binding.pattern,
      case: caseOf,
      example: typeof binding.example === "string" ? binding.example : "",
      hierarchical: binding.hierarchical === true,
    },
    fields,
    urlField: typeof value.url_field === "string" ? value.url_field : "",
    form: typeof value.form === "string" ? value.form : "fields",
    testable: value.testable !== false,
  };
}

/** The descriptor registry the server sends: connector name -> descriptor. */
export function parseNamedDescriptors(payload: unknown): Record<string, NamedDescriptor> {
  const registry: Record<string, NamedDescriptor> = {};
  const listed = isRecord(payload) && Array.isArray(payload.connectors) ? payload.connectors : [];
  for (const item of listed) {
    const descriptor = parseDescriptor(item);
    if (descriptor) registry[descriptor.connector] = descriptor;
  }
  return registry;
}

/** The descriptor of a connector card, or null when the connector has no named connections. */
export function namedConnector(
  connectorName: string,
  registry: Record<string, NamedDescriptor> | null,
): NamedDescriptor | null {
  return registry && Object.prototype.hasOwnProperty.call(registry, connectorName) ? registry[connectorName] : null;
}

/** The panel URL of a Workspace's (projectId) or the global (null) named connections of one connector. */
export function namedConnectionsUrl(
  projectId: string | null,
  connectorName: string,
  connectionId?: string,
  suffix = "",
): string {
  const owner = projectId === null ? "" : `/projects/${encodeURIComponent(projectId)}`;
  const base = `/admin/chat/api/panel${owner}/connectors/${encodeURIComponent(connectorName)}/named-connections`;
  return connectionId ? `${base}/${encodeURIComponent(connectionId)}${suffix}` : base;
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

function parseLastTest(value: unknown): LastTest | null {
  if (!isRecord(value)) return null;
  return {
    ok: value.ok === true,
    at: typeof value.at === "string" ? value.at : null,
    summary: typeof value.summary === "string" ? value.summary : "",
  };
}

function parseUsage(value: unknown): ConnectionUsage | null {
  if (!isRecord(value)) return null;
  const workspaces = (Array.isArray(value.workspaces) ? value.workspaces : [])
    .filter(isRecord)
    .filter((item) => typeof item.id === "string")
    .map((item) => ({ id: String(item.id), name: typeof item.name === "string" ? item.name : String(item.id),
      scopes: strings(item.scopes) }));
  const knowledgeConnectors = (Array.isArray(value.knowledge_connectors) ? value.knowledge_connectors : [])
    .filter(isRecord)
    .filter((item) => typeof item.connector_key === "string" && typeof item.workspace_id === "string")
    .map((item) => ({
      workspaceId: String(item.workspace_id),
      workspaceName: typeof item.workspace_name === "string" ? item.workspace_name : String(item.workspace_id),
      connectorKey: String(item.connector_key),
      scopes: strings(item.scopes),
      pinned: item.pinned === true,
      pinMismatch: item.pin_mismatch === true,
    }));
  const workIntakes = (Array.isArray(value.work_intakes) ? value.work_intakes : [])
    .filter(isRecord)
    .filter((item) => typeof item.name === "string")
    .map((item) => ({ workspaceName: typeof item.workspace_name === "string" ? item.workspace_name : "", name: String(item.name) }));
  return { workspaces, knowledgeConnectors, workIntakes };
}

function secretStatusOf(value: unknown): Record<string, boolean> {
  const status: Record<string, boolean> = {};
  if (isRecord(value)) for (const [field, stored] of Object.entries(value)) status[field] = stored === true;
  return status;
}

function parseOne(value: unknown): NamedConnection | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.name !== "string") return null;
  const secretStatus = secretStatusOf(value.secret_status);
  return {
    id: value.id,
    name: value.name,
    scope: value.scope === "global" ? "global" : "workspace",
    boundScopes: strings(value.bound_scopes),
    publicFields: isRecord(value.fields) ? value.fields : {},
    secretStatus,
    lastTest: parseLastTest(value.last_test),
    usage: parseUsage(value.usage),
    servedHere: strings(value.served_here),
    overriddenHere: strings(value.overridden_here),
  };
}

function parseWorkspaceConnection(value: unknown): WorkspaceConnection | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.workspace_id !== "string") return null;
  return {
    workspaceId: value.workspace_id,
    workspaceName: typeof value.workspace_name === "string" ? value.workspace_name : value.workspace_id,
    id: value.id,
    name: typeof value.name === "string" ? value.name : value.id,
    active: value.active === true,
    boundScopes: strings(value.bound_scopes),
    publicFields: isRecord(value.fields) ? value.fields : {},
  };
}

const parseAll = (value: unknown): NamedConnection[] =>
  (Array.isArray(value) ? value : []).map(parseOne).filter((item): item is NamedConnection => item !== null);

/** The server's list read strictly; null when the answer is not a list of named connections. */
export function parseNamedConnections(payload: unknown): NamedConnectionList | null {
  if (!isRecord(payload) || !Array.isArray(payload.connections)) return null;
  const descriptor = parseDescriptor(payload.descriptor);
  if (!descriptor) return null;
  const fallback = isRecord(payload.default) ? payload.default : {};
  return {
    descriptor,
    defaultConfigured: fallback.configured === true,
    defaultActive: fallback.active === true,
    defaultFields: isRecord(fallback.fields) ? fallback.fields : {},
    defaultSecretStatus: secretStatusOf(fallback.secret_status),
    connections: parseAll(payload.connections),
    inherited: parseAll(payload.inherited),
    workspaceConnections: (Array.isArray(payload.workspace_connections) ? payload.workspace_connections : [])
      .map(parseWorkspaceConnection)
      .filter((item): item is WorkspaceConnection => item !== null),
  };
}

export function parseNamedConnection(payload: unknown): NamedConnection | null {
  return parseOne(payload);
}

