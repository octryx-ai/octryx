import type { ToolArtifact } from "../chatThreadTypes";
import type { ArtifactPreviewKind } from "./artifactPreviewKind";
import { OfficeWorkspace } from "./artifactPreviewOfficeWorkspace";
import { TextWorkspace, HtmlWorkspace } from "./artifactPreviewTextWorkspaces";

export function ArtifactPreviewBody({
  artifact,
  kind,
}: {
  artifact: ToolArtifact;
  kind: ArtifactPreviewKind;
}) {
  if (kind === "image") {
    return (
      <img
        className="artifact-preview__image"
        src={artifact.url}
        alt={artifact.name}
      />
    );
  }
  if (kind === "pdf") {
    return (
      <iframe
        className="artifact-preview__frame"
        src={artifact.url}
        title={artifact.name}
      />
    );
  }
  if (kind === "office") {
    return (
      <OfficeWorkspace artifact={artifact} />
    );
  }
  if (kind === "html") {
    return <HtmlWorkspace artifact={artifact} />;
  }
  if (kind === "text") {
    return <TextWorkspace artifact={artifact} />;
  }
  return (
    <div className="artifact-preview__empty">
      <div className="artifact-preview__empty-title">
        No inline preview available
      </div>
      <div className="artifact-preview__empty-copy">
        Open this artifact in a new tab or download it locally for external
        inspection.
      </div>
    </div>
  );
}
