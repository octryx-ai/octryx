// The file review workspace model: feedback form state, file candidates, editor content, feedback context, language.
import type { WorkAgentFeedbackContext, WorkCodingReviewEvent, WorkCodingReviewEventType } from "../work/workCodingReviewTypes";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit } from "../work/workPullRequestTypes";
import type { CodingSessionSummary } from "./codingTypes";
import { extractNamedValues, recordValue } from "./codingSessionValues";

export type ReviewFormState = {
  eventType: WorkCodingReviewEventType;
  severity: WorkCodingReviewEvent["severity"];
  lineNumber: string;
  body: string;
  updatedContent: string;
};

// File feedback only. Approve / Request changes / Reject is recorded once, in the Reviews tab,
// so a file comment never reads as an approval of all changes.
export const EVENT_TYPES: Array<{ value: WorkCodingReviewEventType; label: string }> = [
  { value: "inline_comment", label: "Inline comment" },
  { value: "manual_edit", label: "Manual edit" },
  { value: "diagnostic", label: "Diagnostic" },
];

export const DEFAULT_FORM: ReviewFormState = {
  eventType: "inline_comment",
  severity: "medium",
  lineNumber: "",
  body: "",
  updatedContent: "",
};
export function fileCandidates(session: CodingSessionSummary, changeUnits: WorkChangeUnit[], latestPlan: WorkChangePlan | null): string[] {
  const sourceFields = recordValue(session.workItem.source_fields);
  return uniqueStrings([
    ...extractFileValues(sourceFields?.planned_files),
    ...extractFileValues(latestPlan?.planned_files),
    ...changeUnits.flatMap((unit) => unit.expected_paths),
  ]);
}

export function extractFileValues(value: unknown): string[] {
  return extractNamedValues(value, ["path", "file_path", "file", "name"]).filter((item) => item.includes(".") || item.includes("/"));
}

export function buildEditorContent({
  session,
  selectedFile,
  selectedChangeUnit,
  fileEvents,
}: {
  session: CodingSessionSummary;
  selectedFile: string;
  selectedChangeUnit?: WorkChangeUnit;
  fileEvents: WorkCodingReviewEvent[];
}): string {
  const latestOriginal = [...fileEvents].reverse().find((event) => event.original_content)?.original_content;
  if (latestOriginal) {
    return latestOriginal;
  }
  return [
    `// Review target: ${selectedFile}`,
    `// Work item: ${session.sourceKey}`,
    `// Repository: ${selectedChangeUnit?.repository_name || session.repositories[0] || "pending"}`,
    `// Branch: ${selectedChangeUnit?.branch_name || session.branches[0] || "pending"}`,
    "",
    "// No captured source snapshot is attached yet.",
    "// Reviewer feedback saved here is persisted as agent feedback context.",
  ].join("\n");
}

export function buildFeedbackContext(
  events: WorkCodingReviewEvent[],
  serverContext?: WorkAgentFeedbackContext | null,
): WorkAgentFeedbackContext {
  const counts = events.reduce<Record<string, number>>((current, event) => {
    current[event.event_type] = (current[event.event_type] || 0) + 1;
    return current;
  }, {});
  return {
    event_count: events.length,
    counts,
    changed_files: uniqueStrings(events.map((event) => event.file_path)),
    human_edits: events.filter((event) => event.event_type === "manual_edit"),
    reviewer_comments: events.filter((event) => event.event_type !== "manual_edit" && event.event_type !== "diagnostic"),
    diagnostics: events.filter((event) => event.event_type === "diagnostic"),
    constraints: uniqueStrings(events.flatMap((event) => {
      const context = recordValue(event.agent_context);
      return typeof context?.constraint === "string" ? [context.constraint] : [];
    })),
    agent_instruction: serverContext?.agent_instruction || "Respect human review feedback before continuing implementation.",
  };
}

export function labelForEvent(eventType: string): string {
  return eventType.replaceAll("_", " ");
}

export function languageForPath(filePath: string): string {
  if (filePath.endsWith(".py")) {
    return "python";
  }
  if (filePath.endsWith(".ts") || filePath.endsWith(".tsx")) {
    return "typescript";
  }
  if (filePath.endsWith(".json")) {
    return "json";
  }
  if (filePath.endsWith(".css")) {
    return "css";
  }
  return "plaintext";
}

export function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right));
}
