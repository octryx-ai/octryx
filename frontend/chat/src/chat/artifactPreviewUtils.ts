import type { ToolArtifact } from "../chatThreadTypes";

export type OfficeInspectMode =
  | "html"
  | "stats"
  | "text"
  | "issues"
  | "outline"
  | "annotated"
  | "forms";
export type OfficeInspectPayload = {
  file_name: string;
  file_path: string;
  file_type: string;
  media_type: string;
  size_bytes: number;
  mode: Exclude<OfficeInspectMode, "html">;
  summary?: Record<string, unknown> | null;
  content?: Record<string, unknown> | null;
  stats?: Record<string, unknown> | null;
};
export type OfficeAction = {
  id: string;
  label: string;
  description: string;
};
export type OfficeActionMode = "prompt" | "tool_plan";
export type OfficeActionsPayload = {
  file_type: string;
  allowed_modes: string[];
  available_views: string[];
  actions: OfficeAction[];
};
export type OfficeResolvedActionPayload = {
  file_type: string;
  action_id: string;
  label: string;
  description: string;
  mode: OfficeActionMode;
  text: string;
};

export function officePreviewUrl(artifact: ToolArtifact) {
  const params = new URLSearchParams({ path: artifact.path });
  return `/chat/api/artifact-preview?${params.toString()}`;
}

// The exact layout, rendered by LibreOffice on the platform; an explanatory page when it cannot render.
export function officeRenderedPdfUrl(artifact: ToolArtifact) {
  const params = new URLSearchParams({ path: artifact.path, format: "pdf" });
  return `/chat/api/artifact-preview?${params.toString()}`;
}

export function artifactOpenUrl(artifact: ToolArtifact) {
  const params = new URLSearchParams({ path: artifact.path });
  return `/chat/api/artifact?${params.toString()}`;
}

export function inspectOfficeUrl(
  artifact: ToolArtifact,
  mode: Exclude<OfficeInspectMode, "html">,
) {
  const params = new URLSearchParams({ path: artifact.path, mode });
  return `/chat/api/artifact-inspect?${params.toString()}`;
}

export function officeActionsUrl(artifact: ToolArtifact) {
  const params = new URLSearchParams({ path: artifact.path });
  return `/chat/api/artifact-actions?${params.toString()}`;
}

export function artifactDownloadUrl(artifact: ToolArtifact) {
  const params = new URLSearchParams({ path: artifact.path, download: "true" });
  return `/chat/api/artifact?${params.toString()}`;
}

export async function resolveOfficeAction(
  artifact: ToolArtifact,
  actionId: string,
  mode: OfficeActionMode,
): Promise<OfficeResolvedActionPayload> {
  const response = await fetch("/chat/api/artifact-actions/resolve", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path: artifact.path,
      action_id: actionId,
      mode,
    }),
  });
  if (!response.ok) {
    throw new Error(`Action resolve failed (${response.status})`);
  }
  return (await response.json()) as OfficeResolvedActionPayload;
}

export function humanFileSize(sizeBytes?: number | null) {
  if (!sizeBytes || sizeBytes <= 0) {
    return "Unknown size";
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

export function formatOfficeValue(value: unknown) {
  if (value == null) {
    return "n/a";
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  return JSON.stringify(value);
}

export function titleFromKey(key: string) {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function officeTypeHint(fileType: string) {
  if (fileType === "xlsx") {
    return "Spreadsheet artifact. Prefer stats, text and forms when checking sheet structure or editable fields.";
  }
  if (fileType === "pptx") {
    return "Presentation artifact. Outline and annotated views are best for slide structure and rendered content checks.";
  }
  return "Document artifact. Text, issues and forms give the fastest operational read on the file.";
}
