import type { ConnectorConfig, ConnectorScope, SourceConnector } from "./connectorTypes";

// The bounds mirror the server's validation only to explain a refusal early; the server stays the authority.

export type GitRepositoryFields = {
  repositoryUrl: string;
  ref: string;
  includeGlobs: string;
  excludeGlobs: string;
  maxFiles: string;
  maxFileBytes: string;
};

export const EMPTY_GIT_FIELDS: GitRepositoryFields = {
  repositoryUrl: "", ref: "", includeGlobs: "", excludeGlobs: "", maxFiles: "", maxFileBytes: "",
};

export const MAX_FILES = { min: 1, max: 5000, serverDefault: 2000 } as const;
export const MAX_FILE_BYTES = { min: 1024, max: 2 * 1024 * 1024, serverDefault: 512 * 1024 } as const;
const MAX_GLOBS = 20;
const MAX_GLOB_CHARS = 200;
const MAX_REF_CHARS = 100;

const REPOSITORY_URLS: Record<string, RegExp> = {
  "github.com": /^https:\/\/github\.com\/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\/([A-Za-z0-9._-]{1,100})$/,
  "bitbucket.org": /^https:\/\/bitbucket\.org\/([a-z0-9][a-z0-9_-]{0,61})\/([A-Za-z0-9._-]{1,100})$/,
};
const REF_CHARS = /^[A-Za-z0-9._/-]+$/;
const COMMIT_SHA = /^[0-9a-f]{40}$/i;
// The last two path segments, so a Bitbucket Data Center .../scm/PROJ/repo.git reads PROJ/repo.
const REMOTE_REPOSITORY = /^https:\/\/[^/]+\/(?:[^/]+\/)*?([^/]+)\/([^/]+?)(?:\.git)?\/?$/;
const SHORT_SHA = 12;
const MAX_REPOSITORY_URL_CHARS = 300;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

type ScopeResult = { scope: Partial<ConnectorConfig> } | { problem: string };

export function repositoryUrlProblem(raw: string): string | null {
  const url = raw.trim();
  if (!url) return "Enter the repository URL (https://github.com/<owner>/<repo> or https://bitbucket.org/<workspace>/<repo>).";
  // A local repository is no Knowledge source: runs use it through a connection.
  if (/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/i.test(url)) {
    return "A local repository is not read as a Knowledge source. To let runs work in it, add it in Work › Repositories › "
      + "Add a repository for runs, through its connection.";
  }
  if (!url.startsWith("https://")) return "The repository URL must use https.";
  const host = Object.keys(REPOSITORY_URLS).find((name) => url === `https://${name}` || url.startsWith(`https://${name}/`));
  if (!host) return "Only github.com and bitbucket.org repositories are supported for now.";
  const match = REPOSITORY_URLS[host].exec(url);
  const repo = match?.[2] ?? "";
  if (!match || repo === "." || repo === ".." || repo.toLowerCase().endsWith(".git")) {
    const owner = host === "bitbucket.org" ? "<workspace>" : "<owner>";
    return `The repository URL is exactly https://${host}/${owner}/<repo>: no .git suffix, no trailing path.`;
  }
  return null;
}

export function refProblem(raw: string): string | null {
  const ref = raw.trim();
  if (!ref) return "Enter a ref: a branch or tag name, or a full 40-character commit sha.";
  if (ref.length > MAX_REF_CHARS || !REF_CHARS.test(ref) || ref.startsWith("-") || ref.startsWith("/") || ref.includes("..")) {
    return `The ref is at most ${MAX_REF_CHARS} characters of letters, digits and . _ / -, does not start with - or /, `
      + "and does not contain “..”.";
  }
  return null;
}

export function isCommitSha(ref: string): boolean {
  return COMMIT_SHA.test(ref);
}

export function splitGlobs(raw: string): string[] {
  return Array.from(new Set(raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)));
}

function globsProblem(globs: string[], label: string): string | null {
  if (globs.length > MAX_GLOBS) return `Enter at most ${MAX_GLOBS} ${label} globs.`;
  const bad = globs.find((glob) => glob.length > MAX_GLOB_CHARS || CONTROL_CHARS.test(glob));
  return bad === undefined ? null : `Each ${label} glob is at most ${MAX_GLOB_CHARS} characters.`;
}

function boundedInteger(raw: string, bounds: { min: number; max: number }): number | null {
  const text = raw.trim();
  if (!text) return null;
  const value = Number(text);
  return Number.isInteger(value) && value >= bounds.min && value <= bounds.max ? value : Number.NaN;
}

