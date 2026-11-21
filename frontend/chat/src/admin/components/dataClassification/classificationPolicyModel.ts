// The classification policy matrix. Pure: no requests,
// no React. Levels and their order come from the server; this module never names a level. The rules are kept in
// their wire form, so a rule this UI does not show yet is sent back unchanged.
//
// API contract (backend/app/api/routes/classification_policy.py):
//   GET /api/v1/admin/data-classification/policy (any signed-in user, read-only)
//     -> {state: default|configured|invalid, levels: [{level, rank, rules: {...}}], defaults: {<level>: rules},
//         rule_keys, connector_families, connector_access_values, model_aliases (the active gateway's aliases: the
//         editor's choices), updated_at, updated_by, can_edit}
//        Optional, read when sent: `label` and `admitted_model_aliases` per level; `derived_rules` (
//        `allowed_model_aliases` is derived from the Model catalog clearance, read-only here, ignored by the PUT).
//   PUT same path (platform admins), {levels: [{level, rules}]} -> the GET body; a refusal is 422
//     {detail: {errors: [{code, path}]}}.

export type Rules = Record<string, unknown>;
export type ConnectorMode = "none" | "read" | "read_write";
export const CONNECTOR_MODES: readonly ConnectorMode[] = ["none", "read", "read_write"];

// A level's catalog entry: the server sends it with every level it knows (policy_matrix_admin._level_info);
// a level missing from the catalog comes without it and reads the defaults below.
export type LevelInfo = { rank: number | null; color: string | null; description: string; modelsAllowed: boolean; builtin: boolean };
export type PolicyLevel = { level: string; label: string; rules: Rules; admittedAliases: string[] | null; info: LevelInfo };

export type MatrixState = "default" | "configured" | "invalid";

export type ClassificationPolicy = {
  state: MatrixState | null;
  levels: PolicyLevel[];
  families: string[];
  defaults: Record<string, Rules>;
  updatedAt: string | null;
  updatedBy: string | null;
  canEdit: boolean;
  modelAliases: string[];
  /** Rules the server derives (read-only here): their current value counts as their default. */
  derivedRules: string[];
};

type RuleKind = "bool" | "aliases" | "days" | "connectors";
export type RuleColumn = { key: string; label: string; kind: RuleKind; help: string; yes?: string; no?: string };

// Plain-language column help; the enforcement point is named so an admin knows what a change does.
export const RULE_COLUMNS: readonly RuleColumn[] = [
  { key: "seat_allowed", label: "Seat sessions", kind: "bool", yes: "allowed", no: "not allowed",
    help: "Claude subscription (seat) sessions may work on data of this level. The Workspace's own seat switch still has to be on." },
  { key: "requires_governed_routing", label: "Governed routing only", kind: "bool", yes: "required", no: "not required",
    help: "When on, seat sessions are forbidden and only company models through the gateway apply." },
  { key: "allowed_model_aliases", label: "Company models", kind: "aliases",
    help: "The enabled gateway models cleared for this level or higher. Read-only: a model's clearance is set in Runtime → Model catalog." },
  { key: "reranker_allowed", label: "Reranker", kind: "bool", yes: "allowed", no: "forbidden",
    help: "When off, Knowledge search never uses the reranker for this level. When on, the runtime admission still decides." },
  { key: "remote_embeddings_allowed", label: "Remote embeddings", kind: "bool", yes: "allowed", no: "forbidden",
    help: "When off, Knowledge never sends this level's text to a remote embedding model. When on, the runtime admission still decides." },
  { key: "log_masking_required", label: "Log masking", kind: "bool", yes: "required", no: "not required",
    help: "Log masking is not available yet: while it is required, the log-reading tools (Kubernetes pod logs, CloudWatch logs) are blocked for this level." },
  { key: "device_runs_allowed", label: "Device runs", kind: "bool", yes: "allowed", no: "not allowed",
    help: "Chat requests may run on members' own octryx-claude devices for this level. The Workspace's own switch still has to be on; each model call of a device job is still routed by this level's model rules." },
  { key: "transcript_retention_days", label: "Transcript retention", kind: "days",
    help: "How many days transcripts of this level are kept; empty keeps them. Stored and shown; it is enforced only where a retention job exists." },
  { key: "connectors", label: "Connectors", kind: "connectors",
    help: "Per connector family: none, read only, or read and write. Hidden tools are not listed to the agent and a call is refused. Individual tool policies still apply." },
];

