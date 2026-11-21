// Pure model of the Policies page: the catalog, the picker entities and the per-policy view of
// the backend read model (`api/routes/policy_engine_catalog.py`), parsed defensively, plus the list's filters and
// labels. Sentences come from the server as segments; the UI only decides which parts are bold.

import { effectBadge } from "./builderContentModel";
import { readModel } from "./policyBuilderModel";
import { readVersion } from "./policyEngineVersions";
import { serverDate } from "./policyEngineStatus";
import type { PolicyVersion } from "./policyEngineVersions";
import { formatRelative } from "../../utils/dateTime";

type Json = Record<string, unknown>;

const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);
const strs = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
const records = (value: unknown): Json[] => (Array.isArray(value) ? value.filter(isRecord) : []);

export type Segment = { text: string; emphasis: "verb" | "value" | null };

export function readSegments(raw: unknown): Segment[] {
  return records(raw).map((item) => ({
    text: str(item.text),
    emphasis: item.emphasis === "verb" || item.emphasis === "value" ? item.emphasis : null,
  }));
}

export const sentenceText = (segments: Segment[]) => segments.map((segment) => segment.text).join("");

// ---- catalog ---------------------------------------------------------------------------------------------------

export type CatalogAction = {
  id: string; group: string; label: string; verb: string; point: string; pointLabel: string; pointWhen: string;
  carriesUser: boolean; carriesClassification: boolean; baseline: string;
  /** What a content action's scan reads ("request body", "the result"); "" for actions without content. */
  content: string;
};
export type CatalogBlock = {
  id: string; step: string; label: string; field: string; actions: string[]; clause: "when" | "unless";
  multi: boolean; picker: string; freeText: boolean; values: string[]; valuesFrom: string; note: string;
  userBound: boolean; classificationBound: boolean;
};
export type TemplatePlaceholder = { field: string; label: string; hint: string };
export type CatalogTemplate = {
  id: string; label: string; icon: string; description: string; tags: string[];
  placeholders: TemplatePlaceholder[]; model: Json;
  /** The gallery section ("" = the general templates). */
  section: string;
};
export type CatalogOutcome = { id: string; label: string; description: string; actions: string[] };
export type Catalog = {
  schemaVersion: string;
  actionGroups: string[];
  actions: CatalogAction[];
  blocks: CatalogBlock[];
  templates: CatalogTemplate[];
  levels: string[];
  dataPolicyClasses: string[];
  connectorFamilies: string[];
  clientTools: string[];
  outcomes: CatalogOutcome[];
  maskStyles: { id: string; label: string }[];
};

export function readCatalog(raw: unknown): Catalog {
  const value = isRecord(raw) ? raw : {};
  const contextTool = records(value.context).find((item) => item.name === "tool");
  return {
    schemaVersion: str(value.schema_version),
    actionGroups: strs(value.action_groups),
    actions: records(value.actions).map((item) => ({
      id: str(item.id), group: str(item.group), label: str(item.label), verb: str(item.verb), point: str(item.point),
      pointLabel: str(item.point_label), pointWhen: str(item.point_when), carriesUser: item.carries_user === true,
      carriesClassification: item.carries_classification === true, baseline: str(item.baseline), content: str(item.content),
    })),
    blocks: records(value.condition_blocks).map((item) => ({
      id: str(item.id), step: str(item.step), label: str(item.label), field: str(item.field), actions: strs(item.actions),
      clause: item.clause === "unless" ? "unless" : "when", multi: item.multi === true, picker: str(item.picker),
      freeText: item.free_text === true, values: strs(item.values), valuesFrom: str(item.values_from), note: str(item.note),
      userBound: item.user_bound === true, classificationBound: item.classification_bound === true,
    })),
    templates: records(value.templates).map((item) => ({
      id: str(item.id), label: str(item.label), icon: str(item.icon), description: str(item.description),
      tags: strs(item.tags), model: isRecord(item.model) ? item.model : {}, section: str(item.section),
      placeholders: records(item.placeholders).map((entry) => ({ field: str(entry.field), label: str(entry.label), hint: str(entry.hint) })),
    })),
    levels: strs(value.classification_levels),
    dataPolicyClasses: strs(value.data_policy_classes),
    connectorFamilies: strs(value.connector_families),
    clientTools: contextTool ? strs(contextTool.values) : [],
    outcomes: records(value.outcomes).map((item) => ({ id: str(item.id), label: str(item.label), description: str(item.description), actions: strs(item.actions) })),
    maskStyles: records(value.mask_styles).map((item) => ({ id: str(item.id), label: str(item.label) || str(item.id) })),
  };
}

export const actionOf = (catalog: Catalog | null, id: string) => catalog?.actions.find((item) => item.id === id) ?? null;

// ---- picker entities -------------------------------------------------------------------------------------------

