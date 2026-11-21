// Named connections: the descriptor, connection, usage and list types as the UI reads them.

export const NAMED_DESCRIPTORS_URL = "/admin/chat/api/panel/named-connection-descriptors";

export type NamedFieldKind = "text" | "url" | "secret" | "bool" | "list" | "select";
export type NamedField = {
  name: string;
  label: string;
  kind: NamedFieldKind;
  required: boolean;
  options: string[];
  placeholder: string;
};

// A connector type's descriptor as the server sends it (backend named_connections/descriptor.py `public()`).
export type NamedDescriptor = {
  connector: string;
  label: string;
  binding: { label: string; plural: string; pattern: string; case: "upper" | "lower" | "exact"; example: string;
    hierarchical: boolean };
  fields: NamedField[];
  urlField: string;
  // "fields": the generic form over `fields`; "atlassian_auth" / "servicenow_auth": the sign-in forms with modes.
  form: string;
  testable: boolean;
};

/** A connector type, described by its descriptor. */
export type NamedConnector = NamedDescriptor;

export type LastTest = { ok: boolean; at: string | null; summary: string };

export type ConnectionUsage = {
  workspaces: Array<{ id: string; name: string; scopes: string[] }>;
  // Work intakes that read through this connection.
  workIntakes?: Array<{ workspaceName: string; name: string }>;
  knowledgeConnectors: Array<{
    workspaceId: string;
    workspaceName: string;
    connectorKey: string;
    scopes: string[];
    pinned: boolean;
    pinMismatch: boolean;
  }>;
};

export type NamedConnection = {
  id: string;
  name: string;
  scope: "workspace" | "global";
  boundScopes: string[];
  publicFields: Record<string, unknown>;
  secretStatus: Record<string, boolean>;
  lastTest: LastTest | null;
  usage: ConnectionUsage | null;
  // Inherited (global) connections in a Workspace's list only: the keys it serves here and the keys the
  // Workspace's own connections override.
  servedHere: string[];
  overriddenHere: string[];
};

export type NamedConnectionList = {
  descriptor: NamedDescriptor;
  defaultConfigured: boolean;
  defaultActive: boolean;
  defaultFields: Record<string, unknown>;
  defaultSecretStatus: Record<string, boolean>;
  connections: NamedConnection[];
  inherited: NamedConnection[];
  // Global list only: every active Workspace's own connections (named and its own default), read-only.
  workspaceConnections: WorkspaceConnection[];
};

export type WorkspaceConnection = {
  workspaceId: string;
  workspaceName: string;
  id: string;
  name: string;
  active: boolean;
  boundScopes: string[];
  publicFields: Record<string, unknown>;
};

