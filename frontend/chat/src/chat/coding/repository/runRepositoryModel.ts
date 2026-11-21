// Work › Repositories › "Add a repository for runs" (alpha): a repository a workflow run can work in, added
// through one of the Workspace's GitHub, GitLab or Bitbucket connections. The backend writes the record
// (api/routes/workspace_repositories.py, services/secure_work/repositories/run_repository.py).

export type RunConnection = { id: string; name: string; connector: "github" | "gitlab" | "bitbucket"; bound_scopes: string[] };
export type RunApp = { path: string; environment_file: string };
export type Detection = { repository: string; base_branch: string; exists: boolean | null; apps: RunApp[];
  apps_found_at: "now" | "first_run" };
export type Right = "read" | "branch" | "write" | "pr";
export type Rights = Record<Right, boolean>;

// What a run may do in the repository: all on by default so the work runs; the team switches any off.
export const RIGHTS: { key: Right; label: string; hint: string }[] = [
  { key: "read", label: "Read", hint: "Clone and read the code." },
  { key: "branch", label: "Create branches", hint: "A run works on its own branch." },
  { key: "write", label: "Push commits", hint: "A run pushes its changes to that branch." },
  { key: "pr", label: "Open pull requests", hint: "A run proposes its change for review." },
];
export const DEFAULT_RIGHTS: Rights = { read: true, branch: true, write: true, pr: true };

const REPOSITORY = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}(\/[A-Za-z0-9._-]{1,100}){1,2}$/;

/** owner/name as typed (a pasted URL or a trailing .git is cut down), or a problem to show. */
export function repositoryName(raw: string): { name: string } | { problem: string } {
  let text = raw.trim();
  const url = /^https?:\/\/[^/]+\/(.+)$/.exec(text);
  if (url) text = url[1];
  text = text.replace(/^\/+|\/+$/g, "").replace(/\.git$/, "");
  if (!text) return { problem: "Enter the repository as owner/name, e.g. demo-org/demo-shop." };
  if (!REPOSITORY.test(text) || text.includes("..")) {
    return { problem: "The repository is owner/name, e.g. demo-org/demo-shop." };
  }
  return { name: text };
}

/** The line under "Check repository": what the check found. */
export function detectionText(found: Detection | null): string {
  if (!found) return "";
  if (found.exists === false) return `${found.repository} has no branch ${found.base_branch} the connection can read.`;
  if (found.apps_found_at === "first_run") {
    return "Found. Its apps (.octryx/environment.json) are listed when the first run prepares the repository.";
  }
  if (!found.apps.length) return "Found. No .octryx/environment.json: the test command below is used.";
  const apps = found.apps.map((app) => (app.path === "." ? "the repository root" : app.path)).join(", ");
  return `Found ${found.apps.length === 1 ? "1 app" : `${found.apps.length} apps`}: ${apps}.`;
}

export function connectionLabel(connection: RunConnection): string {
  const kind = { github: "GitHub", gitlab: "GitLab", bitbucket: "Bitbucket" }[connection.connector];
  return connection.name.toLowerCase().includes(kind.toLowerCase()) ? connection.name : `${connection.name} (${kind})`;
}

const base = (workspaceId: string) => `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/repositories`;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } | string } | null;
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message
      ?? (response.status === 403 ? "Only a Workspace owner or an admin adds repositories." : "The request failed. Try again."));
  }
  return response.json() as Promise<T>;
}

export async function loadRunConnections(workspaceId: string): Promise<RunConnection[]> {
  return (await request<{ items?: RunConnection[] }>(`${base(workspaceId)}/connections`)).items ?? [];
}

export type RunRepositoryDraft = { connection_id: string; repository: string; base_branch: string };

export function detectRunRepository(workspaceId: string, draft: RunRepositoryDraft): Promise<Detection> {
  return request(`${base(workspaceId)}/detect`, { method: "POST", body: JSON.stringify(draft) });
}

export function addRunRepository(workspaceId: string, draft: RunRepositoryDraft & {
  test_command: string; rights: Rights; apps: RunApp[];
}): Promise<{ id: string; name: string }> {
  return request(base(workspaceId), { method: "POST", body: JSON.stringify(draft) });
}