export type NamedConnection = {
  id: string; name: string; connector: string; scope: "global" | "workspace"; workspaceId: string; workspaceName: string;
  boundScopes: string[];
};
export type PickerEntities = {
  workspaces: { id: string; name: string; classification: string }[];
  users: { id: string; name: string }[];
  roles: { name: string; description: string; memberCount: number }[];
  groups: { name: string; description: string; memberCount: number }[];
  namedConnections: NamedConnection[];
  tools: { name: string; connectorFamily: string; risk: string; mutatesState: boolean; readsLogs: boolean }[];
  /** `approvedFor`: the categories the alias is approved for (the Outcome step's route targets). */
  modelAliases: { alias: string; dataPolicyClass: string; approvedFor: string[] }[];
  connectorFamilies: { id: string; label: string }[];
};

export const EMPTY_ENTITIES: PickerEntities = {
  workspaces: [], users: [], roles: [], groups: [], namedConnections: [], tools: [], modelAliases: [], connectorFamilies: [],
};

export function readPickerEntities(raw: unknown): PickerEntities {
  const value = isRecord(raw) ? raw : {};
  return {
    workspaces: records(value.workspaces).map((item) => ({ id: str(item.id), name: str(item.name) || str(item.id), classification: str(item.classification) })),
    users: records(value.users).map((item) => ({ id: str(item.id), name: str(item.display_name) || str(item.username) || str(item.id) })),
    roles: records(value.roles).map((item) => ({ name: str(item.name), description: str(item.description), memberCount: num(item.member_count) })),
    groups: records(value.groups).map((item) => ({ name: str(item.name), description: str(item.description), memberCount: num(item.member_count) })),
    namedConnections: records(value.named_connections).map((item) => ({
      id: str(item.id), name: str(item.name), connector: str(item.connector), scope: item.scope === "workspace" ? "workspace" : "global",
      workspaceId: str(item.workspace_id), workspaceName: str(item.workspace_name), boundScopes: strs(item.bound_scopes),
    })),
    tools: records(value.tools).map((item) => ({
      name: str(item.name), connectorFamily: str(item.connector_family), risk: str(item.risk),
      mutatesState: item.mutates_state === true, readsLogs: item.reads_logs === true,
    })),
    modelAliases: records(value.model_aliases).map((item) => ({ alias: str(item.alias), dataPolicyClass: str(item.data_policy_class), approvedFor: strs(item.approved_for) })),
    connectorFamilies: records(value.connector_families).map((item) => ({ id: str(item.id), label: str(item.label) || str(item.id) })),
  };
}

// ---- per-policy view -------------------------------------------------------------------------------------------

export type PolicyWarning = { code: string; message: string; actions: string[]; id: string };
export type PolicyChange = "new" | "changed" | "unchanged" | "removed" | null;
export type PolicyItem = {
  id: string; name: string; description: string; template: string | null; source: string; editable: boolean;
  effect: string; actions: string[]; groups: string[]; points: string[]; text: string; digest: string;
  sentence: Segment[]; scope: string; references: { entities: Record<string, string[]>; connections: string[] };
  warnings: PolicyWarning[]; change: PolicyChange;
  lastChanged: { version: number; by: string; byName: string; at: string } | null;
  editWhere: string; model: Json | null;
};
export type EditTarget = { version: number; digest: string; createsDraft: boolean };
export type PolicyView = {
  version: PolicyVersion | null; publishedVersion: number | null; authorName: string;
  items: PolicyItem[]; generated: PolicyItem[] | null; changes: { new: number; changed: number; removed: number };
  /** Where a policy-level save goes; `null` while the version is in review (frozen). */
  editTarget: EditTarget | null;
};
export type PolicyHistoryEntry = { version: number; state: string; change: string; byName: string; publishedAt: string };

const CHANGES = new Set(["new", "changed", "unchanged", "removed"]);

export function readPolicyItem(raw: unknown): PolicyItem | null {
  if (!isRecord(raw) || !str(raw.id)) return null;
  const references = isRecord(raw.references) ? raw.references : {};
  const entities = isRecord(references.entities) ? references.entities : {};
  const last = isRecord(raw.last_changed) ? raw.last_changed : null;
  return {
    id: str(raw.id), name: str(raw.name) || str(raw.id), description: str(raw.description), template: str(raw.template) || null,
    source: str(raw.source), editable: raw.editable === true, effect: str(raw.effect), actions: strs(raw.actions),
    groups: strs(raw.groups), points: strs(raw.points), text: str(raw.text), digest: str(raw.digest),
    sentence: readSegments(raw.sentence), scope: str(raw.scope),
    references: { entities: Object.fromEntries(Object.entries(entities).map(([key, value]) => [key, strs(value)])), connections: strs(references.connections) },
    warnings: records(raw.warnings).map((item) => ({ code: str(item.code), message: str(item.message), actions: strs(item.actions), id: str(item.id) })),
    change: CHANGES.has(str(raw.change)) ? (str(raw.change) as PolicyChange) : null,
    lastChanged: last ? { version: num(last.version), by: str(last.by), byName: str(last.by_name), at: str(last.at) } : null,
    editWhere: str(raw.edit_where),
    model: isRecord(raw.model) ? raw.model : null,
  };
}

