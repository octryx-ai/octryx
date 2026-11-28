export type ThinkingLevel = "off" | "light" | "deep";

export const THINKING_LEVEL_LABELS: Record<ThinkingLevel, string> = {
  off: "Off",
  light: "Quick",
  deep: "Thorough",
};

export const THINKING_SWITCH: Array<{ value: ThinkingLevel; label: string }> = [
  { value: "off", label: THINKING_LEVEL_LABELS.off },
  { value: "light", label: THINKING_LEVEL_LABELS.light },
  { value: "deep", label: THINKING_LEVEL_LABELS.deep },
];

export const THINKING_SWITCH_TITLES: Record<ThinkingLevel, string> = {
  off: "Thinking off: answer directly",
  light: "Quick: think briefly before answering",
  deep: "Thorough: think longer before answering",
};

export function thinkingLevelLabel(level: string | null | undefined): string {
  const key = String(level || "").trim().toLowerCase();
  if (key in THINKING_LEVEL_LABELS) return THINKING_LEVEL_LABELS[key as ThinkingLevel];
  const byLabel = Object.values(THINKING_LEVEL_LABELS).find((label) => label.toLowerCase() === key);
  return byLabel ?? THINKING_LEVEL_LABELS.light;
}