const FAMILY_LABELS: Record<string, string> = {
  servicenow: "ServiceNow", jira: "Jira", confluence: "Confluence", kubernetes: "Kubernetes", aws: "AWS", bitbucket: "Bitbucket",
};
export const familyLabel = (family: string) => FAMILY_LABELS[family] || family;

const MODE_TEXT: Record<ConnectorMode, string> = { none: "none", read: "read only", read_write: "read and write" };
export const connectorModeText = (mode: unknown) => (isConnectorMode(mode) ? MODE_TEXT[mode] : "not set");

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const textList = (value: unknown) => (Array.isArray(value) ? Array.from(new Set(value.map((item) => text(isRecord(item) ? item.alias : item)).filter(Boolean))) : []);
export const isConnectorMode = (value: unknown): value is ConnectorMode => CONNECTOR_MODES.includes(value as ConnectorMode);

/** The defaults per level, from `{level: rules}` or `[{level, rules}]`. */
function readDefaults(value: unknown): Record<string, Rules> {
  const defaults: Record<string, Rules> = {};
  if (Array.isArray(value)) {
    for (const entry of value) if (isRecord(entry) && text(entry.level) && isRecord(entry.rules)) defaults[text(entry.level)] = { ...entry.rules };
  } else if (isRecord(value)) {
    const levels = Array.isArray(value.levels) ? readDefaults(value.levels) : null;
    if (levels) return levels;
    for (const [level, rules] of Object.entries(value)) if (isRecord(rules)) defaults[level] = { ...rules };
  }
  return defaults;
}

/** The matrix read model; null when the answer lists no level. `isAdmin` decides editing when the server does not. */
export function readClassificationPolicy(payload: unknown, isAdmin: boolean): ClassificationPolicy | null {
  if (!isRecord(payload) || !Array.isArray(payload.levels)) return null;
  const seen = new Set<string>();
  const levels: PolicyLevel[] = [];
  for (const entry of payload.levels) {
    if (!isRecord(entry)) continue;
    const level = text(entry.level);
    if (!level || seen.has(level)) continue;
    seen.add(level);
    levels.push({
      level, label: text(entry.label) || level, rules: isRecord(entry.rules) ? { ...entry.rules } : {},
      admittedAliases: Array.isArray(entry.admitted_model_aliases) ? textList(entry.admitted_model_aliases) : null,
      info: {
        rank: typeof entry.rank === "number" ? entry.rank : null,
        color: text(entry.color) || null,
        description: text(entry.description),
        modelsAllowed: entry.models_allowed !== false,
        builtin: entry.builtin !== false,
      },
    });
  }
  if (!levels.length) return null;
  const state = text(payload.state);
  const derivedRules = Array.isArray(payload.derived_rules) ? textList(payload.derived_rules) : [];
  const defaults = readDefaults(payload.defaults);
  for (const level of levels) {
    if (!defaults[level.level]) continue;
    for (const key of derivedRules) defaults[level.level][key] = level.rules[key];
  }
  return {
    state: state === "default" || state === "configured" || state === "invalid" ? state : null,
    levels,
    families: Array.isArray(payload.connector_families) ? textList(payload.connector_families) : [],
    defaults,
    updatedAt: text(payload.updated_at) || null,
    updatedBy: text(isRecord(payload.updated_by) ? payload.updated_by.name ?? payload.updated_by.email : payload.updated_by) || null,
    canEdit: typeof payload.can_edit === "boolean" ? payload.can_edit : isAdmin,
    modelAliases: textList(payload.model_aliases),
    derivedRules,
  };
}

const errorRecord = (error: unknown) => (isRecord(error) ? error : null);
const errorMessage = (record: Record<string, unknown> | null) => (typeof record?.message === "string" && record.message ? record.message : "");

export function policyLoadErrorText(error: unknown): string {
  const record = errorRecord(error);
  if (record?.status === 404) return "This server does not offer the classification policy yet.";
  if (record?.status === 401 || record?.status === 403) return "Sign in to see the classification policy.";
  return `The classification policy could not be loaded: ${errorMessage(record) || "the request failed"}.`;
}

/** A stored matrix the server cannot read fails closed; the admin has to know before anything else. */
export const INVALID_STATE_TEXT =
  "The stored matrix could not be read: every level is locked down (fail closed) until a platform admin saves a valid matrix.";
