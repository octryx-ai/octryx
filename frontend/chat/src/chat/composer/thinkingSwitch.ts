// The composer's one thinking control: "Off / Quick / Thorough" map onto
// the thinking levels off / light / deep. There is no second thinking select. Pure data, shared by the composer and
// the header summary.

export type ThinkingLevel = "off" | "light" | "deep";

export const THINKING_LEVEL_LABELS: Record<ThinkingLevel, string> = {
  off: "Off",
  light: "Quick",
  deep: "Thorough",
};

/** The switch's three options, in order. */
export const THINKING_SWITCH: Array<{ value: ThinkingLevel; label: string }> = [
  { value: "off", label: THINKING_LEVEL_LABELS.off },
  { value: "light", label: THINKING_LEVEL_LABELS.light },
  { value: "deep", label: THINKING_LEVEL_LABELS.deep },
];

/** Each option's tooltip: what the level does, in one line. */
export const THINKING_SWITCH_TITLES: Record<ThinkingLevel, string> = {
  off: "Thinking off: answer directly",
  light: "Quick: think briefly before answering",
  deep: "Thorough: think longer before answering",
};

/** The person's word for a thinking level ("light" → "Quick"); an unknown level reads as Quick, the default. */
export function thinkingLevelLabel(level: string | null | undefined): string {
  const key = String(level || "").trim().toLowerCase();
  if (key in THINKING_LEVEL_LABELS) return THINKING_LEVEL_LABELS[key as ThinkingLevel];
  const byLabel = Object.values(THINKING_LEVEL_LABELS).find((label) => label.toLowerCase() === key);
  return byLabel ?? THINKING_LEVEL_LABELS.light;
}
