// PR review bot › the settings beyond the trigger (backend pr_review_bot/settings.py): fix runs,
// the size brake and the repository's own hotspot paths. Pure: no React. The server's rules, so a refused value is
// named at its field before it is sent: limits are whole numbers from 1 to 100000, at most 50 globs of 1 to 200
// characters each.

export const LIMIT_MIN = 1;
export const LIMIT_MAX = 100_000;
export const MAX_HOTSPOTS = 50;
export const MAX_GLOB = 200;
export const DEFAULT_LINES = 800;
export const DEFAULT_FILES = 25;

export type BotLimits = { fixRuns: boolean; sizeLimitLines: number; sizeLimitFiles: number; hotspotPaths: string[] };
export type LimitField = "fixRuns" | "sizeLimitLines" | "sizeLimitFiles" | "hotspotPaths";
export type LimitErrors = Partial<Record<LimitField, string>> & { hotspots?: Record<string, string> };

export const LIMIT_KEYS = ["fix_runs", "size_limit_lines", "size_limit_files", "hotspot_paths"] as const;
export const DEFAULT_LIMITS: BotLimits = { fixRuns: false, sizeLimitLines: DEFAULT_LINES, sizeLimitFiles: DEFAULT_FILES,
  hotspotPaths: [] };

const inRange = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= LIMIT_MIN && value <= LIMIT_MAX;

/** The stored values, read the way the server reads a stored record: anything out of range falls back to the default. */
export function readBotLimits(stored: Record<string, unknown>): BotLimits {
  const globs = Array.isArray(stored.hotspot_paths)
    ? stored.hotspot_paths.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean)
    : [];
  return {
    fixRuns: stored.fix_runs === true,
    sizeLimitLines: inRange(stored.size_limit_lines) ? stored.size_limit_lines : DEFAULT_LINES,
    sizeLimitFiles: inRange(stored.size_limit_files) ? stored.size_limit_files : DEFAULT_FILES,
    hotspotPaths: [...new Set(globs)],
  };
}

export function botLimitsBody(limits: BotLimits) {
  return {
    fix_runs: limits.fixRuns,
    size_limit_lines: limits.sizeLimitLines,
    size_limit_files: limits.sizeLimitFiles,
    hotspot_paths: limits.hotspotPaths.map((glob) => glob.trim()),
  };
}

export const sameBotLimits = (a: BotLimits, b: BotLimits) =>
  a.fixRuns === b.fixRuns && a.sizeLimitLines === b.sizeLimitLines && a.sizeLimitFiles === b.sizeLimitFiles
  && a.hotspotPaths.length === b.hotspotPaths.length
  && a.hotspotPaths.every((glob, index) => glob.trim() === b.hotspotPaths[index]?.trim());

/** A size limit from its input: a whole number, else NaN (named by limitProblem). */
export const parseLimit = (text: string): number => (/^\s*\d+\s*$/.test(text) ? Number(text) : Number.NaN);

export function limitProblem(value: number): string | null {
  return inRange(value) ? null : `A whole number from ${LIMIT_MIN} to ${LIMIT_MAX.toLocaleString("en")}.`;
}

export function hotspotProblem(glob: string, earlier: readonly string[]): string | null {
  const value = glob.trim();
  if (!value) return "A path cannot be empty.";
  if (value.length > MAX_GLOB) return `A path has at most ${MAX_GLOB} characters.`;
  if (earlier.some((item) => item.trim() === value)) return "This path is listed twice.";
  return null;
}

/** The draft's problems at their fields (per glob for the chips); empty when it can be saved. */
export function botLimitsProblems(limits: BotLimits): LimitErrors {
  const errors: LimitErrors = {};
  const lines = limitProblem(limits.sizeLimitLines);
  const files = limitProblem(limits.sizeLimitFiles);
  if (lines) errors.sizeLimitLines = lines;
  if (files) errors.sizeLimitFiles = files;
  if (limits.hotspotPaths.length > MAX_HOTSPOTS) errors.hotspotPaths = `At most ${MAX_HOTSPOTS} paths.`;
  const hotspots: Record<string, string> = {};
  limits.hotspotPaths.forEach((glob, index) => {
    const problem = hotspotProblem(glob, limits.hotspotPaths.slice(0, index));
    if (problem && !hotspots[glob]) hotspots[glob] = problem;
  });
  if (Object.keys(hotspots).length) errors.hotspots = hotspots;
  return errors;
}

/** A refused save of one of these fields in words, or null when the refusal is about another field. */
export function limitsSaveError(reason: string, path: unknown): LimitErrors | null {
  if (reason === "size_limit_invalid") {
    const field = path === "size_limit_files" ? "sizeLimitFiles" : "sizeLimitLines";
    return { [field]: "The server did not accept this limit. " + (limitProblem(Number.NaN) ?? "") };
  }
  if (reason === "hotspot_paths_invalid") {
    return { hotspotPaths: `The server did not accept these paths: at most ${MAX_HOTSPOTS}, each 1 to ${MAX_GLOB} characters.` };
  }
  return null;
}

export const FIX_RUNS_HINT = "“@octryx fix” and “@octryx write tests” in a pull request comment may push onto that pull "
  + "request's branch (never a protected branch, never forced). Off: the bot only reviews.";
export const SIZE_HINT = "Above either limit the review adds “Large pull request” with a split into stacked pull "
  + "requests. It never blocks and never changes the status.";
export const HOTSPOT_HINT = "Files matching these globs are read with extra care, besides the built-in sensitive "
  + "areas (for example src/payments/**).";
export const REVIEW_SEAT_TITLE = "Review on my seat";
export const REVIEW_SEAT_SUB = "When on, the bot may offer this Workspace's pull request reviews to your device and your "
  + "own Claude subscription. The first free seat takes a review; without one it runs on the company route. Your "
  + "choice only: by default on for admins and owners, off for everyone else.";
