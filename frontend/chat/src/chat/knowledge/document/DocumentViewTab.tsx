import { Suspense, lazy, useEffect, useState } from "react";
import { originalContentUrl } from "../../../admin/components/workspaceKnowledge/workspaceKnowledgeRequest";
import { TimeText } from "../../../admin/utils/TimeText";
import { EmptyLine } from "../../../layout/EmptyLine";
import { loadRevisionView } from "./documentApi";
import type { Loaded } from "./documentApi";
import { isMarkdown, isPdf, viewDocument } from "./documentViewModel";
import type { DocumentView } from "./documentViewModel";

// The chat's Markdown renderer (raw HTML in the Markdown is never rendered), loaded only when a Markdown original shows.
const MarkdownRenderer = lazy(async () => ({ default: (await import("../../MarkdownRenderer")).MarkdownRenderer }));

const pageTheme = (): "dark" | "light" =>
  typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";

export type DocumentRevision = {
  revision_id: string; revision_ordinal: number; media_type: string; byte_size: number; span_count: number; state: string;
};

// One revision's original, shown in place: a PDF inline, HTML in a sandboxed frame (no scripts, no same origin),
// Markdown rendered (not as raw monospace text), other text as text. A too large or not
// displayable original says so in one line and offers the download.
export function DocumentViewTab({ workspaceId, sourceId, revision }: {
  workspaceId: string; sourceId: string; revision: DocumentRevision | null;
}) {
  const [loaded, setLoaded] = useState<Loaded<DocumentView> | null>(null);
  const revisionId = revision?.revision_id ?? null;
  const pdf = isPdf(revision?.media_type);
  useEffect(() => {
    if (!revisionId || pdf) return undefined;
    let current = true;
    setLoaded(null);
    void loadRevisionView(workspaceId, sourceId, revisionId).then((next) => { if (current) setLoaded(next); });
    return () => { current = false; };
  }, [workspaceId, sourceId, revisionId, pdf]);

  if (!revision) return <EmptyLine text="This document has no revision that can be shown." testId="document-view-empty" />;
  const originalUrl = originalContentUrl(workspaceId, sourceId, revision.revision_id);
  const download = { label: "Download original", href: originalUrl };
  const heading = <p className="document-view__meta" data-testid="document-view-meta">Revision {revision.revision_ordinal}
    {loaded?.ok && loaded.data.source_changed_at ? <> · changed <TimeText value={loaded.data.source_changed_at} /></> : null}
  </p>;

  if (pdf) {
    return <div className="document-view" data-testid="document-view-pdf">{heading}
      <object className="document-view__frame" data={originalUrl} type="application/pdf" aria-label={`Revision ${revision.revision_ordinal}`}>
        <EmptyLine text="This browser cannot show the PDF here." action={download} />
      </object>
    </div>;
  }
  if (!loaded) return <p className="document-view__meta" role="status">Loading the original…</p>;
  if (!loaded.ok) return <div className="document-view">{heading}
    <EmptyLine text={loaded.message} action={download} testId="document-view-error" /></div>;
  const view = loaded.data;
  if (view.state === "too_large") return <div className="document-view">{heading}
    <EmptyLine text="This original is too large to show here." action={download} testId="document-view-too-large" /></div>;
  if (view.html) {
    return <div className="document-view">{heading}
      <iframe className="document-view__frame" title={`Revision ${revision.revision_ordinal}`} sandbox=""
        referrerPolicy="no-referrer" srcDoc={viewDocument(view.html)} data-testid="document-view-html" />
    </div>;
  }
  if (view.text && (isMarkdown(view.content_type) || isMarkdown(revision.media_type))) {
    const plain = <pre className="document-view__text">{view.text}</pre>;
    return <div className="document-view">{heading}
      <div className="document-view__markdown" data-testid="document-view-markdown">
        <Suspense fallback={plain}><MarkdownRenderer content={view.text} theme={pageTheme()} /></Suspense>
      </div></div>;
  }
  if (view.text) return <div className="document-view">{heading}
    <pre className="document-view__text" data-testid="document-view-text">{view.text}</pre></div>;
  return <div className="document-view">{heading}
    <EmptyLine text="This original has no text to show." action={download} testId="document-view-empty" /></div>;
}
