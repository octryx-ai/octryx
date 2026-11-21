import type { ProjectOption } from "../../chatOptionTypes";
import type { WorkItem, WorkItemComment } from "./workItemTypes";

// The Jira side of the Work Item detail, readable. Pure: no React.
//
// Text from Jira (description, comments) is plain text: it is split into paragraphs and simple lists and rendered
// as text, never as HTML. Sprint and board are named; an empty object reads as none. The
// Workspace is shown by its name.

export type TextBlock = { kind: "paragraph"; lines: string[] } | { kind: "list"; items: string[] };

const BULLET = /^\s*(?:[-*•]|#)\s+/;

/** Paragraphs (blank-line separated, lines kept) and bullet lists ("- ", "* ", "• ", "# "). */
export function textBlocks(text: string | null | undefined): TextBlock[] {
  const source = String(text || "").replace(/\r\n?/g, "\n").trim();
  if (!source) return [];
  return source.split(/\n\s*\n/).map((chunk): TextBlock => {
    const lines = chunk.split("\n").map((line) => line.trimEnd()).filter((line) => line.trim());
    if (lines.length && lines.every((line) => BULLET.test(line))) {
      return { kind: "list", items: lines.map((line) => line.replace(BULLET, "").trim()) };
    }
    return { kind: "paragraph", lines };
  });
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const textOf = (value: unknown): string =>
  typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "";

/** "Sprint 5 (active)" or "-"; null or an empty object is none. */
export function sprintText(sprint: unknown): string {
  if (!isRecord(sprint)) return "-";
  const name = textOf(sprint.name) || textOf(sprint.id);
  if (!name) return "-";
  const state = textOf(sprint.state);
  return state ? `${name} (${state})` : name;
}

// Jira writes a sprint without a goal as the text "<null>"; that is no goal.
const NULL_TEXTS = new Set(["<null>", "null", "none"]);

export function sprintGoal(sprint: unknown): string {
  const goal = isRecord(sprint) ? textOf(sprint.goal) : "";
  return NULL_TEXTS.has(goal.toLowerCase()) ? "" : goal;
}

export function boardText(board: unknown): string {
  if (!isRecord(board)) return "-";
  return textOf(board.name) || textOf(board.id) || "-";
}

export function workspaceName(projectId: string | null | undefined, projects: ProjectOption[]): string {
  if (!projectId) return "No Workspace";
  return projects.find((project) => project.id === projectId)?.name || projectId;
}

/** How the work state was mapped from the Jira status, or null when the server does not say. */
export function statusMappingText(item: WorkItem): string | null {
  const mapping = item.status_mapping;
  if (!mapping || !mapping.source) return null;
  if (mapping.source === "configured") return "from this intake's status mapping";
  if (mapping.source === "builtin") return "from the built-in Jira status vocabulary";
  if (mapping.source === "status_category") {
    return `from Jira's status category${mapping.category ? ` “${mapping.category}”` : ""} (the status itself is not mapped)`;
  }
  if (mapping.source === "unmapped") return "not mapped: the status is unknown, so the item stays in Intake";
  return null;
}

export type CommentsView =
  | { state: "not_reported" }
  | { state: "listed"; comments: WorkItemComment[]; older: number };

/** The synced Jira comments; "not_reported" when this server does not sync them. */
export function commentsView(item: WorkItem): CommentsView {
  if (!Array.isArray(item.comments)) return { state: "not_reported" };
  const total = typeof item.comments_total === "number" ? item.comments_total : item.comments.length;
  return { state: "listed", comments: item.comments, older: Math.max(0, total - item.comments.length) };
}

/** A link only when it is an absolute http(s) address. */
export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value.trim())) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}
