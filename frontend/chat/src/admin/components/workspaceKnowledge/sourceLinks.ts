// Links into Knowledge › Sources (page id `workspaceKnowledge`). `?source=<key>` opens that source; the reserved key
// `new` opens "Add source" (e.g. from the Repository explorer, whose repositories come from a Git source).
export const ADD_SOURCE_KEY = "new";

/** Knowledge › Sources of a Workspace with "Add source" open. */
export function addSourceHref(workspaceId: string): string {
  return `/chat?area=knowledge&tab=workspaceKnowledge&workspace_id=${encodeURIComponent(workspaceId)}&source=${ADD_SOURCE_KEY}`;
}

/** "Add source" opened on a git repository "From a connection" (Bitbucket, GitHub, ...), optionally that connection.
 * Without a Workspace the Knowledge page uses the Workspace the person has open. */
export function addRepositoryFromConnectionHref(
  workspaceId: string,
  connectionId = "",
): string {
  const base = workspaceId
    ? addSourceHref(workspaceId)
    : `/chat?area=knowledge&tab=workspaceKnowledge&source=${ADD_SOURCE_KEY}`;
  return `${base}&kind=git_repository&from=connection${connectionId ? `&connection=${encodeURIComponent(connectionId)}` : ""}`;
}

/** What an "Add source" link asked for: the kind, "From a connection", and which connection. */
export function requestedAddSource(search: string): {
  kind: string;
  fromConnection: boolean;
  connectionId: string;
} {
  const params = new URLSearchParams(search);
  return {
    kind: params.get("kind") ?? "",
    fromConnection: params.get("from") === "connection",
    connectionId: params.get("connection") ?? "",
  };
}

/** Knowledge › Sources of a Workspace with the source-permissions panel open (platform admins). */
export function sourceAclHref(workspaceId: string): string {
  return `/chat?area=knowledge&tab=workspaceKnowledge&workspace_id=${encodeURIComponent(workspaceId)}&source_acl=open`;
}

/** Whether a link asked for the source-permissions panel. */
export function requestedSourceAcl(search: string): boolean {
  return new URLSearchParams(search).get("source_acl") === "open";
}
