import { formatBytes } from "./composerShellHelpers";
import type { ToolArtifact } from "../chatThreadTypes";

function artifactExtension(name: string) {
  const normalized = String(name || "").trim();
  if (!normalized.includes(".")) {
    return "";
  }
  return normalized.split(".").at(-1)?.toLowerCase() || "";
}

function artifactKindLabel(artifact: ToolArtifact) {
  const extension = artifactExtension(artifact.name);
  if (extension) {
    return extension.slice(0, 6).toUpperCase();
  }
  const mediaType = String(artifact.mediaType || "").trim();
  return mediaType.split("/").at(-1)?.slice(0, 6).toUpperCase() || "FILE";
}

function artifactSummaryTypeLabel(artifact: ToolArtifact) {
  const extension = artifactExtension(artifact.name);
  const mediaType = String(artifact.mediaType || "")
    .trim()
    .toLowerCase();

  const extensionLabels: Record<string, string> = {
    csv: "Spreadsheet",
    doc: "Word document",
    docx: "Word document",
    html: "HTML page",
    jpg: "Image",
    jpeg: "Image",
    json: "JSON data",
    md: "Markdown document",
    pdf: "PDF document",
    png: "Image",
    ppt: "Presentation",
    pptx: "Presentation",
    svg: "Image",
    txt: "Text document",
    xls: "Spreadsheet",
    xlsx: "Spreadsheet",
    xml: "XML document",
    yaml: "YAML document",
    yml: "YAML document",
  };
  if (extension && extensionLabels[extension]) {
    return extensionLabels[extension];
  }

  if (mediaType.startsWith("image/")) {
    return "Image";
  }
  if (mediaType === "text/plain") {
    return "Text document";
  }
  if (mediaType === "text/html") {
    return "HTML page";
  }
  if (mediaType === "application/pdf") {
    return "PDF document";
  }
  if (mediaType === "application/json") {
    return "JSON data";
  }
  if (mediaType.includes("wordprocessingml") || mediaType.includes("msword")) {
    return "Word document";
  }
  if (mediaType.includes("spreadsheetml") || mediaType.includes("excel")) {
    return "Spreadsheet";
  }
  if (
    mediaType.includes("presentationml") ||
    mediaType.includes("powerpoint")
  ) {
    return "Presentation";
  }

  return mediaType || "Generated file";
}

function artifactDirectory(path: string) {
  const normalized = String(path || "").trim();
  if (!normalized) {
    return "";
  }
  const segments = normalized.split(/[\\/]/).filter(Boolean);
  if (segments.length <= 1) {
    return normalized;
  }
  return segments.slice(0, -1).join("/");
}

export function ToolArtifacts({
  artifacts,
  onPreviewArtifact,
}: {
  artifacts: ToolArtifact[];
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
}) {
  if (!artifacts.length) {
    return null;
  }

  return (
    <div className="tool-artifacts">
      {artifacts.map((artifact) => {
        const isImage = artifact.mediaType.startsWith("image/");
        const sizeLabel =
          typeof artifact.sizeBytes === "number"
            ? formatBytes(artifact.sizeBytes)
            : null;
        const mediaTypeLabel = artifact.mediaType || "Unknown type";
        const summaryTypeLabel = artifactSummaryTypeLabel(artifact);
        const directoryLabel = artifactDirectory(artifact.path);
        return (
          <article
            key={artifact.url}
            className={`tool-artifact ${isImage ? "tool-artifact--image" : "tool-artifact--file"}`}
          >
            <div className="tool-artifact__leading">
              {isImage ? (
                <img
                  className="tool-artifact__thumb"
                  src={artifact.url}
                  alt={artifact.name}
                  loading="lazy"
                />
              ) : (
                <div className="tool-artifact__badge" aria-hidden="true">
                  {artifactKindLabel(artifact)}
                </div>
              )}
            </div>
            <div className="tool-artifact__body">
              <div className="tool-artifact__identity">
                <div className="tool-artifact__title-row">
                  <span className="tool-artifact__name">{artifact.name}</span>
                  <span className="tool-artifact__kind">
                    {artifactKindLabel(artifact)}
                  </span>
                </div>
                <div className="tool-artifact__meta-row tool-artifact__meta-row--compact">
                  <span className="tool-artifact__type" title={mediaTypeLabel}>
                    {summaryTypeLabel}
                  </span>
                  {sizeLabel ? (
                    <span className="tool-artifact__size">{sizeLabel}</span>
                  ) : null}
                </div>
              </div>
              {directoryLabel ? (
                <div className="tool-artifact__path-row">
                  <span className="tool-artifact__path" title={artifact.path}>
                    {directoryLabel}
                  </span>
                </div>
              ) : null}
            </div>
            <div className="tool-artifact__actions">
              {onPreviewArtifact ? (
                <button
                  type="button"
                  className="tool-artifact__action"
                  onClick={() => onPreviewArtifact(artifact)}
                >
                  Preview
                </button>
              ) : null}
              <a
                className="tool-artifact__action"
                href={artifact.url}
                target="_blank"
                rel="noreferrer"
              >
                Open
              </a>
              <a
                className="tool-artifact__action"
                href={`/chat/api/artifact?${new URLSearchParams({ path: artifact.path, download: "true" }).toString()}`}
                download={artifact.name}
              >
                Download
              </a>
            </div>
            {isImage ? (
              <div className="tool-artifact__inline-preview">
                <img
                  className="tool-artifact__inline-thumb"
                  src={artifact.url}
                  alt={artifact.name}
                  loading="lazy"
                />
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}
