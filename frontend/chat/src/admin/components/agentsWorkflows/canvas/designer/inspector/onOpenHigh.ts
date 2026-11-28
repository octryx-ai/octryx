export const ON_OPEN_HIGH_KEY = "on_open_high";
export type OnOpenHigh = "wait" | "continue_with_findings";
export const ON_OPEN_HIGH_VALUES: readonly OnOpenHigh[] = ["wait", "continue_with_findings"];

export const ON_OPEN_HIGH_LABEL = "When a high finding is still open after the automatic revisions";

const NAMES: Record<OnOpenHigh, string> = {
  wait: "Wait for a person",
  continue_with_findings: "Continue; findings on the pull request",
};

/** Unset waits, as in the backend; a workflow that continues says so on its confirmation box. */
const DEFAULT: OnOpenHigh = "wait";

export function onOpenHighChoices(): {
  empty: string; options: { value: OnOpenHigh; label: string }[];
} {
  const fallback = NAMES[DEFAULT];
  return {
    empty: `Default (${fallback[0].toLowerCase()}${fallback.slice(1)})`,
    options: ON_OPEN_HIGH_VALUES.map((value) => ({ value, label: NAMES[value] })),
  };
}

export function onOpenHighIssue(type: string, config: Record<string, unknown>): string | null {
  const value = config[ON_OPEN_HIGH_KEY];
  if (value === undefined) return null;
  if (type !== "user_confirmation")
    return "Only a confirmation box can say what happens with an open high finding.";
  return ON_OPEN_HIGH_VALUES.includes(value as OnOpenHigh) ? null : "Choose what happens when a high finding is still open.";
}

export function onOpenHighSentence(config: Record<string, unknown>): string {
  const value = config[ON_OPEN_HIGH_KEY];
  if (value === undefined && !config.auto_revise) return "";
  const effective = ON_OPEN_HIGH_VALUES.includes(value as OnOpenHigh) ? (value as OnOpenHigh) : DEFAULT;
  const what = effective === "continue_with_findings"
    ? "the run continues and the findings go on the pull request"
    : "the run waits for a person";
  return `If a high finding is still open after the automatic revisions, ${what}${value === undefined ? " (default)" : ""}.`;
}
