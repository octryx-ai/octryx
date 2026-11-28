// A workflow check's type in words, never the raw code ("tool_called"). The
// stored type stays the server's closed code (backend services/workflow_checks/library.py CHECK_TYPES). Pure.

const CHECK_TYPE_LABELS: Record<string, string> = {
  tool_called: "A tool was called",
  tool_not_called: "A tool was not called",
  evidence_count: "Enough evidence collected",
  artifact_created: "An artifact was created",
  citations_present: "The answer cites its sources",
  urls_cited: "Sources cited as URLs",
  answer_contains_any: "The answer contains a phrase",
  field_present: "A field is present",
  test_command_passed: "The test command passed",
  tests_red: "Tests fail first (red)",
  tests_green: "Tests pass (green)",
  confirmed_tests_intact: "Confirmed tests unchanged",
  ci_green: "CI is green",
  reproduces: "The problem is reproduced",
  review_passed: "The review passed",
  artefact_review_passed: "The artefact review passed",
  slices_merged: "Every slice is merged",
  definition_of_ready: "Definition of Ready complete",
  specification_ready: "Specification ready",
  ci_findings_addressed: "CI findings addressed",
  evidence_families: "Every evidence family answered",
  judge: "Judge (advisory)",
};

// The check types whose parameters name tools (params.tools); the editor offers them as a field.
export const TOOL_LIST_CHECK_TYPES = new Set(["tool_called", "tool_not_called", "evidence_count"]);

export function checkTypeLabel(type: string): string {
  if (CHECK_TYPE_LABELS[type]) return CHECK_TYPE_LABELS[type];
  const words = type.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Check";
}
