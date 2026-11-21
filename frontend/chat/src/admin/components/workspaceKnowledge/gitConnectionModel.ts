// "Read through connection" of a Git repository source (Add source › Git repository, its edit form, and Work ›
// Repositories › Add a repository, which opens the same form). The server names the candidates: the Workspace's
// usable GitHub, GitLab and Bitbucket connections that can read the URL
// (GET …/knowledge/connectors/_git-connection-candidates?repository_url=); an unlinked source lists them as
// `connection_candidates`. The choice is the source's top-level `connection_id` (gitRepositoryScope). Without one the
// server links the single candidate itself, refuses several (422 connection_choice_required) and reads anonymously
// when there is none; an explicit `connection_id` always wins.

export type GitConnectionCandidate = { id: string; name: string; type: string };

export const TYPE_LABEL: Record<string, string> = { github: "GitHub", gitlab: "GitLab", bitbucket: "Bitbucket" };
export const PRIVATE_HINT = "A private repository needs a connection with access.";
export const CANDIDATES_DEBOUNCE_MS = 400;

/** Whether a URL is worth asking the server about: https, a host and at least owner/repo. */
export function candidatesQueryable(raw: string): boolean {
  try {
    const url = new URL(raw.trim());
    return url.protocol === "https:" && Boolean(url.hostname) && url.pathname.split("/").filter(Boolean).length >= 2;
  } catch {
    return false;
  }
}

/** The connection preselected for the candidates: the one candidate, else none ("None (public repository)"). */
export function preselectConnection(candidates: GitConnectionCandidate[]): string {
  return candidates.length === 1 ? candidates[0].id : "";
}

/** The picker's options: the candidates, plus a stored connection the candidates do not list (an edited source). */
export function connectionOptions(candidates: GitConnectionCandidate[], storedId: string): GitConnectionCandidate[] {
  if (!storedId || candidates.some((candidate) => candidate.id === storedId)) return candidates;
  return [...candidates, { id: storedId, name: "This source's connection", type: "" }];
}

/** The option label: the connection's name, with its type when the name does not say it. */
export function connectionLabel(candidate: GitConnectionCandidate): string {
  const type = TYPE_LABEL[candidate.type] ?? candidate.type;
  return !type || candidate.name.toLowerCase().includes(type.toLowerCase()) ? candidate.name : `${candidate.name} (${type})`;
}

/** The hint under the picker for what will happen on save. */
export function connectionHint(candidates: GitConnectionCandidate[], connectionId: string): string {
  if (connectionId) return PRIVATE_HINT;
  if (candidates.length === 1) {
    return `${PRIVATE_HINT} With None, saving still links ${candidates[0].name}, the one connection that can read it.`;
  }
  if (candidates.length > 1) return `${PRIVATE_HINT} Several connections can read it: pick one, or None for a public repository.`;
  return `${PRIVATE_HINT} None of this Workspace's connections reads it, so it is read as a public repository.`;
}

// The refusals of a save that concern the chosen connection, in words (shown next to the picker).
const REFUSAL_TEXT: Record<string, string> = {
  connection_choice_required: "Not saved: several connections can read this repository. Pick one under Read through connection.",
  connection_not_available: "Not saved: this connection is not available in this Workspace. Pick another one, or None for a public repository.",
  source_connection_not_granted: "Not saved: this connection is not released to this Workspace. A platform admin releases it in Admin › Connections (open the connection, tick this Workspace under Workspaces).",
  repository_not_on_connection_host: "Not saved: the repository is not on this connection's host. Pick the connection for its host, or None for a public repository.",
  connection_disabled: "Not saved: this connection is disabled.",
  connection_use_disabled: "Not saved: using this connection for Knowledge is switched off.",
};

export function gitConnectionRefusalText(reason: string): string | null {
  return REFUSAL_TEXT[reason] ?? null;
}

/** The words for a URL the candidates lookup refused (400: no URL of a known Git host). */
export const URL_REFUSED_TEXT = "This is no repository address Octryx can read. Use https://github.com/<owner>/<repo>, "
  + "https://bitbucket.org/<workspace>/<repo> or the address the connection lists.";

/** Sources linked to no connection although connections could read them: a notice offers to choose one. */
export function unlinkedWithCandidates<T extends { kind: string; connection_id?: string | null; connection_candidates?: GitConnectionCandidate[] }>(
  connectors: T[],
): T[] {
  return connectors.filter((connector) => connector.kind === "git_repository" && !connector.connection_id
    && (connector.connection_candidates?.length ?? 0) > 0);
}
