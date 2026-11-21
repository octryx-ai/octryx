// Payload types of the Workspace Knowledge and web search APIs, with the package document roles.

export type KnowledgeSource = {
  source_id: string;
  source_key: string;
  display_title: string;
  revision_count: number;
  latest_revision_ordinal: number | null;
  // Upload or synced connector item (optional); see chat/knowledge/syncedSourceModel.ts.
  origin?: unknown;
};

export type SourceListing = {
  sources: KnowledgeSource[];
  projection_backlog: Record<string, number>;
  // Opaque continuation of a newest-first page; null on the last page.
  next_cursor?: string | null;
};

export type SourceDetail = {
  source_id: string; display_title: string;
  origin?: unknown;
  revisions: { revision_id: string; revision_ordinal: number; media_type: string;
    byte_size: number; span_count: number; state: string; content_sha256: string }[];
};

export type UploadResult = {
  source_id: string;
  revision_id: string;
  revision_ordinal: number;
  media_type: string;
  span_count: number;
  created: boolean;
  projection: string;
};

export type EvidenceHit = {
  evidence_key: string;
  text: string;
  citation: string;
  // Address the original bytes of the cited revision (originalContentUrl); optional.
  source_id?: string | null;
  revision_id?: string;
  source_title: string;
  source_url: string | null;
  products: string[];
  version: string | null;
  kind: string | null;
  pages: [number, number] | null;
  section: string | null;
  found_by: string[];
  relevance: number | null;
  similarity: number | null;
  // The Workspace the passage was found in; bound = read through a Workspace binding.
  workspace?: string;
  bound?: boolean;
  // Optional: where the source comes from, its space or project, and when this
  // version was received; the lines of a code or text passage.
  origin?: { kind: string; connector_key?: string | null; url?: string | null; source_changed_at?: string | null } | null;
  container?: string | null;
  changed_at?: string | null;
  // When the source itself last changed (Confluence version date, Jira "updated"), once the server stores it;
  // `changed_at` is when Octryx AI received the version.
  source_changed_at?: string | null;
  lines?: [number, number] | null;
};

// The passage with its neighbours for the preview (GET …/knowledge/evidence/{key}/window).
export type EvidenceWindow = { passage: string; before: string[]; after: string[] };

export type SearchResult = {
  evidence: EvidenceHit[];
  // Milliseconds per retrieval stage (optional).
  timings_ms?: Record<string, unknown>;
  mode_states?: Record<string, string>;
  workspace_states?: Record<string, Record<string, string>>;
};

export type KnowledgeBinding = {
  id: string;
  workspace_id: string;
  workspace_name: string;
  products: string[];
  state: "active" | "revoked";
  effective: "active" | "inert" | "revoked";
  inert_reason: string | null;
  reason: string;
  created_at: string | null;
  revoked_at: string | null;
};

export type BindingsOverview = {
  workspace_id: string;
  may_author: boolean;
  reads_from: KnowledgeBinding[];
  read_by: KnowledgeBinding[];
};

export type PackageDocument = {
  id: string;
  url: string;
  title: string;
  version: string | null;
  role: string;
  rationale: string;
  state: string;
  outcome: string | null;
  // The trusted-source registry's current word on the document's source.
  source_state: "trusted" | "proposed" | "blocked" | "unknown";
  source_pattern: string | null;
};

export type ResearchRound = {
  instruction?: string;
  queries?: string[];
  search_outcomes?: string[];
  source_proposals?: string[];
  candidates?: number;
  model_usage?: { calls?: number; models?: string[] };
};

export type KnowledgePackage = {
  id: string;
  topic: string;
  title: string;
  product: string;
  versions: string[];
  state: string;
  research: { rounds?: ResearchRound[] };
  documents: PackageDocument[];
  counts?: Record<string, number>;
  added?: number;
  graph_revisions_owed?: number;
  held_untrusted?: string[];
};

export type TrustedSource = {
  id: string;
  scope: "platform" | "workspace";
  pattern: string;
  products: string[];
  state: "trusted" | "proposed" | "blocked";
  origin: "admin" | "agent";
  reason: string;
  evidence_url: string | null;
  decided_at: string | null;
  created_at: string | null;
};

export type WebSearchOverview = {
  mode: "open" | "trusted_only";
  provider: { name: string | null; state: string; quarantine_reason: string | null; data_policy_class: string | null };
  blocklist_version: string;
  may_edit_platform: boolean;
  sources: TrustedSource[];
};

export type SourceRequest = {
  pattern: string;
  state: "trusted" | "blocked";
  scope: "workspace" | "platform";
  products: string[];
  reason: string;
};

export type CatalogEntry = { url: string; title: string; version: string | null; role: string };

export const PACKAGE_ROLES = [
  "migration_guide",
  "release_notes",
  "configuration_changelog",
  "reference",
  "specification",
];

export type GraphStatus = {
  episodes: number;
  pending_revisions: number;
  revisions_owed?: number;
  // Whether this installation can read extracted relationships, and extract new ones.
  readable?: boolean;
  extractable?: boolean;
};

export type ChangeFact = {
  fact: string;
  relation: string;
  subject: string;
  object: string;
  version: string | null;
  citation: string;
  source_title: string;
  source_url: string | null;
  section: string | null;
};

export type ChangesResult = {
  state: string;
  facts_workspace?: string;
  versions: string[];
  episodes: number;
  facts: ChangeFact[];
  // Without a query: totals per relation across the whole range. With a query: counts of this page.
  kind_counts?: Record<string, number>;
};
