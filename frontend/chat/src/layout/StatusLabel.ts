import { createElement } from "react";

// Plain .ts with createElement so unit-test loaders can require it.
// Only exceptions are coloured: a normal state is neutral.

export type StatusTone = "neutral" | "attention" | "problem" | "success" | "info";

const TONES: ReadonlyArray<[RegExp, StatusTone]> = [
  [/^(failed|failure|error|errored|broken|rejected|conflict|sync[ _-]?failed|problem|blocked|denied|red)$/, "problem"],
  [/^(needs[ _-]?you|needs[ _-]?attention|needs[ _-]?approval|needs[ _-]?configuration|needs[ _-]?clarification|waiting[ _-]?for[ _-]?you|action[ _-]?required|overdue|expiring|offline|stale|paused)$/, "attention"],
  [/^(passed|green|approved|success|succeeded)$/, "success"],
  [/^(running|syncing|working|in[ _-]?progress|queued|starting|refining)$/, "info"],
];

export function statusTone(state: string | null | undefined): StatusTone {
  const key = String(state ?? "").trim().toLowerCase();
  if (!key) return "neutral";
  for (const [pattern, tone] of TONES) if (pattern.test(key)) return tone;
  return "neutral";
}

export type StatusLabelProps = {
  label: string;
  tone?: StatusTone;
  title?: string;
  testId?: string;
};

export function StatusLabel({ label, tone, title, testId }: StatusLabelProps) {
  const resolved = tone ?? statusTone(label);
  return createElement(
    "span",
    { className: `ds-status ds-status--${resolved}`, title: title || undefined, "data-tone": resolved, "data-testid": testId },
    label,
  );
}
