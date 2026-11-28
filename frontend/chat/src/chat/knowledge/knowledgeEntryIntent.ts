// Nothing is persisted; a request not taken by the next Documents mount is discarded.

let pendingUpload: string | null = null;

export function requestDocumentUpload(workspaceId: string): void {
  pendingUpload = workspaceId || null;
}

export function takeDocumentUploadRequest(workspaceId: string): boolean {
  const requested = Boolean(workspaceId) && pendingUpload === workspaceId;
  pendingUpload = null;
  return requested;
}
