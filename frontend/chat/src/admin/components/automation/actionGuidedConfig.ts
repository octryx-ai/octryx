// Guided Action authoring: the capability choices, reserved keys and the Config (JSON) text as the form reads it.

export const CAPABILITY_CHOICES = [
  {
    value: "read_only",
    label: "Read only",
    detail:
      "Answers and investigates; it makes no changes. This is the default.",
  },
  {
    value: "change",
    label: "Change",
    detail:
      "May also edit files in its run workspace and run builds and tests. Execution policy and guardrails still apply.",
  },
  {
    value: "deliver",
    label: "Deliver",
    detail:
      "May additionally push, open pull requests and write to external systems. Workspace policy and approval rules still apply.",
  },
] as const;
const CAPABILITY_VALUES: readonly string[] = CAPABILITY_CHOICES.map(
  (choice) => choice.value,
);

/** Config keys the form owns through its own fields; typing them into the JSON would be silently replaced. */
export const RESERVED_CONFIG_KEYS = [
  "agent_definition_id",
  "max_iterations",
] as const;

// ---- the one config source: the Config (JSON) text --------------------------------------------

export type ParsedConfig =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; message: string };

export function parseConfig(text: string): ParsedConfig {
  try {
    const value: unknown = JSON.parse(text || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { ok: false, message: "Config must be a JSON object." };
    }
    return { ok: true, value: value as Record<string, unknown> };
  } catch {
    return { ok: false, message: "Config is not valid JSON." };
  }
}

/** The text with one key set (or removed); every other key and value is kept as parsed. */
export function withConfigKey(
  text: string,
  key: string,
  value: unknown,
): string | null {
  const parsed = parseConfig(text);
  if (!parsed.ok) return null;
  const next = { ...parsed.value };
  if (value === undefined) delete next[key];
  else next[key] = value;
  return JSON.stringify(next, null, 2);
}

export type GuidedConfigView = {
  error: string | null;
  prompt: string;
  capability: string;
  capabilityInvalid: string | null;
  promptInvalid: boolean;
  reserved: string[];
};

export function guidedConfigView(text: string): GuidedConfigView {
  const parsed = parseConfig(text);
  if (!parsed.ok) {
    return {
      error: parsed.message,
      prompt: "",
      capability: "read_only",
      capabilityInvalid: null,
      promptInvalid: false,
      reserved: [],
    };
  }
  const { prompt, capability_class: capability } = parsed.value;
  const capabilityInvalid =
    capability === undefined ||
    (typeof capability === "string" && CAPABILITY_VALUES.includes(capability))
      ? null
      : JSON.stringify(capability);
  return {
    error: null,
    prompt: typeof prompt === "string" ? prompt : "",
    promptInvalid: prompt !== undefined && typeof prompt !== "string",
    capability:
      typeof capability === "string" && CAPABILITY_VALUES.includes(capability)
        ? capability
        : "read_only",
    capabilityInvalid,
    reserved: RESERVED_CONFIG_KEYS.filter((key) => key in parsed.value),
  };
}

/** Reserved keys typed into the JSON: refused instead of being silently replaced on save. */
export function reservedKeyConflict(text: string): string | null {
  const parsed = parseConfig(text);
  if (!parsed.ok) return null;
  const typed = RESERVED_CONFIG_KEYS.filter((key) => key in parsed.value);
  return typed.length
    ? `Remove ${typed.map((key) => `"${key}"`).join(" and ")} from Config (JSON); set ${typed.length > 1 ? "them" : "it"} with the form's own field.`
    : null;
}

