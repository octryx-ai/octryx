import { configOf } from "./connectorConfig";
import { connectorsApi } from "./connectorsApi";
import { reasonText } from "./connectorReasons";
import type { ConnectorRequestError } from "./connectorReasons";
import type { AccessMode, ConnectionRepositoryConfig, SourceConnector, SyncRun } from "./connectorTypes";
import type { ConnectionRepository, ConnectionWorkspace } from "./connectionRepositoriesApi";
import { runResultText } from "./connectorFreshness";

const MAX_KEY_CHARS = 40;
export const CONNECTOR_KEY = /^[a-z0-9][a-z0-9-]{0,39}$/;
const MAX_SUFFIX = 999;

const trimDashes = (value: string) => value.replace(/^-+|-+$/g, "");

export function repositoryConnectorKey(projectKey: string, slug: string): string {
  const key = trimDashes(`bitbucket-${projectKey}-${slug}`.toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/-{2,}/g, "-"));
  return trimDashes(key.slice(0, MAX_KEY_CHARS)) || "bitbucket";
}

export function suffixedKey(base: string, n: number): string {
  const suffix = `-${n}`;
  return `${trimDashes(base.slice(0, MAX_KEY_CHARS - suffix.length))}${suffix}`;
}

type ListedConnector = Pick<SourceConnector, "connector_key" | "kind" | "scope">;

/** Whether a listed connector already reads this repository from its remote (a launcher snapshot does not count). */
function readsRepository(connector: ListedConnector, repositoryUrl: string): boolean {
  return connector.kind === "git_repository" && connector.scope?.fetch_mode !== "local_snapshot"
    && connector.scope?.remote === repositoryUrl;
}

/** An existing source of the same repository keeps its own key; otherwise the first free "-2", "-3", … suffix. */
export function collisionSafeKey(base: string, repositoryUrl: string, existing: ListedConnector[]):
  { key: string; existing: ListedConnector | null } {
  const same = existing.find((connector) => readsRepository(connector, repositoryUrl));
  if (same) return { key: same.connector_key, existing: same };
  const taken = new Set(existing.map((connector) => connector.connector_key));
  for (let n = 1; n <= MAX_SUFFIX; n += 1) {
    const key = n === 1 ? base : suffixedKey(base, n);
    if (!taken.has(key)) return { key, existing: null };
  }
  throw new Error(`No free source name for ${base}.`);
}

/** A blank Git token is not sent, so a stored one is kept; an existing source sends its stored settings back. */
export function repositoryConnectorConfig(
  { repositoryUrl, ref, connectionId, accessMode, gitToken }:
    { repositoryUrl: string; ref: string; connectionId: string; accessMode: AccessMode; gitToken?: string },
  existing: ListedConnector | null = null,
): ConnectionRepositoryConfig {
  const stored = existing && "products" in existing ? configOf(existing as SourceConnector) : {};
  const token = gitToken?.trim() ?? "";
  return {
    ...stored,
    kind: "git_repository",
    fetch_mode: "remote_git",
    repository_url: repositoryUrl,
    ref,
    connection_id: connectionId,
    access_mode: accessMode,
    ...(token ? { git_token: token } : {}),
  };
}

export function orderedWorkspaces(workspaces: ConnectionWorkspace[]): ConnectionWorkspace[] {
  return [...workspaces].sort((a, b) => Number(b.current) - Number(a.current) || a.name.localeCompare(b.name));
}

export function defaultWorkspaceSelection(workspaces: ConnectionWorkspace[], currentId: string): string[] {
  const current = workspaces.find((workspace) => workspace.current) ?? workspaces.find((workspace) => workspace.id === currentId);
  return current ? [current.id] : [currentId];
}

export type PagerState = { start: number; previous: number[] };

export const FIRST_PAGE: PagerState = { start: 0, previous: [] };

export function nextPage(pager: PagerState, nextStart: number | null): PagerState {
  return nextStart === null ? pager : { start: nextStart, previous: [...pager.previous, pager.start] };
}

export function previousPage(pager: PagerState): PagerState {
  if (!pager.previous.length) return pager;
  return { start: pager.previous[pager.previous.length - 1], previous: pager.previous.slice(0, -1) };
}

