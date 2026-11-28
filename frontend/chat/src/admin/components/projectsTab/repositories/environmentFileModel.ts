// Mirrors the server's validate_environment_file (workflow_runs/workspace/spec.py) to catch a wrong path before the round trip.

export const ENVIRONMENT_FILE_KEY = "environment_file";
export const ENVIRONMENT_FILE_MAX = 200;
export const ENVIRONMENT_FILE_LABEL = "Environment file";
export const ENVIRONMENT_FILE_PLACEHOLDER = "app/.octryx/environment.json";
export const ENVIRONMENT_FILE_HINT =
  "When set, the file in the run's branch declares the test commands (it wins over the environment declared here); " +
  "commands run in the folder that contains .octryx/.";
export const ENVIRONMENT_FILE_INVALID =
  "Use a path inside the repository to a .json file: relative, no '..' or backslash, at most 200 characters " +
  "(for example app/.octryx/environment.json).";

export function environmentFileError(raw: string): string | null {
  const text = raw.trim();
  if (!text) return null;
  const parts = text.split("/");
  const name = parts[parts.length - 1];
  if (text.length > ENVIRONMENT_FILE_MAX || text.startsWith("/") || text.includes("\\") || parts.includes("..")
    || !text.endsWith(".json") || name === ".json") return ENVIRONMENT_FILE_INVALID;
  return null;
}

export function environmentFileText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Unchanged sends nothing (the server keeps it); cleared sends null. */
export function environmentFileBody(stored: unknown, draft: string): Record<string, string | null> {
  const next = draft.trim();
  if (next === environmentFileText(stored).trim()) return {};
  return { [ENVIRONMENT_FILE_KEY]: next || null };
}

export function environmentFileServerError(error: unknown): string | null {
  const code = error && typeof error === "object" ? (error as { code?: unknown }).code : null;
  return code === "invalid_environment_file" ? ENVIRONMENT_FILE_INVALID : null;
}
