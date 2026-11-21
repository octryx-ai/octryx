import type { ToolArtifact } from "../chatThreadTypes";
import { artifactOpenUrl, artifactDownloadUrl, humanFileSize } from "./artifactPreviewUtils";
import { type ArtifactPreviewKind } from "./artifactPreviewKind";

export function ArtifactPreviewHeader({
  artifact,
  kind,
  extension,
  copy,
  onClose,
}: {
  artifact: ToolArtifact;
  kind: ArtifactPreviewKind;
  extension: string;
  copy: {
    eyebrow: string;
    title: string;
    description: string;
  };
  onClose: () => void;
}) {
  return (
    <div className="artifact-preview__header">
      <div className="artifact-preview__identity">
        <div className="artifact-preview__eyebrow">{copy.eyebrow}</div>
        <h3>{artifact.name}</h3>
        {kind === "office" ? null : (
          <div className="artifact-preview__description">
            {copy.description}
          </div>
        )}
        <div className="artifact-preview__meta">
          <span className="artifact-preview__badge">{kind.toUpperCase()}</span>
          {extension ? (
            <span className="artifact-preview__badge artifact-preview__badge--secondary">
              {extension}
            </span>
          ) : null}
          <span>{artifact.mediaType || "Unknown media type"}</span>
          <span>{humanFileSize(artifact.sizeBytes)}</span>
        </div>
      </div>
      <div className="artifact-preview__actions">
        <a
          href={kind === "office" ? artifactOpenUrl(artifact) : artifact.url}
          target="_blank"
          rel="noreferrer"
          className="plain-button"
        >
          Open
        </a>
        <a
          href={artifactDownloadUrl(artifact)}
          download={artifact.name}
          className="plain-button"
        >
          Download
        </a>
        <button type="button" className="plain-button" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
