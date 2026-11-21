import type { ToolArtifact } from "../chatThreadTypes";
import type { WorkspaceFileEntry } from "../chatWorkspaceTypes";
import { formatChatTime } from "./chatTimestamp";

export function humanSize(sizeBytes?: number | null) {
  if (!sizeBytes || sizeBytes <= 0) {
    return "";
  }
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }
  const units = ["KB", "MB", "GB"];
  let value = sizeBytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatTime(value?: string | null) {
  return formatChatTime(value, value || "");
}

export function asArtifact(file: WorkspaceFileEntry): ToolArtifact {
  return {
    name: file.name,
    path: file.path,
    mediaType: file.mediaType,
    sizeBytes: file.sizeBytes,
    url: file.url || "",
  };
}

export function relativeParent(path: string) {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 1) {
    return "";
  }
  return parts.slice(0, -1).join("/");
}

export function workspaceFileTypeLabel(name: string) {
  const trimmed = String(name || "").trim();
  const extension = trimmed.includes(".") ? trimmed.split(".").pop() || "" : "";
  const normalized = extension.replace(/[^a-z0-9]/gi, "").toUpperCase();
  return normalized || "FILE";
}