function connectionRepositoryUrlProblem(raw: string): string | null {
  const url = raw.trim();
  if (!url.startsWith("https://") || url.length > MAX_REPOSITORY_URL_CHARS || CONTROL_CHARS.test(url)) {
    return "The repository URL must be the https address the connection lists.";
  }
  return null;
}

// Every save sends the connection id, or the server reads the URL as a public repository.
export function gitRepositoryScope(fields: GitRepositoryFields & { connectionId?: string }): ScopeResult {
  const connectionId = fields.connectionId?.trim() ?? "";
  const problem = (connectionId ? connectionRepositoryUrlProblem(fields.repositoryUrl) : repositoryUrlProblem(fields.repositoryUrl))
    ?? refProblem(fields.ref);
  if (problem) return { problem };
  const includeGlobs = splitGlobs(fields.includeGlobs);
  const excludeGlobs = splitGlobs(fields.excludeGlobs);
  const globProblem = globsProblem(includeGlobs, "include") ?? globsProblem(excludeGlobs, "exclude");
  if (globProblem) return { problem: globProblem };
  const maxFiles = boundedInteger(fields.maxFiles, MAX_FILES);
  if (Number.isNaN(maxFiles)) {
    return { problem: `Max files is a whole number from ${MAX_FILES.min} to ${MAX_FILES.max}, or empty for the default.` };
  }
  const maxFileBytes = boundedInteger(fields.maxFileBytes, MAX_FILE_BYTES);
  if (Number.isNaN(maxFileBytes)) {
    return {
      problem: `Max file size is a whole number of bytes from ${MAX_FILE_BYTES.min} to ${MAX_FILE_BYTES.max} (2 MiB), `
        + "or empty for the default.",
    };
  }
  return {
    scope: {
      fetch_mode: "remote_git",
      repository_url: fields.repositoryUrl.trim(),
      ref: fields.ref.trim(),
      include_globs: includeGlobs.length ? includeGlobs : null,
      exclude_globs: excludeGlobs.length ? excludeGlobs : null,
      max_files: maxFiles,
      max_file_bytes: maxFileBytes,
      ...(connectionId ? { connection_id: connectionId } : {}),
    },
  };
}

export function gitFieldsFromScope(scope: ConnectorScope): GitRepositoryFields {
  return {
    repositoryUrl: scope.remote ?? "",
    ref: scope.ref ?? "",
    includeGlobs: (scope.include_globs ?? []).join("\n"),
    excludeGlobs: (scope.exclude_globs ?? []).join("\n"),
    maxFiles: typeof scope.max_files === "number" ? String(scope.max_files) : "",
    maxFileBytes: typeof scope.max_file_bytes === "number" ? String(scope.max_file_bytes) : "",
  };
}

export function bytesText(bytes: number): string {
  if (bytes >= 1024 * 1024 && bytes % (1024 * 1024) === 0) return `${bytes / (1024 * 1024)} MiB`;
  if (bytes >= 1024 && bytes % 1024 === 0) return `${bytes / 1024} KiB`;
  return `${bytes} bytes`;
}

export function isLocalSnapshot(connector: SourceConnector): boolean {
  return connector.kind === "git_repository" && connector.scope.fetch_mode === "local_snapshot";
}

export function headText(scope: ConnectorScope): string {
  if (!scope.head_commit) return "not synced yet";
  return `synced at ${scope.head_commit.slice(0, SHORT_SHA)}${scope.head_dirty ? " (dirty)" : ""}`;
}

export function gitScopeSummary(scope: ConnectorScope): {
  repository: string;
  ref: string;
  include: string;
  exclude: string;
  limits: string;
  head: string;
} {
  const remote = scope.remote ?? "";
  const match = REMOTE_REPOSITORY.exec(remote);
  const repository = match ? `${match[1]}/${match[2]}` : remote;
  const limits = [
    typeof scope.max_files === "number" ? `at most ${scope.max_files} files` : "",
    typeof scope.max_file_bytes === "number" ? `${bytesText(scope.max_file_bytes)} per file` : "",
  ].filter(Boolean).join(", ");
  return {
    repository,
    ref: scope.ref ?? "",
    include: (scope.include_globs ?? []).join(", "),
    exclude: (scope.exclude_globs ?? []).join(", "),
    limits,
    head: headText(scope),
  };
}
