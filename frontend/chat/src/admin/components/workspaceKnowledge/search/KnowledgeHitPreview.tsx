import { useEffect, useState } from "react";

import { SidePanel } from "../../../../layout/SidePanel";
import { TimeText } from "../../../utils/TimeText";
import { workspaceKnowledgeApi } from "../workspaceKnowledgeApi";
import { type EvidenceHit, type EvidenceWindow } from "../workspaceKnowledgeTypes";
import { SnippetMarkdown } from "./SnippetMarkdown";
import { hitDate, hitPlace, hitSourceUrl, openInLabel, originKindOf, originLabel } from "./searchFacets";

type WindowState = { key: string; context: EvidenceWindow | null };

// The preview of a chosen hit: a side panel over the dimmed results, opened on demand, so the results
// keep the page's full width. The passage is highlighted between its neighbours, read with the reader's own access
// (…/evidence/{key}/window); when the window cannot be read the passage is shown alone.
export function KnowledgeHitPreview({ workspaceId, hit, onClose, terms, loadWindow = workspaceKnowledgeApi.evidenceWindow }: {
  workspaceId: string;
  hit: EvidenceHit;
  // The question's words, marked in the found passage.
  terms?: string[];
  onClose: () => void;
  loadWindow?: (workspaceId: string, evidenceKey: string) => Promise<EvidenceWindow | null>;
}) {
  const [state, setState] = useState<WindowState | null>(null);
  useEffect(() => {
    let current = true;
    setState(null);
    Promise.resolve()
      .then(() => loadWindow(workspaceId, hit.evidence_key))
      .then((context) => { if (current) setState({ key: hit.evidence_key, context }); })
      .catch(() => { if (current) setState({ key: hit.evidence_key, context: null }); });
    return () => { current = false; };
  }, [workspaceId, hit.evidence_key, loadWindow]);
  const context = state?.key === hit.evidence_key ? state.context : null;
  const kind = originKindOf(hit);
  const url = hitSourceUrl(hit);
  const place = hitPlace(hit);
  const date = hitDate(hit);
  const subtitle = [originLabel(kind), hit.container ?? "", place].filter(Boolean).join(" · ");
  return (
    <SidePanel title={hit.source_title} subtitle={subtitle || undefined} onClose={onClose} testId="search-preview"
      footer={url ? <a className="admin-panel__action-btn admin-panel__action-btn--primary" href={url} target="_blank" rel="noopener noreferrer">
        {openInLabel(kind)}</a> : undefined}>
      <div className="knowledge-search__preview-body">
        {date ? <span className="knowledge-search__meta">{date.label} <TimeText value={date.value} mode="date" /></span> : null}
        {context?.before.map((text, index) => <SnippetMarkdown key={`b${index}`} text={text} className="knowledge-search__context" />)}
        {/* The found passage, marked between its neighbours. */}
        <div className="knowledge-search__highlight" data-testid="preview-passage">
          <SnippetMarkdown text={context?.passage || hit.text} terms={terms} />
        </div>
        {context?.after.map((text, index) => <SnippetMarkdown key={`a${index}`} text={text} className="knowledge-search__context" />)}
      </div>
    </SidePanel>
  );
}
