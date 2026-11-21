import { useRef, useState, type RefObject } from "react";

import { EMBED_URL } from "./diagramViewerEditor";
import { useDiagramActions, useDiagramXml, useDrawioBridge } from "./diagramViewerHooks";

interface DiagramViewerProps {
  xml?: string;
  title?: string;
  diagramId?: string;
  // When the inline result only carries a truncated XML (large diagrams are
  // externalized), fetch the full draw.io XML from this URL and render that.
  fetchUrl?: string;
  // "image" (default): show the server-rendered PNG first, embed on demand.
  // "embed": mount the interactive draw.io embed immediately (preview page).
  initialView?: "image" | "embed";
}

type ViewMode = "image" | "embed";

function DiagramHeading({ title, diagramId }: { title?: string; diagramId?: string }) {
  return (
    <div className="diagram-viewer__heading">
      <span className="diagram-viewer__eyebrow">Diagram preview</span>
      <span className="diagram-viewer__title">
        <svg
          viewBox="0 0 20 20"
          className="diagram-viewer__icon"
          aria-hidden="true"
        >
          <rect x="2" y="5" width="5" height="4" rx="1" />
          <rect x="13" y="5" width="5" height="4" rx="1" />
          <rect x="7.5" y="12" width="5" height="4" rx="1" />
          <line x1="4.5" y1="9" x2="4.5" y2="14" />
          <line x1="15.5" y1="9" x2="15.5" y2="14" />
          <line x1="4.5" y1="14" x2="10" y2="14" />
          <line x1="15.5" y1="14" x2="10" y2="14" />
        </svg>
        <span className="diagram-viewer__title-copy">
          {title ?? "Diagram"}
        </span>
      </span>
      {diagramId ? (
        <span className="diagram-viewer__meta">ID {diagramId}</span>
      ) : null}
    </div>
  );
}

type HeaderProps = {
  title?: string;
  diagramId?: string;
  showXml: boolean;
  onToggleXml: () => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  onOpenFullEditor: () => void;
};

function DiagramViewerHeader({ title, diagramId, showXml, onToggleXml, viewMode, setViewMode, onOpenFullEditor }: HeaderProps) {
  return (
    <div className="diagram-viewer__header">
      <DiagramHeading title={title} diagramId={diagramId} />
      <div className="diagram-viewer__actions">
        <button
          type="button"
          className="diagram-viewer__btn"
          onClick={onToggleXml}
          title="Toggle XML source"
        >
          {showXml ? "Hide XML" : "XML"}
        </button>
        {viewMode === "image" ? (
          <button
            type="button"
            className="diagram-viewer__btn"
            onClick={() => setViewMode("embed")}
            title="Open the interactive draw.io editor inline"
          >
            Edit inline
          </button>
        ) : null}
        <button
          type="button"
          className="diagram-viewer__btn diagram-viewer__btn--primary"
          onClick={onOpenFullEditor}
          title="Open in full draw.io editor (new tab)"
        >
          Open in Editor ↗
        </button>
      </div>
    </div>
  );
}

function DiagramImage({
  imageUrl,
  title,
  imageLoaded,
  setImageLoaded,
  setViewMode,
}: {
  imageUrl: string;
  title?: string;
  imageLoaded: boolean;
  setImageLoaded: (loaded: boolean) => void;
  setViewMode: (mode: ViewMode) => void;
}) {
  return (
    <div className="diagram-viewer__image-wrapper">
      {!imageLoaded && (
        <div className="diagram-viewer__loading" aria-live="polite">
          Loading diagram…
        </div>
      )}
      <img
        src={imageUrl}
        alt={title ?? "Diagram"}
        className="diagram-viewer__image"
        loading="lazy"
        onLoad={() => setImageLoaded(true)}
        onClick={() => setViewMode("embed")}
        onError={() => {
          // Renderer unavailable or render failure: explicit fallback to
          // the interactive embed (the pre-image behavior).
          setViewMode("embed");
        }}
        title="Click to open the interactive editor"
      />
    </div>
  );
}

function DiagramFrame({
  iframeRef,
  title,
  loading,
}: {
  iframeRef: RefObject<HTMLIFrameElement>;
  title?: string;
  loading: boolean;
}) {
  return (
    <div className="diagram-viewer__frame-wrapper">
      {loading && (
        <div className="diagram-viewer__loading" aria-live="polite">
          Loading diagram…
        </div>
      )}
      <iframe
        ref={iframeRef}
        src={EMBED_URL}
        className="diagram-viewer__frame"
        title={title ?? "Diagram"}
        loading="lazy"
      />
    </div>
  );
}

// Preview strategy: diagrams with a known id first show the server-rendered
// PNG (pixel-accurate drawio CLI export, cached backend-side). The
// interactive draw.io embed only mounts when the user asks for it. When the
// image endpoint fails (e.g. 503 renderer_unavailable), we fall back to the
// embed — exactly the pre-image behavior.
function diagramImageUrl(diagramId: string | undefined): string | null {
  return diagramId
    ? `/chat/api/artifact-image?path=${encodeURIComponent(`diagram://${diagramId}`)}&scale=2`
    : null;
}

function DiagramError({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="diagram-viewer__error">
      <strong>Diagram error:</strong> {error}
      <button
        type="button"
        className="diagram-viewer__btn"
        onClick={onRetry}
      >
        Retry
      </button>
    </div>
  );
}

export function DiagramViewer({
  xml,
  title,
  diagramId,
  fetchUrl,
  initialView = "image",
}: DiagramViewerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const initializedRef = useRef(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showXml, setShowXml] = useState(false);

  const imageUrl = diagramImageUrl(diagramId);
  const [viewMode, setViewMode] = useState<ViewMode>(
    imageUrl && initialView === "image" ? "image" : "embed",
  );
  const [imageLoaded, setImageLoaded] = useState(false);
  const { resolvedXml, fetching } = useDiagramXml(fetchUrl, xml);
  const xmlRef = useDrawioBridge({ iframeRef, initializedRef, resolvedXml, loaded, setLoaded, setError });
  const { handleOpenFullEditor, handleRetry } = useDiagramActions({ diagramId, xmlRef, iframeRef, initializedRef, setLoaded, setError });

  return (
    <div className="diagram-viewer">
      <DiagramViewerHeader
        title={title}
        diagramId={diagramId}
        showXml={showXml}
        onToggleXml={() => setShowXml((v) => !v)}
        viewMode={viewMode}
        setViewMode={setViewMode}
        onOpenFullEditor={handleOpenFullEditor}
      />

      <div className="diagram-viewer__body">
        {error ? (
          <DiagramError error={error} onRetry={handleRetry} />
        ) : viewMode === "image" && imageUrl ? (
          <DiagramImage imageUrl={imageUrl} title={title} imageLoaded={imageLoaded}
            setImageLoaded={setImageLoaded} setViewMode={setViewMode} />
        ) : (
          <DiagramFrame iframeRef={iframeRef} title={title} loading={!loaded || fetching} />
        )}

        {showXml && (
          <details className="diagram-viewer__xml-details" open>
            <summary className="diagram-viewer__xml-summary">
              draw.io XML source
            </summary>
            <pre className="diagram-viewer__xml-pre">{resolvedXml}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
