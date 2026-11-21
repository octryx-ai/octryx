// Skill catalog response types for delivery, sources, settings, usage, import inspection and assignments.
import type { CategoryNode, LaunchSpec, SpecIssue, Surface } from "./skillCatalogTypes";

export type Readiness = { state: "ready" | "restricted" | "needs_mcp_policy" | string; refusals: { tool: string; policy: string; reason: string; rule: string | null }[] };
export type SurfaceReach = { delivered: boolean; assigned_by: string; reason: string; readiness: Readiness | null };
export type WorkspaceReach = { project_id: string; name: string; surfaces: Partial<Record<Surface, SurfaceReach>> };

export type DeliveryPreview = {
  kind: "skill" | "mcp_server";
  plugin: string;
  command?: string;
  deliverable?: boolean;
  files: { path: string; size: number }[];
  skill_md: string | null;
  scripts_withheld: string[];
  stripped_keys: string[];
  server?: { command: string; args: string[]; env: Record<string, string> };
  image_digest?: string | null;
  env_unset?: string[];
};

export type SourceRow = {
  id: string;
  kind: "git" | "upload" | "marketplace" | string;
  label: string;
  trust: "official" | "community" | "internal" | string;
  url: string | null;
  ref: string | null;
  base_path: string;
  named_connection_id: string | null;
  licence_detected: string | null;
  last_checked_at: string | null;
  last_seen_commit: string | null;
  last_error: string | null;
  skills: number;
};
export type CatalogSettings = {
  licence_allowlist: string[];
  allowed_hosts: string[];
  update_check_hours: number;
  always_allowed_licences: string[];
};

export type UsageEntry = { skill_id: string; name: string; uses: number; refusals: number; by_surface: Record<string, number>; last_used_at: string | null };
export type UsageSummary = { days: number; skills: UsageEntry[]; unmanaged: { name: string; uses: number }[]; totals: { uses: number; refusals: number } };

export type InspectItem = {
  kind: "skill" | "mcp_server";
  path: string;
  name: string;
  description?: string;
  /** Skills: the number of files; MCP server entries: the plugin files. */
  files: number | string[];
  scripts?: string[];
  execution_keys?: string[];
  spec_issues?: SpecIssue[];
  importable: boolean;
  licence: { spdx: string | null; source: string; allowed: boolean };
  /** A skill with this name exists: `update` (same source and path → use its update) or `name_taken`. */
  existing: { skill_id: string; relation: "update" | "name_taken"; kind: string } | null;
  launch_spec?: LaunchSpec;
  security?: { high: number; medium: number; info: number };
  problem?: unknown;
};
export type InspectResult = {
  url: string;
  ref: string;
  commit: string;
  path: string;
  plugin: { name: string; [key: string]: unknown } | null;
  licence: { spdx: string | null; source: string } | null;
  skills: InspectItem[];
  mcp_servers: InspectItem[];
  ignored: { path: string; reason: string }[];
};

export type AssignmentMode = "all_active" | "selected_only" | "none";
export type AssignmentPolicy = {
  mode: AssignmentMode;
  skill_ids: string[];
  category_keys: string[];
  blocked_skill_ids: string[];
  surfaces: Record<Surface, boolean>;
};
export type AssignmentSkill = { id: string; name: string; kind: string; description: string; version: number; category_key: string | null; category_path: string[] };
export type EffectiveRow = { skill_id: string; name: string; kind: string; version: number; category_path: string[]; assigned_by: string; readiness?: Readiness; reason?: string };
export type Assignment = {
  project_id: string;
  digest: string;
  policy: AssignmentPolicy;
  categories: CategoryNode[];
  skills: AssignmentSkill[];
  effective: Record<Surface, EffectiveRow[]>;
  withheld: Record<Surface, EffectiveRow[]>;
};
