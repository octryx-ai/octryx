// Custom REST Work source: the setup form's state, its field names and labels, and the form of a stored intake.

export const REST_SOURCE = "custom_rest";

export type RestOperationInfo = {
  op_key: string;
  name: string;
  method: string;
  path: string;
  summary?: string | null;
  paginated?: boolean;
  roles: string[];
  scoped_roles: string[];
  role_required: boolean;
};

export type RestDiscovery = {
  definition?: string;
  name?: string;
  list_operations?: RestOperationInfo[];
  write_operations?: RestOperationInfo[];
  fields?: { required: string[]; optional: string[] };
  template_keys?: string[];
};

export type Pair = { name: string; value: string };

export type RestSourceForm = {
  operation: string;
  role: string;
  arguments: Pair[];
  fields: Record<string, string>;
  statusRows: Array<{ status: string; state: string }>;
  closedStatuses: string[];
  writeOperation: string;
  writeArguments: Pair[];
  writeBody: string;
  autoAnalyze: boolean;
};

export const REQUIRED_FIELDS = ["key", "title", "status"] as const;
export const OPTIONAL_FIELDS = ["id", "description", "type", "priority", "reporter", "assignee", "url", "parent", "labels",
  "updated_at", "created_at"] as const;

/** The Work item fields a record maps to, in words. */
export const FIELD_LABELS: Record<string, string> = {
  key: "Key", title: "Title", status: "Status", id: "Id", description: "Description", type: "Type", priority: "Priority",
  reporter: "Reporter", assignee: "Assignee", url: "Link", parent: "Parent", labels: "Labels", updated_at: "Updated",
  created_at: "Created",
};

export const DOT_PATH_HINT = "A dot path into one record: number, fields.summary or state.name. Letters, digits and _ $ @ : - per step.";

export function emptyRestForm(): RestSourceForm {
  return { operation: "", role: "", arguments: [], fields: {}, statusRows: [], closedStatuses: [], writeOperation: "",
    writeArguments: [], writeBody: "", autoAnalyze: false };
}

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
export const str = (value: unknown) => (typeof value === "string" ? value : value === null || value === undefined ? "" : String(value));
const pairs = (value: unknown): Pair[] => Object.entries(record(value)).map(([name, entry]) => ({ name, value: str(entry) }));

/** The form of a stored intake (`GET …/intake/{id}`): `what` and `how` as the server returns them. */
export function restFormOf(what: unknown, how: unknown): RestSourceForm {
  const w = record(what);
  const h = record(how);
  const writeBack = record(h.write_back);
  return {
    operation: str(w.operation),
    role: str(w.role),
    arguments: pairs(w.arguments),
    fields: Object.fromEntries(Object.entries(record(h.field_mapping)).map(([name, path]) => [name, str(path)])),
    statusRows: Object.entries(record(h.status_mapping)).map(([status, state]) => ({ status, state: str(state) })),
    closedStatuses: Array.isArray(h.closed_statuses) ? h.closed_statuses.map(str) : [],
    writeOperation: str(writeBack.operation),
    writeArguments: pairs(writeBack.arguments),
    writeBody: writeBack.body !== undefined && writeBack.body !== null ? JSON.stringify(writeBack.body, null, 2) : "",
    autoAnalyze: h.auto_analyze_new === true,
  };
}
