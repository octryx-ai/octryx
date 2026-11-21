// The run's documentation events (workflow_runs/documentation/auto_pages.py) as history lines:
// - `documentation_page_written` (detail: title, url, page_id, version, slot): "Page written: <title>", links the page;
// - `documentation_skipped` (detail.reason): "Documentation skipped: <reason in words>", links the Documentation
//   target card where the Workspace can fix it;
// - `documentation_failed` (detail.reason: a code or the Confluence error's text): "Documentation failed: <reason>".
// Pure: no React.

import { workspaceSectionHref } from "../../admin/components/projectsTab/workspaceSettingsLink";

export const DOCUMENTATION_EVENTS = ["documentation_page_written", "documentation_skipped", "documentation_failed"] as const;

export type RunHistoryLink = { href: string; label: string; external: boolean };
export type DocumentationLine = { title: string; text: string; tone: "neutral" | "attention" | "problem"; link?: RunHistoryLink };

// The skip and stop codes auto_pages.py records, in words.
const REASONS: Record<string, string> = {
  no_parent_page: "no parent page set in Documentation target",
  no_documentation_space: "no space set in Documentation target",
  auto_publish_off: "automatic publishing is off in Documentation target",
  target_drift: "the Documentation target changed since the run started",
  foreign_page: "a page with this title exists and was not created by Octryx",
  page_moved: "the page Octryx created was moved out of the parent",
  spec_unavailable: "the specification of this commit could not be read",
  no_confluence_connection: "no Confluence connection serves this space",
  space_not_allowed: "the Confluence connection does not allow this space",
  parent_unreadable: "the parent page could not be read",
  parent_elsewhere: "the parent page is not in this space",
  no_epic: "the run has no epic",
  no_epic_story: "the story has no epic",
};

// Reasons the Workspace fixes in its Documentation target card.
const FIXED_IN_CARD = new Set(["no_parent_page", "no_documentation_space", "auto_publish_off", "target_drift",
  "no_confluence_connection", "space_not_allowed", "parent_elsewhere"]);

/** A reason code in words; an unknown code with underscores reads as words, a Confluence message stays as it is. */
export function documentationReasonText(reason: unknown): string {
  const value = String(reason ?? "").trim();
  if (!value) return "no reason given";
  if (REASONS[value]) return REASONS[value];
  return /^[a-z0-9_]+$/.test(value) ? value.replace(/_/g, " ") : value;
}

const safeUrl = (value: unknown) => {
  const url = String(value ?? "").trim();
  return /^https?:\/\//i.test(url) ? url : "";
};

/** The line for a documentation event, or null for any other event. */
export function documentationLine(kind: string, detail: Record<string, unknown>, projectId?: string | null): DocumentationLine | null {
  const reason = String(detail.reason ?? "").trim();
  if (kind === "documentation_page_written") {
    const url = safeUrl(detail.url);
    const title = String(detail.title ?? "").trim() || "Documentation page";
    return { title: "Page written", text: title, tone: "neutral", ...(url ? { link: { href: url, label: "Open page", external: true } } : {}) };
  }
  if (kind === "documentation_skipped") {
    const link = projectId && FIXED_IN_CARD.has(reason)
      ? { href: workspaceSectionHref(projectId, "documentation"), label: "Documentation target", external: false }
      : undefined;
    return { title: "Documentation skipped", text: documentationReasonText(reason), tone: "attention", ...(link ? { link } : {}) };
  }
  if (kind === "documentation_failed") {
    return { title: "Documentation failed", text: documentationReasonText(reason), tone: "problem" };
  }
  return null;
}
