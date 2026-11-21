// Artifact preview kinds: file extension and media type checks, the kind classification and each kind's copy.
import type { ToolArtifact } from "../chatThreadTypes";

export type ArtifactPreviewKind =
  | "image"
  | "pdf"
  | "office"
  | "html"
  | "text"
  | "generic";

export function artifactExtension(name: string) {
  const parts = name.split(".");
  return parts.length > 1 ? `.${parts.at(-1)?.toLowerCase() || ""}` : "";
}

const OFFICE_PREVIEW_EXTENSIONS = new Set([
  ".doc",
  ".docx",
  ".xls",
  ".xlsx",
  ".ppt",
  ".pptx",
]);
const TEXT_PREVIEW_EXTENSIONS = new Set([
  ".txt",
  ".md",
  ".markdown",
  ".json",
  ".yml",
  ".yaml",
  ".xml",
  ".csv",
  ".tsv",
  ".log",
  ".py",
  ".js",
  ".ts",
  ".tsx",
  ".jsx",
  ".css",
  ".scss",
  ".sql",
  ".sh",
  ".toml",
  ".ini",
  ".cfg",
  ".conf",
  ".env",
]);

function artifactPreviewExtension(artifact: ToolArtifact) {
  return artifactExtension(artifact.name) || artifactExtension(artifact.path);
}

function isOfficePreviewable(artifact: ToolArtifact) {
  const extension = artifactPreviewExtension(artifact);
  const mediaType = String(artifact.mediaType || "").toLowerCase();
  return (
    OFFICE_PREVIEW_EXTENSIONS.has(extension) ||
    mediaType.includes("application/vnd.ms-") ||
    mediaType.includes("application/msword") ||
    mediaType.includes("application/vnd.openxmlformats-officedocument")
  );
}

function isHtmlPreviewable(artifact: ToolArtifact) {
  const extension = artifactPreviewExtension(artifact);
  const mediaType = String(artifact.mediaType || "").toLowerCase();
  return (
    mediaType.includes("text/html") ||
    extension === ".html" ||
    extension === ".htm"
  );
}

function isTextPreviewable(artifact: ToolArtifact) {
  const extension = artifactPreviewExtension(artifact);
  const mediaType = String(artifact.mediaType || "").toLowerCase();
  return (
    mediaType.startsWith("text/") ||
    mediaType === "application/json" ||
    mediaType === "application/xml" ||
    mediaType === "application/javascript" ||
    TEXT_PREVIEW_EXTENSIONS.has(extension)
  );
}

export function classifyArtifact(artifact: ToolArtifact): ArtifactPreviewKind {
  const lower =
    `${artifact.name} ${artifact.path} ${artifact.mediaType}`.toLowerCase();
  if (artifact.mediaType.startsWith("image/")) {
    return "image";
  }
  if (artifact.mediaType === "application/pdf" || lower.includes(".pdf")) {
    return "pdf";
  }
  if (isOfficePreviewable(artifact)) {
    return "office";
  }
  if (isHtmlPreviewable(artifact)) {
    return "html";
  }
  if (isTextPreviewable(artifact)) {
    return "text";
  }
  return "generic";
}

export function previewCopy(kind: ArtifactPreviewKind) {
  switch (kind) {
    case "image":
      return {
        eyebrow: "Image Preview",
        title: "Inline image viewer",
        description:
          "Use this for screenshots, generated charts, and image artifacts.",
      };
    case "pdf":
      return {
        eyebrow: "PDF Preview",
        title: "Embedded document viewer",
        description: "Best for exported reports, specs, and attached PDFs.",
      };
    case "office":
      return {
        eyebrow: "Office Preview",
        title: "Structural preview",
        description:
          "Word, Excel, and PowerPoint files are previewed from their structure. Open PDF shows the exact layout where the platform can render it.",
      };
    case "html":
      return {
        eyebrow: "HTML Preview",
        title: "Embedded web artifact",
        description:
          "Use this for generated reports and static HTML snapshots.",
      };
    case "text":
      return {
        eyebrow: "Text Preview",
        title: "Inline text viewer",
        description:
          "Use this for parsed text, logs, code, CSV and other text-based outputs.",
      };
    default:
      return {
        eyebrow: "Output Preview",
        title: "No inline renderer",
        description:
          "This artifact does not have a dedicated inline renderer yet.",
      };
  }
}
