export const ADD_SOURCE_KEY = "new";

export function addSourceHref(workspaceId: string): string {
  return `/chat?area=knowledge&tab=workspaceKnowledge&workspace_id=${encodeURIComponent(workspaceId)}&source=${ADD_SOURCE_KEY}`;
}

export function addRepositoryFromConnectionHref(
  workspaceId: string,
  connectionId = "",
): string {
  const base = workspaceId
    ? addSourceHref(workspaceId)
    : `/chat?area=knowledge&tab=workspaceKnowledge&source=${ADD_SOURCE_KEY}`;
  return `${base}&kind=git_repository&from=connection${connectionId ? `&connection=${encodeURIComponent(connectionId)}` : ""}`;
}

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

export function sourceAclHref(workspaceId: string): string {
  return `/chat?area=knowledge&tab=workspaceKnowledge&workspace_id=${encodeURIComponent(workspaceId)}&source_acl=open`;
}

export function requestedSourceAcl(search: string): boolean {
  return new URLSearchParams(search).get("source_acl") === "open";
}
