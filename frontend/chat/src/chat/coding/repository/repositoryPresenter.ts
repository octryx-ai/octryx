import { reasonText } from "../../../admin/components/workspaceKnowledge/connectorReasons";
import type { RepositorySource } from "../../../admin/components/projectsTab/repositories/workspaceRepositoriesApi";

// Pure presentation rules for Work › Repositories. Kept out of the .tsx views so that the wording stays truthful and
// unit-testable.

/**
 * A repository's name as people say it: project/repository. A source path names the host's path
 * ("bitbucket/scm/SHOP/acme-orders-server", "scm/shop/acme-orders.git"); only its last two parts are shown.
 */
export function repositoryDisplayName(path: string): string {
  const parts = path.trim().replace(/\.git$/i, "").split("/").filter(Boolean);
  return parts.slice(-2).join("/") || path;
}

export type RepositoryStateTone = "neutral" | "info" | "problem";

export type RepositoryOverviewRow = {
  // "source": a Knowledge git source (with or without a record); "record": a Workspace repository record
  // (Admin › Workspace › Repositories) that no listed source names.
  kind: "source" | "record"; key: string; id: string; name: string; path: string;
  origin: string; originTitle: string;
  // What agents may do on it through its connection: "Read only", "Read and write" or "–".
  access: string; accessTitle: string;
  // The source's sync state in one or two words; the sentence behind it is the tooltip.
  status: string; statusTitle: string; tone: RepositoryStateTone;
  // Only a synced source without a record can be set up as a repository for runs.
  canSetUp: boolean;
  // From the Workspace's repository record (workspaceRepositoryRows): its default branch and coding setup summary.
  branch?: string | null;
  // The branch is read from the Knowledge source, not stored on the record.
  branchFromSource?: boolean;
  setup?: { text: string; missing: boolean } | null;
  // The repository record whose workflow runs the row's "Runs" panel lists; null for a source without a record.
  recordId?: string | null;
};

const CONNECTION_TYPES: Record<string, string> = {
  bitbucket: "Bitbucket", github: "GitHub", gitlab: "GitLab", azure_devops: "Azure DevOps",
};

export function connectionTypeLabel(type: string): string {
  const known = CONNECTION_TYPES[type];
  if (known) return known;
  const words = type.replaceAll("_", " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Connection";
}

/** Where a source comes from, in the words of Admin › Connections and Knowledge › Sources. */
export function sourceOrigin(source: RepositorySource | undefined): { label: string; title: string } {
  if (!source || !source.fetch_mode) return { label: "Knowledge source", title: "A Knowledge repository source." };
  if (source.fetch_mode === "local_snapshot") {
    return { label: "Snapshot", title: "A checkout a launcher uploaded as a local snapshot (Knowledge › Sources)." };
  }
  if (source.connection) {
    const type = connectionTypeLabel(source.connection.type);
    const name = source.connection.name.trim();
    return { label: name && name !== type ? `${type} · ${name}` : type,
      title: `Read through the ${type} connection "${name || type}" (Admin › Connections).` };
  }
  return { label: "Git", title: "A public Git repository, read without a connection." };
}

const ACCESS_LABELS: Record<string, string> = { read_only: "Read only", read_write: "Read and write" };

/** What agents may do on the repository through its connection (services/knowledge/sources/repository_access.py). */
export function sourceAccess(source: RepositorySource | undefined): { label: string; title: string } {
  const label = source?.access_mode ? ACCESS_LABELS[source.access_mode] : undefined;
  if (label) {
    return { label, title: source?.access_mode === "read_write"
      ? "Agents may create branches, push commits and open pull requests through the connection."
      : "Agents may read the repository but not write to it through the connection." };
  }
  if (source?.fetch_mode === "local_snapshot") return { label: "–", title: "An uploaded snapshot; agents do not reach the repository through it." };
  if (source?.fetch_mode && !source.connection) return { label: "–", title: "Not read through a connection; no access mode applies." };
  return { label: "–", title: "Access mode unknown." };
}

// A failed sync on Git access is said as such (such a source read "Waiting for sync").
const NO_GIT_ACCESS = new Set(["source_unauthorized", "git_token_invalid", "git_token_wrong_repository"]);
const SYNC_FAILED = new Set(["failed", "needs_configuration"]);
// A completed sync of a repository without any commit (an empty repository is no problem).
export const EMPTY_REPOSITORY_LABEL = "Empty repository — ready for a first commit";

/** A source's state from its synced commit and how its last sync ended. */
export function sourceStatus(source: RepositorySource): { label: string; title: string; tone: RepositoryStateTone } {
  const sync = source.last_sync;
  if (sync && SYNC_FAILED.has(sync.state)) {
    const reason = sync.reason || "";
    const kept = source.commit ? " The last synced commit stays available." : "";
    if (NO_GIT_ACCESS.has(reason)) {
      return { label: "Sync failed: no Git access", tone: "problem",
        title: `The last sync failed: ${reasonText(reason)}. Set a Git token on the repository (Knowledge › Sources) `
          + `or fix the connection's credential (Admin › Connections), then run the sync again.${kept}` };
    }
    return { label: "Sync failed", tone: "problem",
      title: `The last sync failed${reason ? `: ${reasonText(reason)}` : ""}. Check the source in Knowledge › Sources.${kept}` };
  }
  if (sync?.state === "running") {
    return { label: "Syncing", tone: "info", title: "A sync of this Knowledge source is running." };
  }
  if (sync?.state === "completed" && sync.reason === "repository_empty") {
    return { label: EMPTY_REPOSITORY_LABEL, tone: "neutral",
      title: "The repository exists but has no commits yet, so the sync found nothing to read. Push a first commit "
        + "and sync again." };
  }
  if (source.commit) {
    return { label: "Synced", tone: "neutral", title: "Synced and searchable in Knowledge." };
  }
  if (source.fetch_mode === "local_snapshot") {
    return { label: "Waiting for upload", tone: "neutral",
      title: "No snapshot has been uploaded yet; a launcher uploads the checkout." };
  }
  return { label: "Waiting for sync", tone: "neutral", title: sync
    ? "The last sync ended without a commit; the repository can be set up for runs after a sync with a commit."
    : "The Knowledge source has not synced a commit yet; the repository can be set up for runs after the first sync." };
}

/** One row per Knowledge git source: where it comes from, what agents may do on it and its sync state. */
export function sourceRows(sources: RepositorySource[]): RepositoryOverviewRow[] {
  return sources.map((source): RepositoryOverviewRow => {
    const origin = sourceOrigin(source);
    const access = sourceAccess(source);
    const state = sourceStatus(source);
    return {
      kind: "source", key: `source:${source.id}`, id: source.id, name: repositoryDisplayName(source.name), path: source.name,
      origin: origin.label, originTitle: origin.title, access: access.label, accessTitle: access.title,
      status: state.label, statusTitle: state.title, tone: state.tone, canSetUp: Boolean(source.commit),
    };
  });
}
