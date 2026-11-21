// Connector scope texts: the hint under the scope fields and the scope refusal shown next to them.
import { reasonText } from "./connectorReasons";
import type { ConnectorKind } from "./connectorTypes";
import { gitConnectionRefusalText } from "./gitConnectionModel";
import { PAGE_TREE_REASON_TEXT } from "./confluencePageTree";
import { REST_KIND } from "./rest/restSourceForm";

export function scopeHint(kind: ConnectorKind): string {
  if (kind === "git_repository") {
    return "The connector reads one public github.com repository, or a bitbucket.org repository with the Workspace's "
      + "Bitbucket Cloud connection, at the ref: a branch or tag is resolved to a commit "
      + "at every run and the run report records it; a full commit sha pins the content. Only the files the include "
      + "globs select (all files without them) and the exclude globs do not drop are synced, within the file count "
      + "and per-file size limits; binary files are skipped.";
  }
  if (kind === "kubernetes") {
    return "The connector reads one cluster through the Kubernetes connection bound to it (or this Workspace's own "
      + "Kubernetes entry with an API URL and token), read-only: the namespaces (only the connection's allowed ones; "
      + "empty: all) with their deployments, replica counts and container images, one inventory per namespace. "
      + "The structured graph's operations layer builds clusters, namespaces, deployments and images from it.";
  }
  if (kind === REST_KIND) {
    return "The source reads one list operation of a REST API through its connection, as the role you pick: that role's "
      + "grant decides what is read, and by default the grants also decide who finds each item.";
  }
  if (kind === "servicenow") {
    return "The connector reads through this Workspace's own ServiceNow connection (URL and credential under Connectors, "
      + "active for this Workspace) and only tables in its allowed tables (kb_knowledge for articles). It syncs published, "
      + "active articles of the knowledge bases and the chosen records. A filter is an encoded query that can only narrow "
      + "that scope; the connector adds the order itself. Articles need the document parser sandbox.";
  }
  const jira = kind === "jira";
  return `The connector reads through this Workspace's own ${jira ? "Jira" : "Confluence"} connection (URL and credential `
    + `under Connectors, active for this Workspace) and only inside its allowed ${jira ? "projects" : "spaces"}.`
    + (jira ? " The filter narrows the projects, it never widens them." : "");
}

/** A refused save that belongs to the scope (page-tree shape 422, or a space outside the connection's allowlist,
 *  409 scope_not_allowed), shown next to the scope fields; null for any other failure. */
export function scopeRefusalText(error: unknown): string | null {
  const record = error && typeof error === "object" ? (error as { reason?: unknown; field?: unknown }) : null;
  const reason = typeof record?.reason === "string" ? record.reason : null;
  if (!reason) return null;
  if (reason === "scope_not_allowed") {
    return `Not saved: ${reasonText(reason)}. Every space, and the space of every page tree, must be one of the `
      + "connection's allowed spaces (Confluence connector settings).";
  }
  if (record?.field === "page_trees" || reason in PAGE_TREE_REASON_TEXT) return `Not saved: ${reasonText(reason)}.`;
  // The Connection of a Git repository source, shown next to its select.
  const connection = gitConnectionRefusalText(reason);
  if (connection) return connection;
  return null;
}
