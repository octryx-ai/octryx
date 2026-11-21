// One-shot hand-over from the Search entry to Knowledge → Documents: "Upload document" asks the
// Documents page to open its upload drawer once, for the workspace the request was made in.
// Nothing is persisted; a request that is not taken by the next Documents mount is discarded.

let pendingUpload: string | null = null;

export function requestDocumentUpload(workspaceId: string): void {
  pendingUpload = workspaceId || null;
}

export function takeDocumentUploadRequest(workspaceId: string): boolean {
  const requested = Boolean(workspaceId) && pendingUpload === workspaceId;
  pendingUpload = null;
  return requested;
}
