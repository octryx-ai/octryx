import { createElement } from "react";

// The one state label of the UI (design system, product inventory). Plain .ts with createElement so every
// component and its unit-test loader can require it; styles in styles/chat/design-system.css.
//
// Colour has a fixed meaning and only exceptions are coloured: a normal state (open, running, synced, merged) is
// neutral; attention means a person must act; problem means something failed; success is used sparingly for a
// result worth noticing (a check that passed); info marks something in progress worth seeing.

export type StatusTone = "neutral" | "attention" | "problem" | "success" | "info";

const TONES: ReadonlyArray<[RegExp, StatusTone]> = [
  [/^(failed|failure|error|errored|broken|rejected|conflict|sync[ _-]?failed|problem|blocked|denied|red)$/, "problem"],
  [/^(needs[ _-]?you|needs[ _-]?attention|needs[ _-]?approval|needs[ _-]?configuration|needs[ _-]?clarification|waiting[ _-]?for[ _-]?you|action[ _-]?required|overdue|expiring|offline|stale|paused)$/, "attention"],
  [/^(passed|green|approved|success|succeeded)$/, "success"],
  [/^(running|syncing|working|in[ _-]?progress|queued|starting|refining)$/, "info"],
];

/** The tone of a state word ("Failed", "needs_you", "running"); everything not listed is neutral. */
export function statusTone(state: string | null | undefined): StatusTone {
  const key = String(state ?? "").trim().toLowerCase();
  if (!key) return "neutral";
  for (const [pattern, tone] of TONES) if (pattern.test(key)) return tone;
  return "neutral";
}

export type StatusLabelProps = {
  // The state in the user's words ("Needs you", "Synced"); shown as is.
  label: string;
  // Defaults to statusTone(label).
  tone?: StatusTone;
  // The reason in one sentence, as tooltip and accessible description.
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
