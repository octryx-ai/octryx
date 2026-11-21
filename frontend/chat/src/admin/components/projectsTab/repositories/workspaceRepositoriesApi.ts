import { readJson } from "../../../utils/adminPanelHelpers";

// Settings → Workspace → Repositories: the Workspace's repository records, created from a
// Knowledge git source, and each record's coding setup.

export type RepositorySetupSummary = { configured: string[]; missing: string[] };

export type WorkspaceRepository = {
  id: string;
  name: string;
  provider: string;
  default_branch: string | null;
  // "knowledge_source" when the record has none and the branch is the one its Knowledge source follows.
  default_branch_from?: string | null;
  source: { kind: string; name: string };
  owners: string[];
  coding_setup: RepositorySetupSummary;
  last_index_status: string | null;
};

export type CodingSetup = Record<string, string | string[] | unknown[] | null>;
// A Knowledge git source a record can be created from: how it is read, through which connection (name and type,
// e.g. "bitbucket"), what agents may do on it (connection-linked only; null otherwise) and how its last sync ended.
export type AccessMode = "read_only" | "read_write";
export type SourceSync = { state: string; reason: string | null };
export type RepositorySource = {
  id: string; name: string; commit?: string | null;
  fetch_mode?: "remote_git" | "local_snapshot" | string;
  access_mode?: AccessMode | null;
  connection?: { name: string; type: string } | null;
  last_sync?: SourceSync | null;
};

const base = (workspaceId: string) => `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`;

export async function loadWorkspaceRepositories(workspaceId: string): Promise<WorkspaceRepository[]> {
  const payload = await readJson<{ items?: WorkspaceRepository[] }>(`${base(workspaceId)}/repositories`);
  return payload.items ?? [];
}

export async function loadRepositorySources(workspaceId: string): Promise<RepositorySource[]> {
  const payload = await readJson<{ items?: RepositorySource[] }>(`${base(workspaceId)}/repositories/sources`);
  return payload.items ?? [];
}

export function addRepositoryFromSource(workspaceId: string, connectorId: string): Promise<{ repository_id: string }> {
  return readJson(`${base(workspaceId)}/repositories/from-source`, {
    method: "POST", body: JSON.stringify({ connector_id: connectorId }) });
}

export async function loadCodingSetup(workspaceId: string, repositoryId: string): Promise<CodingSetup> {
  const payload = await readJson<{ coding_setup?: CodingSetup }>(`${base(workspaceId)}/repositories/${encodeURIComponent(repositoryId)}/coding-setup`);
  return payload.coding_setup ?? {};
}

export function saveCodingSetup(workspaceId: string, repositoryId: string, setup: CodingSetup): Promise<unknown> {
  return readJson(`${base(workspaceId)}/repositories/${encodeURIComponent(repositoryId)}/coding-setup`, {
    method: "PUT", body: JSON.stringify(setup) });
}

/** "build · test · lint", or what is missing. */
export function setupText(summary: RepositorySetupSummary): { text: string; missing: boolean } {
  if (!summary.missing.length) return { text: summary.configured.join(" · "), missing: false };
  if (!summary.configured.length) return { text: "not set up", missing: true };
  return { text: `${summary.missing.join(", ")} missing`, missing: true };
}

export function sourceText(source: WorkspaceRepository["source"]): string {
  return source.kind === "knowledge_source" ? `Knowledge source "${source.name}"` : source.name;
}
