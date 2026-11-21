// Workspace › Coding tools & devices › "Workflow runs on devices": the phases that get a browser and the phases that
// must research on the web (and how many sources they need) (backend services/devices/device_runs_keys.py;
// PUT …/agent-gateway/device-runs). Pure: no React.
//
// The PUT merges only top-level keys into the stored section, so a patch names one key.

// The server's limits (device_runs_keys: MAX_BROWSER_PHASES, MAX_BROWSER_PHASE_CHARS, _BROWSER_PHASE).
export const MAX_BROWSER_PHASES = 20;
export const MAX_BROWSER_PHASE_CHARS = 120;
// research_min_sources: _BOUNDS (1, 20), DEFAULTS 3.
export const MIN_SOURCES_LOW = 1;
export const MIN_SOURCES_HIGH = 20;
export const DEFAULT_MIN_SOURCES = 3;
const BROWSER_PHASE = /^[A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z0-9_][A-Za-z0-9_.:-]*$/;

export type RunPhaseSettings = {
  browserPhases: string[];
  researchPhases: string[];
  researchMinSources: number;
  canEdit: boolean;
  policyValid: boolean;
};

const minSources = (value: unknown) =>
  typeof value === "number" && Number.isInteger(value) && value >= MIN_SOURCES_LOW && value <= MIN_SOURCES_HIGH
    ? value : DEFAULT_MIN_SOURCES;
const texts = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

export function readRunPhaseSettings(raw: unknown): RunPhaseSettings | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  if (typeof item.project_id !== "string") return null;
  return {
    browserPhases: texts(item.browser_phases),
    researchPhases: texts(item.research_phases),
    researchMinSources: minSources(item.research_min_sources),
    canEdit: item.can_edit === true,
    policyValid: item.policy_valid !== false,
  };
}

/** Why a typed phase cannot be added (the server's own rule, in words); null when it can. Browser and research
 * phases share the rule (device_runs_keys._browser_phases); `example` only changes the hint. */
export function browserPhaseProblem(draft: string, current: readonly string[],
  example = "epic-delivery.implement"): string | null {
  const value = draft.trim();
  if (!value) return `Enter a phase, for example ${example}.`;
  if (value.length > MAX_BROWSER_PHASE_CHARS) return `A phase has at most ${MAX_BROWSER_PHASE_CHARS} characters.`;
  if (!BROWSER_PHASE.test(value)) {
    return `Write it as <workflow>.<phase>, for example ${example} (letters, digits, - and _).`;
  }
  if (current.includes(value)) return "This phase is already listed.";
  if (current.length >= MAX_BROWSER_PHASES) return `At most ${MAX_BROWSER_PHASES} phases.`;
  return null;
}

export const browserPhasesPatch = (phases: readonly string[]) => ({ browser_phases: [...phases] });
export const researchPhasesPatch = (phases: readonly string[]) => ({ research_phases: [...phases] });
export const researchMinSourcesPatch = (count: number) => ({ research_min_sources: count });

/** The typed minimum as the server's integer, or the reason in words. */
export function minSourcesValue(draft: string): { value: number } | { problem: string } {
  const text = draft.trim();
  const value = /^\d+$/.test(text) ? Number(text) : NaN;
  if (!Number.isInteger(value) || value < MIN_SOURCES_LOW || value > MIN_SOURCES_HIGH) {
    return { problem: `Enter a whole number from ${MIN_SOURCES_LOW} to ${MIN_SOURCES_HIGH}.` };
  }
  return { value };
}

const REASONS: Record<string, string> = {
  invalid_browser_phases: `Each phase is <workflow>.<phase> with up to ${MAX_BROWSER_PHASE_CHARS} characters; at most ${MAX_BROWSER_PHASES} phases.`,
  invalid_research_phases: `Each research phase is <workflow>.<phase> with up to ${MAX_BROWSER_PHASE_CHARS} characters; at most ${MAX_BROWSER_PHASES} phases.`,
  invalid_number: `Minimum sources is a whole number from ${MIN_SOURCES_LOW} to ${MIN_SOURCES_HIGH}.`,
  invalid_device_runs: "The server did not accept this setting; reload the page and try again.",
  agent_gateway_policy_invalid: "The Workspace's coding-tool policy has an invalid value; fix it in this section first.",
  workspace_admin_required: "Only the Workspace's admins and owners change this.",
  workspace_not_found: "This Workspace no longer exists or you are no longer a member.",
};

/** A refused save in words, shown at the field. */
export function runPhaseSaveError(error: unknown): string {
  const { status, code } = (error ?? {}) as { status?: number; code?: string | null };
  if (code && REASONS[code]) return REASONS[code];
  if (status === 403) return REASONS.workspace_admin_required;
  if (status === 404) return REASONS.workspace_not_found;
  return "The change could not be saved. Try again.";
}
