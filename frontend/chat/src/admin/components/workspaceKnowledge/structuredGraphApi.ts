// The Workspace's deterministic structured graph: build requests, status, Handbook vs. reality.
import { knowledgeBase, request } from "./workspaceKnowledgeRequest";

export const STRUCTURED_LAYERS = ["manual", "configuration", "operations"] as const;
export type StructuredLayer = (typeof STRUCTURED_LAYERS)[number];

export type StructuredCitation = {
  citation?: string;
  cite_as?: string;
  evidence_key?: string;
  source_title?: string;
  source_url?: string | null;
  section?: string | null;
  page?: number | null;
  line?: number | null;
  source_id?: string;
  revision_id?: string;
};

export type LayerReport = {
  selected?: number; extracted?: number; already_current?: number; retired?: number; failed?: number;
  nodes?: number; edges?: number; warnings?: Record<string, number>; state?: string;
};

export type StructuredBuild = {
  id: string;
  state: "pending" | "running" | "completed" | "failed";
  trigger: string;
  layers: StructuredLayer[];
  requested_at: string | null;
  finished_at: string | null;
  failure: string | null;
  // Running without a live claimer: its runner stopped (a restart) or handed it back; the next claim resumes it.
  lease_expired?: boolean;
  // Null for a reader who is not a Workspace author (counts include restricted sources).
  report: { layers?: Record<string, LayerReport>; linkage?: Record<string, Record<string, unknown>>;
    duration_seconds?: number | null; slices?: number } | null;
};

export type StructuredStatus = {
  workspace_id: string;
  profile: string;
  counts_visible: boolean;
  layers: Record<StructuredLayer, { revisions: number; nodes: number; edges: number }> | null;
  refresh_after_sync: boolean;
  // The manual build runner's last recorded run (instance-wide); null before its first record.
  runner: { status: "success" | "failed"; completed_at: string | null; updated_at: string | null;
    failure: string | null; run_count: number; failure_count: number } | null;
  builds: StructuredBuild[];
};

export type SettingItem = {
  setting: string; section: string | null; key: string; value: string; redacted: boolean;
  component: string; file: string; repository: string; line: number; citation: StructuredCitation | null;
};
export type ParameterItem = {
  parameter: string; name: string; scope: string | null; default: string | null; unit: string | null;
  citation: StructuredCitation | null;
};

export type HandbookReport = {
  workspace_id: string;
  state: "ok" | "not_built" | "no_manual";
  built_at: string | null;
  counts: Record<string, number>;
  truncated: boolean;
  edges_capped: boolean;
  undocumented_in_known_section: Array<FindingItem & { name_matches: ParameterItem[] }>;
  unknown_section: UnknownSectionItem[];
  deviations: Array<FindingItem & { deviates: boolean; documented: ParameterItem }>;
  unresolved_placeholders: Array<FindingItem & { placeholders: string[]; documented: ParameterItem }>;
  inconsistencies: Array<{ setting: string; values: Array<SettingItem & { compared_value: string | null;
    variants: VariantItem[] }> }>;
  documented_unused: Array<ParameterItem & { files: string[] }>;
};

// A variant file (``server.ini-test``) of the finding's base file, with its own value.
export type VariantItem = {
  path: string; variant: string | null; line: number; value: string; resolved_value?: string;
  deviates?: boolean; unresolved?: string[];
};
export type FindingItem = SettingItem & { variants: VariantItem[]; resolved_value?: string };
export type UnknownSectionItem = {
  section: string | null; keys: string[]; key_count: number; variant_files: string[]; component: string;
  file: string; repository: string; line: number; citation: StructuredCitation | null;
  name_matches: ParameterItem[];
};

export function structuredBase(workspaceId: string): string {
  return `${knowledgeBase(workspaceId)}/graph/structured`;
}

export function reportUrl(workspaceId: string, filters: { parameter?: string; file?: string; section?: string }) {
  const params = new URLSearchParams({ limit: "50" });
  for (const [key, value] of Object.entries(filters)) if (value && value.trim()) params.set(key, value.trim());
  return `${structuredBase(workspaceId)}/report?${params}`;
}

export const structuredGraphApi = {
  status: (id: string) => request<StructuredStatus>(structuredBase(id)),
  build: (id: string, layers: StructuredLayer[]) =>
    request<{ build: { id: string; state: string; layers: StructuredLayer[] } }>(`${structuredBase(id)}/builds`, {
      method: "POST",
      body: JSON.stringify({ layers }),
    }),
  report: (id: string, filters: { parameter?: string; file?: string; section?: string }) =>
    request<HandbookReport>(reportUrl(id, filters)),
};

// The structured-graph profile of a Workspace: the instance default or its own versioned document.
export type StructuredProfileHistoryItem = {
  revision: number; profile_id: string | null; reset: boolean; created_by: string | null; created_at: string | null;
};
export type StructuredProfileSettings = {
  workspace_id: string;
  source: "default" | "workspace";
  profile_id: string;
  revision: number | null;
  document: Record<string, unknown>;
  default_document: Record<string, unknown>;
  may_author: boolean;
  history: StructuredProfileHistoryItem[];
};

export const structuredProfileApi = {
  get: (id: string) => request<StructuredProfileSettings>(`${structuredBase(id)}/profile`),
  validate: (id: string, document: Record<string, unknown>) =>
    request<{ valid: boolean; profile_id: string }>(`${structuredBase(id)}/profile/validate`, {
      method: "POST", body: JSON.stringify({ document }),
    }),
  // ``null`` returns to the instance default. Either way every layer is re-extracted.
  save: (id: string, document: Record<string, unknown> | null) =>
    request<StructuredProfileSettings & { build: { id: string; state: string } }>(`${structuredBase(id)}/profile`, {
      method: "PUT", body: JSON.stringify({ document }),
    }),
};
