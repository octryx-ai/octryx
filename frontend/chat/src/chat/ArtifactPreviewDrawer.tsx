import type { ToolArtifact } from "../chatThreadTypes";
import { ArtifactPreviewHeader } from "./artifactPreviewHeader";
import { ArtifactPreviewBody } from "./artifactPreviewBody";
import { artifactExtension, classifyArtifact, previewCopy } from "./artifactPreviewKind";

export function ArtifactPreviewDrawer({
  artifact,
  onClose,
}: {
  artifact: ToolArtifact | null;
  onClose: () => void;
}) {
  if (!artifact) {
    return null;
  }

  const kind = classifyArtifact(artifact);
  const copy = previewCopy(kind);
  const extension = artifactExtension(artifact.name);

  return (
    <>
      <div className="artifact-preview__backdrop" onClick={onClose} />
      <aside className={`artifact-preview artifact-preview--${kind}`}>
        <ArtifactPreviewHeader
          artifact={artifact}
          kind={kind}
          extension={extension}
          copy={copy}
          onClose={onClose}
        />
        <div className="artifact-preview__body-shell">
          {kind === "office" ? (
            <ArtifactPreviewBody artifact={artifact} kind={kind} />
          ) : (
            <>
              <section className="artifact-preview__body">
                <ArtifactPreviewBody artifact={artifact} kind={kind} />
              </section>
              <aside className="artifact-preview__sidecar">
                <div className="artifact-preview__sidecard">
                  <div className="artifact-preview__sidecard-label">Viewer</div>
                  <div className="artifact-preview__sidecard-value">
                    {copy.title}
                  </div>
                </div>
                <div className="artifact-preview__sidecard">
                  <div className="artifact-preview__sidecard-label">
                    Output path
                  </div>
                  <div className="artifact-preview__sidecard-path">
                    {artifact.path}
                  </div>
                </div>
              </aside>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
