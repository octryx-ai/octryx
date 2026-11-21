// Skill catalog response types: surfaces, skill rows, versions, security reports, reviews and categories.
export type Surface = "platform_chat" | "octryx_claude";
export const SURFACES: Surface[] = ["platform_chat", "octryx_claude"];
export const SURFACE_LABELS: Record<Surface, string> = { platform_chat: "Platform chat", octryx_claude: "octryx-claude" };

export type VersionState = "draft" | "in_review" | "published" | "retired";
export type VersionSummary = { version: number; state: VersionState; digest: string; updated_at: string | null };
export type CategoryPath = { id: string; key: string; label: string; path: string[] };
export type SourceRef = { id: string; label: string; trust: string; kind: string; url?: string; ref?: string };
export type UpstreamStatus = {
  checked_at?: string | null;
  compare_ref?: string | null;
  latest_commit?: string | null;
  current_commit?: string | null;
  path?: string | null;
  path_moved?: { from: string; to: string } | null;
  update_available?: boolean;
  reference_version?: number | null;
  error?: string | null;
  candidates?: string[];
};

export type SkillRow = {
  id: string;
  name: string;
  kind: "skill" | "mcp_server";
  tags: string[];
  description: string;
  category: CategoryPath | null;
  published: VersionSummary | null;
  open: VersionSummary | null;
  available: Record<Surface, boolean>;
  source: SourceRef | null;
  tracking_mode: "pinned" | "follow" | null;
  update_available: boolean;
  upstream_status: UpstreamStatus | null;
  uses: number;
  workspaces: number;
};
export type CatalogCounts = { published: number; drafts: number; in_review: number; updates: number; total: number };
export type SkillList = { items: SkillRow[]; counts: CatalogCounts };

export type FileEntry = { path: string; sha256: string; size: number; kind: string };
export type Finding = {
  id: string;
  rule: string;
  severity: "high" | "medium" | "info";
  message: string;
  file: string | null;
  line: number | null;
  effect: string;
  acknowledge: boolean;
  blocks: boolean;
};
export type SpecIssue = { code: string; severity: "error" | "warning"; field?: string; message: string };
export type SecurityReport = { spec: SpecIssue[]; findings: Finding[]; summary: { high: number; medium: number; info: number } };
export type Conflict = {
  id: string;
  path: string;
  kind: string;
  base: string[];
  ours: string[];
  theirs: string[];
  relocation: { path: string; line: number; end_line: number; after_line: number; block: string[]; mine: string[] } | null;
};
export type Resolution = { choice: "upstream" | "mine" | "manual" | "relocate"; text?: string };
export type MergeReport = {
  files: { path: string; status: string; local_hunks?: number; upstream_hunks?: number }[];
  conflicts: Conflict[];
  resolutions: Record<string, Resolution>;
  base_commit: string | null;
  theirs_commit: string | null;
  from_version: number | null;
  path_moved: { from: string; to: string } | null;
};
export type LaunchSpec = {
  command?: string;
  args?: string[];
  env_names?: string[];
  passthrough?: string[];
  image?: string | null;
  image_digest?: string | null;
  env_connections?: Record<string, string>;
  [key: string]: unknown;
};
export type Extension = {
  tools?: Record<Surface, { required: string[]; optional: string[] }>;
  output_contract?: Record<string, string>;
  safety_rules?: string[];
  allowed_roles?: string[];
  card_override?: string;
  [key: string]: unknown;
};
export type SkillVersion = {
  id: string;
  version: number;
  state: VersionState;
  digest: string;
  bundle_digest: string;
  category_id: string | null;
  available_platform_chat: boolean;
  available_octryx_claude: boolean;
  licence_spdx: string | null;
  scripts_allowed: boolean;
  scripts_reason: string | null;
  scripts_allowed_by: string | null;
  acknowledged_findings: string[];
  upstream: { source_id: string; path: string; commit: string; bundle_digest: string } | null;
  base_version: number | null;
  note: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  submitted_by: string | null;
  submitted_at: string | null;
  approval_id: string | null;
  published_by: string | null;
  published_at: string | null;
  retired_at: string | null;
  files: FileEntry[];
  security_report: SecurityReport;
  merge_report: MergeReport | null;
  launch_spec: LaunchSpec | null;
  frontmatter?: Record<string, unknown>;
  body?: string;
  extension?: Extension;
  author_name?: string | null;
  reviewer_name?: string | null;
  /** `self` when the author approved their own version (approval rule: single admin). */
  approval_mode?: string | null;
};
export type Person = { id: string; name: string };
export type Review = {
  approval_id: string;
  status: "pending" | "approved" | "rejected" | string;
  requested_by: Person | null;
  requested_at: string | null;
  decided_by: Person | null;
  decided_at: string | null;
  comment: string | null;
  author: Person | null;
  submitter: Person | null;
  approver_candidates: Person[];
  viewer: { is_author: boolean; is_submitter: boolean; can_approve: boolean };
  single_admin: boolean;
  rule: string;
};
export type SkillDetail = {
  id: string;
  name: string;
  kind: "skill" | "mcp_server";
  tags: string[];
  owner_id: string | null;
  tracking_mode: "pinned" | "follow" | null;
  pinned_commit: string | null;
  upstream_path: string | null;
  upstream_status: UpstreamStatus | null;
  source: SourceRef | null;
  category: CategoryPath | null;
  published: SkillVersion | null;
  open: SkillVersion | null;
  review: Review | null;
  new_findings: Finding[];
  versions: SkillVersion[];
};

export type CategoryNode = {
  id: string;
  key: string;
  label: string;
  description: string;
  parent_id: string | null;
  sort_order: number;
  archived: boolean;
  skills: number;
  total: number;
  children: CategoryNode[];
};
export type CategoryCatalog = { categories: CategoryNode[]; tags: { tag: string; skills: number }[]; assigned_in: Record<string, number> };
