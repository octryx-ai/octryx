// Files and pending changes of the selected chat workspace.

export type WorkspaceFileEntry = {
  path: string;
  relativePath: string;
  parentPath?: string;
  name: string;
  kind?: "file" | "directory";
  depth?: number;
  childCount?: number | null;
  mediaType: string;
  sizeBytes?: number | null;
  url?: string;
  toolName?: string | null;
  createdAt?: string | null;
  modifiedAt?: string | null;
};

export type WorkspaceChangeEntry = {
  id: string;
  approvalId: string;
  toolName?: string | null;
  requestFingerprint?: string | null;
  summary: string;
  status: string;
  createdAt?: string | null;
  preview?: Record<string, unknown> | null;
};

export type SelectedWorkspace = {
  rootLabel: string;
  rootPath?: string;
  isTemporary: boolean;
  files: WorkspaceFileEntry[];
  loadedDirectories?: string[];
  changes: WorkspaceChangeEntry[];
};
