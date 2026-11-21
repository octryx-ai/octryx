// Wire types of the prompt catalog admin API (/api/v1/prompt-catalog,
// backend/app/services/prompt_catalog/views.py).

export type PromptRisk = "standard" | "high";
// Precedence when a run resolves a text: global < workflow:<flow key> < workspace:<id>.
export type PromptScopeType = "global" | "workflow" | "workspace";
export type PromptVersionState = "draft" | "in_review" | "published" | "retired";
export type PromptVersionSource = "seed" | "admin";

export type PromptVersion = {
  id: string;
  version: number;
  state: PromptVersionState;
  source: PromptVersionSource;
  digest: string;
  change_note: string;
  created_by: string;
  created_at: string | null;
  approval_id: string | null;
  published_by: string | null;
  published_at: string | null;
  retired_at: string | null;
  body?: string;
  placeholders_used?: string[];
};

export type PromptSpec = {
  key: string;
  area: string;
  title: string;
  description: string;
  risk: PromptRisk;
  placeholders: string[];
  // Served verbatim (tool and MCP descriptions): no placeholders, braces are plain text.
  literal?: boolean;
  // Sub-group inside the area, as display text (backend PromptKeySpec); missing → "Other".
  group?: string | null;
  // Fixed order of the sub-groups (backend); null sorts after the numbered ones.
  group_order?: number | null;
  // Placeholder name → one short sentence (backend PromptKeySpec); a missing entry shows the name only.
  placeholder_descriptions?: Record<string, string>;
};

// A scope the current user may write a draft for, with its display name (workspace or workflow name).
export type PromptWritableScope = {
  scope_type: PromptScopeType;
  scope_id: string | null;
  label?: string | null;
};

export type PromptListResponse = {
  items: PromptListItem[];
  count: number;
  areas: Record<string, number>;
  collapsed_areas: string[];
};

export type PromptListItem = PromptSpec & {
  published: PromptVersion | null;
  seed_digest: string;
  open_versions: number;
  override_count: number;
};

export type PromptTemplateView = {
  id: string;
  key: string;
  scope_type: PromptScopeType;
  scope_id: string | null;
  scope_key: string;
  versions: PromptVersion[];
};

export type PromptDetail = PromptSpec & {
  seed: string;
  seed_digest: string;
  templates: PromptTemplateView[];
  writable_scopes?: PromptWritableScope[];
};

export type PromptDiff = {
  version_id: string;
  baseline: string;
  identical: boolean;
  diff: string;
};

export type PromptApprovalGate = {
  status: string;
  approval_id: string | null;
  requested_by?: string | null;
  approved_by?: string | null;
  dev_self_approval?: boolean;
  /** "self" when the author approved their own review under the approval rule. */
  approval_mode?: string | null;
};

export type PromptPublishResult = { version: PromptVersion; approval_gate: PromptApprovalGate | null };

export type DraftInput = {
  scope_type: PromptScopeType;
  scope_id: string | null;
  body: string;
  change_note: string;
};
