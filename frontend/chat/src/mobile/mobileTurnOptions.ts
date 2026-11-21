// A turn's options (model, effort, permission mode), Server model choices and the router's model suggestion.

// --- the turn's options: model, effort, permission mode (as Claude Code offers them) ----------------

export type TurnOptions = {
  model: string;
  effort: string;
  permissionMode: string;
};
export const DEFAULT_TURN_OPTIONS: TurnOptions = {
  model: "",
  effort: "",
  permissionMode: "",
};
export const EFFORT_CHOICES: { id: string; label: string }[] = [
  { id: "", label: "Effort" },
  { id: "low", label: "Low effort" },
  { id: "medium", label: "Medium effort" },
  { id: "high", label: "High effort" },
  { id: "xhigh", label: "X-high effort" },
  { id: "max", label: "Max effort" },
];
export const MODE_CHOICES: { id: string; label: string }[] = [
  { id: "", label: "Ask first" },
  { id: "acceptEdits", label: "Accept edits" },
  { id: "plan", label: "Plan only" },
  { id: "bypassPermissions", label: "Bypass" },
];

const TURN_OPTIONS_KEY = "octryx.mobile.turnOptions";

/** The options kept for a thread (or the last ones used for a new chat); invalid values fall back to the default. */
export function readTurnOptions(raw: string | null): TurnOptions {
  try {
    const value = JSON.parse(raw ?? "{}") as Record<string, unknown>;
    const pick = (key: string, allowed: string[] | null) => {
      const item = typeof value[key] === "string" ? (value[key] as string) : "";
      return allowed === null || allowed.includes(item)
        ? item.slice(0, 200)
        : "";
    };
    return {
      model: pick("model", null),
      effort: pick(
        "effort",
        EFFORT_CHOICES.map((choice) => choice.id),
      ),
      permissionMode: pick(
        "permissionMode",
        MODE_CHOICES.map((choice) => choice.id),
      ),
    };
  } catch {
    return { ...DEFAULT_TURN_OPTIONS };
  }
}

export function turnOptionsKey(threadId: string | null): string {
  return `${TURN_OPTIONS_KEY}:${threadId || "new"}`;
}

/** The options a chat starts with. A new chat (``threadId`` null) takes the last model and effort, never a permission
 * mode: it always starts with "Ask first". */
export function initialTurnOptions(
  threadId: string | null,
  getItem: (key: string) => string | null,
): TurnOptions {
  if (threadId) {
    const stored = getItem(turnOptionsKey(threadId));
    if (stored !== null) return readTurnOptions(stored);
  }
  return {
    ...readTurnOptions(getItem(turnOptionsKey(null))),
    permissionMode: "",
  };
}

/** What to store after a change: the chat's own options, and for new chats only the model and effort. */
export function turnOptionsToStore(
  threadId: string | null,
  options: TurnOptions,
): [string, string][] {
  const shared: [string, string] = [
    turnOptionsKey(null),
    JSON.stringify({ model: options.model, effort: options.effort }),
  ];
  return threadId
    ? [[turnOptionsKey(threadId), JSON.stringify(options)], shared]
    : [shared];
}

// --- chats on the Server (start work on the Server too, not only on the Mac) ---

export const SERVER_TARGET = "server";
export type RuntimeChoice = { value: string; label: string; disabled: boolean };
export const THINKING_CHOICES: { id: string; label: string }[] = [
  { id: "off", label: "No thinking" },
  { id: "light", label: "Think briefly" },
  { id: "deep", label: "Think thoroughly" },
];

/** The Server's model choices of a Workspace (the chat bootstrap's ``runtimeOptions``); "" is the automatic one. */
export function readRuntimeChoices(raw: unknown): RuntimeChoice[] {
  const items = (raw as { runtimeOptions?: unknown } | null)?.runtimeOptions;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item): RuntimeChoice[] => {
    const value =
      item && typeof item === "object" ? (item as Record<string, unknown>) : {};
    if (typeof value.value !== "string" || typeof value.label !== "string")
      return [];
    return [
      {
        value: value.value,
        label: value.label,
        disabled: Boolean(
          value.disabled || value.disabledReason || value.disabled_reason,
        ),
      },
    ];
  });
}

/** The modes this person may pick in this Workspace (viewer plan only, member no bypass); the
 * platform enforces the same. ``null`` (not known yet) offers all of them. */
export function readSessionModes(raw: unknown): string[] | null {
  const modes = (raw as { session_modes?: unknown } | null)?.session_modes;
  return Array.isArray(modes)
    ? modes.filter((m): m is string => typeof m === "string")
    : null;
}

export function modeChoices(
  sessionModes: string[] | null,
): { id: string; label: string }[] {
  if (sessionModes === null) return MODE_CHOICES;
  return MODE_CHOICES.filter((choice) =>
    sessionModes.includes(choice.id || "default"),
  );
}

// The local LLM: the Mac's decision model suggests a model and effort per turn (only
// measured: the turn keeps the person's choice), and every compaction is reported with how much it freed.
export type RouteSuggestion = {
  tier: string;
  confidence: number;
  model: string;
  effort: string;
};

const MODEL_SHORT: Record<string, string> = {
  "claude-haiku-5-5": "Haiku",
  "claude-sonnet-5-5": "Sonnet",
  "claude-opus-5-5": "Opus",
};

export function routeSuggestion(
  jobs: { events: { seq: number; body: Record<string, unknown> }[] }[],
): RouteSuggestion | null {
  let found: RouteSuggestion | null = null;
  for (const job of jobs)
    for (const event of job.events) {
      const body = event.body ?? {};
      if (body.kind !== "route" || typeof body.tier !== "string") continue;
      found = {
        tier: body.tier,
        confidence: typeof body.confidence === "number" ? body.confidence : 0,
        model:
          typeof body.suggested_model === "string" ? body.suggested_model : "",
        effort:
          typeof body.suggested_effort === "string"
            ? body.suggested_effort
            : "",
      };
    }
  return found;
}

/** "Router: Haiku · low · 95 %" */
export function routeLabel(route: RouteSuggestion): string {
  const model = MODEL_SHORT[route.model] ?? route.model;
  return `Router: ${model} · ${route.effort} · ${Math.round(route.confidence * 100)} %`;
}
