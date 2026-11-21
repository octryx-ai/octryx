// Classification matrix rows, cell values, cell options and cell edits.
import type { Rules } from "./classificationPolicyModel";
import { familyLabel } from "./classificationPolicyModel";
import { isRecord } from "./classificationValueReaders";

export type CellTone = "yes" | "part" | "no" | "";
type Option = { value: unknown; text: string; tone: CellTone };

export type MatrixRow = {
  key: string;
  family: string;
  label: string;
  sub: string;
  // The stored rule and, for connectors, the family inside it.
  rule: string;
  connector?: string;
  derived?: boolean;
  notEnforced?: boolean;
  // The generated policy id suffix (`classification:<level>:<suffix>`), for "View policy".
  policySuffix: string;
  options: Option[];
};

const ALLOWED_OFF: Option[] = [
  { value: true, text: "Allowed", tone: "yes" },
  { value: false, text: "Off", tone: "no" },
];
const CONNECTOR_OPTIONS: Option[] = [
  { value: "read_write", text: "Read & write", tone: "yes" },
  { value: "read", text: "Read only", tone: "part" },
  { value: "none", text: "None", tone: "no" },
];
export const RETENTION_CHOICES: (number | null)[] = [null, 365, 180, 90, 30];

/** The matrix rows; connector families come from the server (their order), so a new family needs no UI change. */
export function matrixRows(families: string[]): MatrixRow[] {
  return [
    { key: "models", family: "Models", label: "Models cleared", sub: "derived from each model's clearance", rule: "allowed_model_aliases",
      derived: true, policySuffix: "model-aliases", options: [] },
    { key: "gateway", family: "Models", label: "Company gateway required", sub: "every model call governed", rule: "requires_governed_routing",
      policySuffix: "requires-governed-routing",
      options: [{ value: false, text: "Not required", tone: "yes" }, { value: true, text: "Required", tone: "no" }] },
    { key: "seat", family: "Coding tools", label: "Claude Code seat", sub: "members' own seats", rule: "seat_allowed",
      policySuffix: "seat-not-allowed", options: ALLOWED_OFF },
    { key: "device", family: "Coding tools", label: "Device runs", sub: "runs on paired devices", rule: "device_runs_allowed",
      policySuffix: "device-runs-not-allowed", options: ALLOWED_OFF },
    { key: "reranker", family: "Knowledge", label: "Reranker", sub: "remote reranking", rule: "reranker_allowed",
      policySuffix: "reranker-forbidden", options: ALLOWED_OFF },
    { key: "embeddings", family: "Knowledge", label: "Remote embeddings", sub: "", rule: "remote_embeddings_allowed",
      policySuffix: "remote-embeddings-forbidden", options: ALLOWED_OFF },
    ...families.map((family): MatrixRow => ({
      key: `connector:${family}`, family: "Connectors", label: familyLabel(family), sub: "", rule: "connectors", connector: family,
      policySuffix: `connector:${family}:`, options: CONNECTOR_OPTIONS,
    })),
    { key: "logs", family: "Connectors", label: "Log tools", sub: "blocked until sensitive data in logs can be masked", rule: "log_masking_required",
      policySuffix: "log-masking-not-available",
      options: [{ value: false, text: "Allowed", tone: "yes" }, { value: true, text: "Blocked", tone: "no" }] },
    { key: "retention", family: "Retention", label: "Transcript retention", sub: "", rule: "transcript_retention_days", notEnforced: true,
      policySuffix: "transcript-retention",
      options: RETENTION_CHOICES.map((days) => ({ value: days, text: days === null ? "Unlimited" : `${days} days`, tone: "" as CellTone })) },
  ];
}

export function cellValue(row: MatrixRow, rules: Rules | undefined): unknown {
  if (!rules) return undefined;
  if (row.connector) return isRecord(rules.connectors) ? rules.connectors[row.connector] ?? "read_write" : "read_write";
  return rules[row.rule];
}

export function cellDisplay(row: MatrixRow, value: unknown): { text: string; tone: CellTone } {
  if (row.derived) {
    if (!Array.isArray(value)) return { text: "All cleared", tone: "yes" };
    return value.length ? { text: `${value.length} ${value.length === 1 ? "model" : "models"}`, tone: "part" } : { text: "None", tone: "no" };
  }
  const option = row.options.find((item) => item.value === value);
  if (option) return { text: option.text, tone: row.notEnforced ? "" : option.tone };
  if (row.rule === "transcript_retention_days" && typeof value === "number") return { text: `${value} days`, tone: "" };
  return { text: "–", tone: "" };
}

/** The options a cell may take: retention keeps a stored custom number of days. */
export function cellOptions(row: MatrixRow, value: unknown): Option[] {
  if (row.rule === "transcript_retention_days" && typeof value === "number" && !RETENTION_CHOICES.includes(value)) {
    return [...row.options, { value, text: `${value} days`, tone: "" }];
  }
  return row.options;
}

export type LevelRules = { level: string; rules: Rules };

export function setCell(levels: LevelRules[], level: string, row: MatrixRow, value: unknown): LevelRules[] {
  return levels.map((item) => {
    if (item.level !== level) return item;
    if (row.connector) {
      const connectors = isRecord(item.rules.connectors) ? item.rules.connectors : {};
      return { level, rules: { ...item.rules, connectors: { ...connectors, [row.connector]: value } } };
    }
    return { level, rules: { ...item.rules, [row.rule]: value } };
  });
}

export function policiesForCell(policies: { id: string; text: string }[], level: string, row: MatrixRow) {
  const prefix = `classification:${level}:${row.policySuffix}`;
  return policies.filter((policy) => (row.connector ? policy.id.startsWith(prefix) : policy.id === prefix));
}

export const levelLabelOf = (key: string, labels: Record<string, string> = {}) =>
  labels[key] || (key ? key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " ") : key);
