import { connectorRequest } from "./connectorsApi";
import type { AccessMode } from "./connectorTypes";
import { knowledgeBase } from "./workspaceKnowledgeRequest";
import type { GitConnectionCandidate } from "./gitConnectionModel";

// Typed client of the repository connections a Workspace's authors may add sources from
// (/knowledge/connections): the Bitbucket connections usable in the Workspace, a connection's repositories (paged
// and searchable), a repository's default branch, and the Workspaces the same connection may also be used in.
// Refusals are 409 {detail: {state: "refused", reason}}; connectorRequest turns them into a ConnectorRequestError.

export type RepositoryConnection = {
  id: string;
  name: string;
  type: string;
  deployment: "datacenter" | "cloud" | string;
  host: string;
};

export type ConnectionRepository = {
  project_key: string;
  slug: string;
  name: string;
  repository_url: string;
  web_url: string | null;
  // Already a source of this Workspace: its connector key and access mode.
  registered: { connector_key: string; access_mode: AccessMode | null } | null;
};

export type RepositoryPage = {
  repositories: ConnectionRepository[];
  start: number;
  limit: number;
  next_start: number | null;
  is_last_page: boolean;
};

export type ConnectionWorkspace = { id: string; name: string; current: boolean };

export const REPOSITORY_PAGE_SIZE = 25;

function connectionsBase(workspaceId: string): string {
  return `${knowledgeBase(workspaceId)}/connections`;
}

function connectionUrl(workspaceId: string, connectionId: string, suffix: string): string {
  return `${connectionsBase(workspaceId)}/${encodeURIComponent(connectionId)}${suffix}`;
}

export const connectionRepositoriesApi = {
  connections: (workspaceId: string) =>
    connectorRequest<{ connections: RepositoryConnection[] }>(connectionsBase(workspaceId)),
  // The connections that can read a repository URL, for "Read through connection"; 400 for an unknown host.
  gitCandidates: (workspaceId: string, repositoryUrl: string) =>
    connectorRequest<{ repository_url: string; candidates: GitConnectionCandidate[] }>(
      `${knowledgeBase(workspaceId)}/connectors/_git-connection-candidates?${new URLSearchParams({ repository_url: repositoryUrl.trim() })}`),
  repositories: (workspaceId: string, connectionId: string, page: { q?: string; start?: number; limit?: number } = {}) => {
    const params = new URLSearchParams({
      q: page.q?.trim() ?? "",
      start: String(page.start ?? 0),
      limit: String(page.limit ?? REPOSITORY_PAGE_SIZE),
    });
    return connectorRequest<RepositoryPage>(connectionUrl(workspaceId, connectionId, `/repositories?${params.toString()}`));
  },
  defaultBranch: (workspaceId: string, connectionId: string, projectKey: string, slug: string) =>
    connectorRequest<{ default_branch: string | null }>(connectionUrl(workspaceId, connectionId,
      `/repositories/${encodeURIComponent(projectKey)}/${encodeURIComponent(slug)}/default-branch`)),
  workspaces: (workspaceId: string, connectionId: string) =>
    connectorRequest<{ workspaces: ConnectionWorkspace[] }>(connectionUrl(workspaceId, connectionId, "/workspaces")),
};
