// What a research profile allows, read from its published spec.
// Only spec values are shown; a missing value is left out rather than guessed.

import { getSpecPath, type ResearchPolicySpec } from "./researchPolicySpecHelpers";

function numberAt(spec: ResearchPolicySpec, path: string[]): number | null {
  const value = getSpecPath(spec, path);
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function plural(value: number, noun: string): string {
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}

export function researchProfileAllowances(spec: ResearchPolicySpec | null | undefined): string[] {
  const s = spec || {};
  const parts: string[] = [];
  const min = numberAt(s, ["research_strategy", "min_source_count"]);
  const max = numberAt(s, ["research_strategy", "max_source_count"]);
  const target = numberAt(s, ["research_strategy", "target_source_count"]);
  if (min !== null && max !== null) {
    parts.push(`${min}–${max} sources${target !== null ? ` (target ${target})` : ""}`);
  } else if (max !== null) {
    parts.push(`up to ${plural(max, "source")}`);
  } else if (target !== null) {
    parts.push(`target ${plural(target, "source")}`);
  }
  const rounds = numberAt(s, ["research_strategy", "max_search_rounds"]);
  if (rounds !== null) parts.push(`up to ${plural(rounds, "search round")}`);
  const children = numberAt(s, ["delegation_policy", "max_child_agents"]);
  if (children !== null) {
    parts.push(children === 0 ? "no child agents" : `up to ${plural(children, "child agent")}`);
  }
  const pages = numberAt(s, ["output_policy", "target_pages", "target"]);
  if (pages !== null) parts.push(`about ${plural(pages, "page")}`);
  return parts;
}

export function researchProfileSummary(spec: ResearchPolicySpec | null | undefined): string {
  const parts = researchProfileAllowances(spec);
  return parts.length ? parts.join(" · ") : "No limits in the spec";
}

// Where the profile in effect comes from, in words ("source default_profile · diagnostics valid").
export function effectiveSourceWords(source: string | null | undefined): string {
  switch (source || "default") {
    case "workspace_assignment":
    case "assignment":
      return "assigned to this Workspace";
    case "default_profile":
      return "the platform's default profile";
    case "default":
    case "builtin":
    case "built_in":
      return "the built-in default";
    default:
      return `from ${String(source).replace(/_/g, " ")}`;
  }
}

// A valid check says nothing; anything else is named once.
export function diagnosticsWords(status: string | null | undefined): string {
  if (!status || status === "valid") return "";
  return ` · check: ${status.replace(/_/g, " ")}`;
}
