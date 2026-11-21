// Inline previews of text and generated HTML artifacts, each loaded on open.
import { useEffect, useMemo, useState } from "react";
import type { ToolArtifact } from "../chatThreadTypes";
import { artifactOpenUrl, officePreviewUrl } from "./artifactPreviewUtils";

export function TextWorkspace({ artifact }: { artifact: ToolArtifact }) {
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setContent("");
    setError("");
    fetch(artifactOpenUrl(artifact), { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Preview failed (${response.status})`);
        }
        return response.text();
      })
      .then((text) => {
        if (!cancelled) {
          setContent(text);
          setLoading(false);
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Failed to load text preview",
          );
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [artifact]);

  if (loading) {
    return (
      <div className="artifact-preview__empty">
        <div className="artifact-preview__empty-title">
          Loading text preview
        </div>
        <div className="artifact-preview__empty-copy">
          Fetching artifact contents…
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="artifact-preview__empty">
        <div className="artifact-preview__empty-title">
          Text preview unavailable
        </div>
        <div className="artifact-preview__empty-copy">{error}</div>
      </div>
    );
  }
  return (
    <section className="artifact-preview__body">
      <div className="artifact-preview__panel">
        <div className="artifact-preview__panel-title">Artifact contents</div>
        <div className="artifact-preview__panel-copy">
          Inline text rendering for workspace artifacts.
        </div>
        <pre className="artifact-preview__pre artifact-preview__pre--text">
          {content || "(empty file)"}
        </pre>
      </div>
    </section>
  );
}

export function HtmlWorkspace({ artifact }: { artifact: ToolArtifact }) {
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const htmlPreviewHref = useMemo(() => officePreviewUrl(artifact), [artifact]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setHtml("");
    setError("");
    fetch(htmlPreviewHref, { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Preview failed (${response.status})`);
        }
        return response.text();
      })
      .then((payload) => {
        if (!cancelled) {
          setHtml(payload);
          setLoading(false);
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Failed to load HTML preview",
          );
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [htmlPreviewHref]);

  if (loading) {
    return (
      <div className="artifact-preview__empty">
        <div className="artifact-preview__empty-title">
          Loading HTML preview
        </div>
        <div className="artifact-preview__empty-copy">
          Rendering the generated HTML artifact…
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="artifact-preview__empty">
        <div className="artifact-preview__empty-title">
          HTML preview unavailable
        </div>
        <div className="artifact-preview__empty-copy">{error}</div>
      </div>
    );
  }
  return (
    <section className="artifact-preview__body artifact-preview__body--html">
      <div className="artifact-preview__panel artifact-preview__panel--html">
        <iframe
          className="artifact-preview__frame artifact-preview__frame--html"
          srcDoc={html}
          title={artifact.name}
          // Generated HTML: an opaque origin, never the platform's (no allow-same-origin).
          sandbox="allow-scripts"
        />
      </div>
    </section>
  );
}