export type RunOutcome = "not_started" | "running" | "started" | "failed";

export type WorkspaceSaveResult = {
  workspaceId: string;
  workspaceName: string;
  state: "saved" | "refused" | "failed";
  connectorKey: string | null;
  updated: boolean;
  problem: string | null;
  reason: string | null;
  run: RunOutcome;
  runText: string | null;
};

export type SaveApi = {
  list: (workspaceId: string) => Promise<{ connectors: SourceConnector[] }>;
  configure: (workspaceId: string, connectorKey: string, config: ConnectionRepositoryConfig) => Promise<unknown>;
  run: (workspaceId: string, connectorKey: string) => Promise<SyncRun>;
};

const DEFAULT_API: SaveApi = { list: connectorsApi.list, configure: connectorsApi.configure, run: connectorsApi.run };

export function refusalReason(error: unknown): string | null {
  const reason = error && typeof error === "object" ? (error as Partial<ConnectorRequestError>).reason : null;
  return typeof reason === "string" && reason ? reason : null;
}

function failure(error: unknown): { problem: string; reason: string | null; state: "refused" | "failed" } {
  const reason = refusalReason(error);
  const message = error instanceof Error ? error.message : String(error);
  return { problem: reason ? `Refused: ${reasonText(reason)}.` : message, reason, state: reason ? "refused" : "failed" };
}

function runOutcome(run: SyncRun): { run: RunOutcome; runText: string } {
  if (run.state === "failed" || run.state === "needs_configuration") {
    const reason = reasonText(run.reason);
    return { run: "failed", runText: reason ? `First sync: ${reason}.` : `First sync: ${runResultText(run, "git_repository")}` };
  }
  return { run: "started", runText: `First sync: ${runResultText(run, "git_repository")}` };
}

/** A refused save does not stop the others, and a run that does not start does not undo its save. */
export async function addRepositoryToWorkspaces(
  input: {
    workspaces: ConnectionWorkspace[];
    repository: Pick<ConnectionRepository, "project_key" | "slug" | "repository_url">;
    ref: string;
    connectionId: string;
    accessMode: AccessMode;
    // The repository's own Git token (Bitbucket Data Center), sent with every Workspace's PUT; blank: none.
    gitToken?: string;
  },
  { api = DEFAULT_API, onProgress }: { api?: SaveApi; onProgress?: (results: WorkspaceSaveResult[]) => void } = {},
): Promise<WorkspaceSaveResult[]> {
  const base = repositoryConnectorKey(input.repository.project_key, input.repository.slug);
  const results: WorkspaceSaveResult[] = [];
  const report = () => onProgress?.(results.map((result) => ({ ...result })));
  for (const workspace of input.workspaces) {
    const result: WorkspaceSaveResult = {
      workspaceId: workspace.id, workspaceName: workspace.name, state: "saved", connectorKey: null, updated: false,
      problem: null, reason: null, run: "not_started", runText: null,
    };
    results.push(result);
    try {
      const { connectors } = await api.list(workspace.id);
      const { key, existing } = collisionSafeKey(base, input.repository.repository_url, connectors);
      result.connectorKey = key;
      result.updated = existing !== null;
      await api.configure(workspace.id, key, repositoryConnectorConfig({
        repositoryUrl: input.repository.repository_url, ref: input.ref, connectionId: input.connectionId, accessMode: input.accessMode,
        gitToken: input.gitToken,
      }, existing));
    } catch (error) {
      Object.assign(result, failure(error));
    }
    report();
  }
  await Promise.all(results.filter((result) => result.state === "saved").map(async (result) => {
    result.run = "running";
    report();
    try {
      Object.assign(result, runOutcome(await api.run(result.workspaceId, result.connectorKey as string)));
    } catch (error) {
      result.run = "failed";
      result.runText = `First sync not started: ${failure(error).problem}`;
    }
    report();
  }));
  return results;
}

export function saveResultText(result: WorkspaceSaveResult): string {
  if (result.state !== "saved") return result.problem ?? "Not saved.";
  const saved = `${result.updated ? "Updated" : "Saved as"} ${result.connectorKey}.`;
  if (result.run === "running") return `${saved} First sync running…`;
  return [saved, result.runText].filter(Boolean).join(" ");
}
