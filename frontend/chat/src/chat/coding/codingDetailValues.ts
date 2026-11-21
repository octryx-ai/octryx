import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import type { WorkCodingWorkspace } from "../work/workCodingPipelineTypes";
import { latestByVersion, recordValue } from "./codingSessionValues";

// Readers shared by the Coding session detail parts: links of repositories and branches, the pipeline run's
// workspace and context-budget records, and small value helpers.

export function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function repositoryLinkEntries(
  session: CodingSessionSummary,
  latestPlan: ReturnType<typeof latestByVersion>,
): Array<{ label: string; href?: string | null }> {
  const urls = repositoryUrlsByName(latestPlan);
  return session.repositories.map((repository) => ({
    label: repository,
    href: urls.get(repository) || null,
  }));
}

export function branchLinkEntries(
  session: CodingSessionSummary,
  detail: CodingSessionDetailData | null,
  latestPlan: ReturnType<typeof latestByVersion>,
): Array<{ label: string; href?: string | null }> {
  const urls = repositoryUrlsByName(latestPlan);
  const links = [
    ...(detail?.changeUnits || []).map((unit) => ({
      label: unit.branch_name,
      href: branchBrowseUrl(urls.get(unit.repository_name), unit.branch_name),
    })),
    ...arrayValue(latestPlan?.proposed_branches).map((entry) => {
      const branch = recordValue(entry);
      const repositoryName = stringValue(branch?.repository_name);
      const branchName = stringValue(branch?.branch_name || branch?.branch || branch?.name);
      return {
        label: branchName,
        href: branchBrowseUrl(urls.get(repositoryName), branchName),
      };
    }),
    ...session.branches.map((branch) => ({ label: branch, href: null })),
  ];
  const seen = new Set<string>();
  return links.filter((link) => {
    if (!link.label || seen.has(link.label)) return false;
    seen.add(link.label);
    return true;
  });
}

export function workspaceRecords(detail: CodingSessionDetailData | null): WorkCodingWorkspace[] {
  const run = detail?.pipelineTrace?.run;
  const summary = recordValue(run?.summary);
  const recoveryState = recordValue(run?.recovery_state);
  return [
    ...arrayValue(summary?.workspaces),
    ...arrayValue(recoveryState?.workspaces),
  ].filter(isWorkspaceRecord);
}

export function contextBudgetRecord(detail: CodingSessionDetailData | null): Record<string, unknown> | null {
  const run = detail?.pipelineTrace?.run;
  const summary = recordValue(run?.summary);
  return recordValue(summary?.context_budget);
}

export function isWorkspaceRecord(value: unknown): value is WorkCodingWorkspace {
  const workspace = recordValue(value);
  return Boolean(
    workspace &&
      typeof workspace.id === "string" &&
      typeof workspace.work_item_id === "string" &&
      typeof workspace.status === "string",
  );
}

export function repositoryUrlsByName(latestPlan: ReturnType<typeof latestByVersion>): Map<string, string> {
  const urls = new Map<string, string>();
  for (const entry of arrayValue(latestPlan?.affected_repositories)) {
    const repository = recordValue(entry);
    const name = stringValue(repository?.repository_name || repository?.name);
    const url = stringValue(repository?.repository_url || repository?.url);
    if (name && isHttpUrl(url)) {
      urls.set(name, url);
    }
  }
  return urls;
}

export function branchBrowseUrl(repositoryUrl?: string | null, branchName?: string | null): string | null {
  const branch = String(branchName || "").trim();
  const rawUrl = String(repositoryUrl || "").trim();
  if (!branch || !isHttpUrl(rawUrl)) return null;
  const browseUrl = rawUrl.includes("/browse") ? rawUrl : `${rawUrl.replace(/\/$/, "")}/browse`;
  const separator = browseUrl.includes("?") ? "&" : "?";
  return `${browseUrl}${separator}at=${encodeURIComponent(`refs/heads/${branch}`)}`;
}

export function compactUrlLabel(url: string): string {
  const value = url.trim();
  if (!isHttpUrl(value)) return value;
  const pullRequestMatch = value.match(/pull-requests\/([^/?#]+)/i);
  if (pullRequestMatch) return `PR ${pullRequestMatch[1]}`;
  const branchMatch = value.match(/[?&]at=([^&#]+)/i);
  if (branchMatch) return decodeURIComponent(branchMatch[1]).replace(/^refs\/heads\//, "");
  const parts = value.split("/").filter(Boolean);
  return parts.slice(-2).join("/") || value;
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

export function phaseLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export function sprintLabel(value: unknown): string {
  const sprint = recordValue(value);
  if (!sprint) return "-";
  const name = stringValue(sprint.name);
  const id = String(sprint.id || "").trim();
  if (name && id) return `${name} (${id})`;
  return name || id || "-";
}

export function arrayValue(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }
  if (value == null || value === "") {
    return [];
  }
  return [value];
}