export function readPolicyView(raw: unknown): PolicyView {
  const value = isRecord(raw) ? raw : {};
  const changes = isRecord(value.changes) ? value.changes : {};
  const items = (list: unknown) => records(list).map(readPolicyItem).filter((item): item is PolicyItem => item !== null);
  return {
    version: readVersion(value.version),
    publishedVersion: typeof value.published_version === "number" ? value.published_version : null,
    authorName: str(value.author_name),
    items: items(value.items),
    generated: Array.isArray(value.generated) ? items(value.generated) : null,
    changes: { new: num(changes.new), changed: num(changes.changed), removed: num(changes.removed) },
    editTarget: isRecord(value.edit_target) && typeof value.edit_target.version === "number"
      ? { version: value.edit_target.version, digest: str(value.edit_target.digest), createsDraft: value.edit_target.creates_draft === true }
      : null,
  };
}

export function readPolicyHistory(raw: unknown): PolicyHistoryEntry[] {
  const value = isRecord(raw) ? raw : {};
  return records(value.history).map((item) => ({
    version: num(item.version), state: str(item.state), change: str(item.change), byName: str(item.by_name) || str(item.by),
    publishedAt: str(item.published_at),
  }));
}

// ---- list labels and filters -----------------------------------------------------------------------------------

export type Tone = "active" | "attention" | "running" | "danger" | "neutral";

export const SOURCE_LABELS: Record<string, string> = {
  builder: "Builder", hand_written: "Hand-written", classification: "Classification matrix",
  workspace: "Workspace policy", platform: "Platform",
};

/** The Status column: what this policy is in the working version against the published one. */
export function policyStatus(item: PolicyItem, versionState: string | null): { label: string; tone: Tone; key: string } {
  if (item.change === null) return { label: "Generated", tone: "neutral", key: "generated" };
  if (item.change === "unchanged" || versionState === "published" || versionState === null) return { label: "Published", tone: "active", key: "published" };
  const prefix = versionState === "in_review" ? "In review" : "Draft";
  const key = versionState === "in_review" ? "in_review" : "draft";
  if (item.change === "new") return { label: `${prefix} · new`, tone: "attention", key };
  if (item.change === "changed") return { label: `${prefix} · changed`, tone: "running", key };
  return { label: `${prefix} · removed`, tone: "danger", key };
}

/** The Effect badge: Allows for a permit; for a content policy its obligation like the builder's badge (Masks · routes,
 * Masks, Routes, Blocks); else Blocks. */
export function effectOf(item: PolicyItem): { label: string; tone: "active" | "danger" | "running" } {
  if (item.effect === "permit") return { label: "Allows", tone: "active" };
  return item.model ? effectBadge(readModel(item.model)) : { label: "Blocks", tone: "danger" };
}
export const effectLabel = (item: PolicyItem) => effectOf(item).label;

export type ListFilters = {
  query: string; group: string; status: string; workspace: string; connection: string; connector: string;
  showGenerated: boolean;
};
export const NO_FILTERS: ListFilters = { query: "", group: "", status: "", workspace: "", connection: "", connector: "", showGenerated: false };

/** Does this policy touch a connector: its family is named, or one of its connections belongs to it. */
export function touchesConnector(item: PolicyItem, connector: string, connections: NamedConnection[]): boolean {
  if ((item.references.entities.ConnectorFamily ?? []).includes(connector)) return true;
  return item.references.connections.some((id) => connections.find((entry) => entry.id === id)?.connector === connector);
}

export function filterPolicies(
  items: PolicyItem[], filters: ListFilters, versionState: string | null, connections: NamedConnection[] = [],
): PolicyItem[] {
  const query = filters.query.trim().toLowerCase();
  return items.filter((item) => {
    if (query && ![item.name, item.description, item.id, sentenceText(item.sentence), item.scope].some((value) => value.toLowerCase().includes(query))) return false;
    if (filters.group && !item.groups.includes(filters.group)) return false;
    if (filters.status && policyStatus(item, versionState).key !== filters.status) return false;
    if (filters.workspace && !(item.references.entities.Workspace ?? []).includes(filters.workspace)) return false;
    if (filters.connection && !item.references.connections.includes(filters.connection)) return false;
    if (filters.connector && !touchesConnector(item, filters.connector, connections)) return false;
    return true;
  });
}

/** Deep-link filters (`?policyConnection=<id>` etc.) from the connector cards and the Agents area. */
export function readUrlFilters(search: string): Partial<ListFilters> {
  const params = new URLSearchParams(search);
  const safe = (value: string | null) => (value && /^[A-Za-z0-9._:@/-]{1,120}$/.test(value) ? value : "");
  const found: Partial<ListFilters> = {};
  const workspace = safe(params.get("policyWorkspace"));
  const connection = safe(params.get("policyConnection"));
  const connector = safe(params.get("policyConnector"));
  if (workspace) found.workspace = workspace;
  if (connection) found.connection = connection;
  if (connector) found.connector = connector;
  return found;
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  return iso ? formatRelative(iso, "", now.getTime()) : "";
}
