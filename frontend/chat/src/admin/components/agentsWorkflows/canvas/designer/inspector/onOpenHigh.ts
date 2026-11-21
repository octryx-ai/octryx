// What a confirmation box does when a high finding is still open after the automatic revisions (``on_open_high``,
// backend workflow_runs/auto_accept.py): wait for a person, or continue and put the findings on the
// pull request. Unset means the workflow's default. Pure, so the side panel and the unit tests share it.

export const ON_OPEN_HIGH_KEY = "on_open_high";
export type OnOpenHigh = "wait" | "continue_with_findings";
export const ON_OPEN_HIGH_VALUES: readonly OnOpenHigh[] = ["wait", "continue_with_findings"];

/** The workflows that continue by default (backend ``CONTINUE_BY_DEFAULT``, kept identical): an epic's stories run
 * unattended. */
const CONTINUE_BY_DEFAULT = new Set(["epic-delivery"]);

export const ON_OPEN_HIGH_LABEL = "When a high finding is still open after the automatic revisions";

const NAMES: Record<OnOpenHigh, string> = {
  wait: "Wait for a person",
  continue_with_findings: "Continue; findings on the pull request",
};

/** What an unset ``on_open_high`` means in this workflow. */
export function onOpenHighDefault(workflowKey: string | null | undefined): OnOpenHigh {
  return CONTINUE_BY_DEFAULT.has(String(workflowKey ?? "")) ? "continue_with_findings" : "wait";
}

/** The select's choices: the workflow default (removes the key, value "") names what it means, then the two values. */
export function onOpenHighChoices(workflowKey: string | null | undefined): {
  empty: string; options: { value: OnOpenHigh; label: string }[];
} {
  const fallback = NAMES[onOpenHighDefault(workflowKey)];
  return {
    empty: `Workflow default (${fallback[0].toLowerCase()}${fallback.slice(1)})`,
    options: ON_OPEN_HIGH_VALUES.map((value) => ({ value, label: NAMES[value] })),
  };
}

/** The backend's ``on_open_high`` check in plain words: only on a confirmation box, only one of the two values. */
export function onOpenHighIssue(type: string, config: Record<string, unknown>): string | null {
  const value = config[ON_OPEN_HIGH_KEY];
  if (value === undefined) return null;
  if (type !== "user_confirmation")
    return "Only a confirmation box can say what happens with an open high finding.";
  return ON_OPEN_HIGH_VALUES.includes(value as OnOpenHigh) ? null : "Choose what happens when a high finding is still open.";
}

/** The read-only panel's sentence for a confirmation that sends work back on its own (``auto_revise``) or sets the
 * key; "" otherwise, where the setting changes nothing. */
export function onOpenHighSentence(config: Record<string, unknown>, workflowKey: string | null | undefined): string {
  const value = config[ON_OPEN_HIGH_KEY];
  if (value === undefined && !config.auto_revise) return "";
  const effective = ON_OPEN_HIGH_VALUES.includes(value as OnOpenHigh) ? (value as OnOpenHigh) : onOpenHighDefault(workflowKey);
  const what = effective === "continue_with_findings"
    ? "the run continues and the findings go on the pull request"
    : "the run waits for a person";
  return `If a high finding is still open after the automatic revisions, ${what}${value === undefined ? " (workflow default)" : ""}.`;
}
