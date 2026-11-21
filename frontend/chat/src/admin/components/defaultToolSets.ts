// The governed default tool sets per capability class, as the admin panel shows them.
// The code-owned sets are the seed; an admin edit stores the next version (`diagnosis.v2`) with an
// audit entry, and "Reset to seed" stores the seed again as a new version.

import {
  type PolicyListHistoryEntry,
  asNames,
  asRecord,
  asText,
  parseHistory,
} from "./policyLists";

export const DEFAULT_TOOL_SETS_PATH = "/admin/chat/api/panel/default-tool-sets";

export type DefaultToolFamily = { name: string; tools: string[] };

export type DefaultToolSet = {
  capabilityType: string;
  key: string;
  version: number;
  seedKey: string;
  origin: string;
  matchesSeed: boolean;
  title: string;
  description: string;
  toolCount: number;
  families: DefaultToolFamily[];
  unregisteredTools: string[];
  history: PolicyListHistoryEntry[];
  // The run capability classes whose turns get this set; [] when no run uses it any more.
  capabilityClasses: string[];
};

export type DefaultToolSetsView = {
  source: string;
  overrideSupported: boolean;
  sets: DefaultToolSet[];
};

function toFamily(value: unknown): DefaultToolFamily | null {
  const record = asRecord(value);
  const name = asText(record.name);
  const tools = asNames(record.tools);
  return name && tools.length > 0 ? { name, tools } : null;
}

function toSet(value: unknown): DefaultToolSet | null {
  const record = asRecord(value);
  const capabilityType = asText(record.capability_type);
  const key = asText(record.key);
  if (!capabilityType || !key) return null;
  const families = Array.isArray(record.families)
    ? record.families
        .map(toFamily)
        .filter((family): family is DefaultToolFamily => family !== null)
    : [];
  const version = Number(record.version);
  return {
    capabilityType,
    key,
    version: Number.isInteger(version) && version > 0 ? version : 0,
    seedKey: asText(record.seed_key),
    origin: asText(record.origin),
    matchesSeed: record.matches_seed === true,
    title: asText(record.title) || capabilityType,
    description: asText(record.description),
    // The count is what the families hold, so a malformed count cannot mislead.
    toolCount: new Set(families.flatMap((family) => family.tools)).size,
    families,
    unregisteredTools: asNames(record.unregistered_tools),
    history: parseHistory(record.history),
    capabilityClasses: asNames(record.capability_classes),
  };
}

/** Parse the panel payload; malformed sets and families are dropped, never guessed. */
export function parseDefaultToolSets(payload: unknown): DefaultToolSetsView {
  const record = asRecord(payload);
  const sets = Array.isArray(record.sets)
    ? record.sets
        .map(toSet)
        .filter((set): set is DefaultToolSet => set !== null)
    : [];
  return {
    source: asText(record.source),
    overrideSupported: asText(record.override) === "supported",
    sets,
  };
}
