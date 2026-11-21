import { useEffect, useId, useRef, useState } from "react";

import { TimeText } from "../../../utils/TimeText";
import { hitMetaLine } from "../knowledgeSearchPresenter";
import { originalContentUrl } from "../workspaceKnowledgeRequest";
import { type EvidenceHit } from "../workspaceKnowledgeTypes";
import { SnippetMarkdown } from "./SnippetMarkdown";
import { groupPresented, hitDate, hitPlace, hitSourceUrl, openInLabel, originKindOf, type NumberedHit } from "./searchFacets";
import { excerptFor } from "./snippet";

// The results grouped by the system they come from (Confluence, Jira, ServiceNow, Code …), each hit with its
// number on the page, title, space or project, a labelled date and the part of the passage with the question's
// words, marked. No score, revision or character offsets: the order is the ranking.
// Further versions of one page sit folded under it, further passages of the same page under its best
// one; a cited or chosen passage opens its fold. "Preview" opens the hit on the right.
export function KnowledgeHitGroups({ shown, workspaceId, selectedKey, onSelect, labelledBy, terms = [] }: {
  shown: NumberedHit[];
  workspaceId: string;
  selectedKey: string | null;
  onSelect: (hit: EvidenceHit) => void;
  labelledBy?: string;
  terms?: string[];
}) {
  const groups = groupPresented(shown);
  const single = groups.length === 1;
  return (
    <div className="knowledge-search__groups" data-testid="search-groups">
      {groups.map((group) => (
        <section key={group.kind || "sources"} className="knowledge-search__group" aria-label={single ? undefined : group.label}>
          {single ? null : <h3 className="knowledge-search__group-head">{group.label} <span className="knowledge-search__count">{group.hits.length}</span></h3>}
          <ol className="knowledge-search__list" aria-labelledby={single ? labelledBy : undefined}>
            {group.hits.map((entry) => (
              <KnowledgeHitRow key={entry.hit.evidence_key} entry={entry} workspaceId={workspaceId} terms={terms}
                selectedKey={selectedKey} onSelect={onSelect} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

function HitDateText({ hit }: { hit: EvidenceHit }) {
  const date = hitDate(hit);
  return date ? <>{date.label} <TimeText value={date.value} mode="date" /></> : null;
}

function KnowledgeHitRow({ entry, workspaceId, terms, selectedKey, onSelect }: {
  entry: NumberedHit; workspaceId: string; terms: string[]; selectedKey: string | null; onSelect: (hit: EvidenceHit) => void;
}) {
  const { hit, number, older } = entry;
  const passages = entry.passages ?? [];
  const id = useId();
  const row = useRef<HTMLLIElement>(null);
  const collapsing = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [passagesOpen, setPassagesOpen] = useState(false);
  const passageChosen = passages.some((passage) => passage.evidence_key === selectedKey);
  const versionChosen = older.some((version) => version.evidence_key === selectedKey);
  // A citation marker or preview choosing a folded passage or version shows it where it sits.
  useEffect(() => { if (passageChosen) setPassagesOpen(true); }, [passageChosen]);
  useEffect(() => { if (versionChosen) setVersionsOpen(true); }, [versionChosen]);
  const excerpt = excerptFor(hit.text, terms);
  // The excerpt is bounded (snippet.ts); the full passage opens on demand.
  const expandable = excerpt !== hit.text.trim();
  const selected = selectedKey === hit.evidence_key || passageChosen || versionChosen;
  const place = hitPlace(hit);
  const url = hitSourceUrl(hit);
  const original = !url && !hit.bound && hit.source_id && hit.revision_id
    ? originalContentUrl(workspaceId, hit.source_id, hit.revision_id) : null;
  const meta = [hit.container ?? "", hitMetaLine(hit), place].filter(Boolean).join(" · ");
  const date = hitDate(hit);
  // Collapsing a long passage keeps its row in view instead of leaving the reader further down the list.
  useEffect(() => {
    if (!collapsing.current) return;
    collapsing.current = false;
    row.current?.scrollIntoView?.({ block: "nearest" });
  }, [expanded]);
  const toggle = () => { collapsing.current = expanded; setExpanded(!expanded); };
  return (
    <li ref={row} className={`knowledge-search__hit${selected ? " knowledge-search__hit--selected" : ""}`} value={number}
      data-kind={originKindOf(hit) || undefined}>
      <article aria-labelledby={`${id}-title`}>
        <h3 id={`${id}-title`} className="knowledge-search__hit-title">
          <span className="knowledge-search__hit-number" aria-hidden="true">{number}</span>{hit.source_title}
        </h3>
        {meta || date ? (
          <p className="knowledge-search__meta">
            {meta}{date ? <>{meta ? " · " : ""}<HitDateText hit={hit} /></> : null}
          </p>
        ) : null}
        <div id={`${id}-passage`}>
          <SnippetMarkdown text={expanded ? hit.text : excerpt} terms={terms} className="knowledge-search__passage" />
        </div>
        <HitFoot hit={hit} id={id} url={url} original={original} expandable={expandable} expanded={expanded} toggle={toggle}
          selectedKey={selectedKey} onSelect={onSelect} passages={passages} passagesOpen={passagesOpen} setPassagesOpen={setPassagesOpen}
          older={older} versionsOpen={versionsOpen} setVersionsOpen={setVersionsOpen} />
        {passages.length && passagesOpen ? (
          <MorePassages id={id} hit={hit} passages={passages} terms={terms} selectedKey={selectedKey} onSelect={onSelect} />
        ) : null}
        {older.length && versionsOpen ? <OlderVersions id={id} hit={hit} older={older} selectedKey={selectedKey} onSelect={onSelect} /> : null}
      </article>
    </li>
  );
}

// Show full passage, Preview, the link to the source, and the folds for more passages and older versions.
function HitFoot({ hit, id, url, original, expandable, expanded, toggle, selectedKey, onSelect, passages, passagesOpen, setPassagesOpen,
  older, versionsOpen, setVersionsOpen }: {
  hit: EvidenceHit;
  id: string;
  url: string | null;
  original: string | null;
  expandable: boolean;
  expanded: boolean;
  toggle: () => void;
  selectedKey: string | null;
  onSelect: (hit: EvidenceHit) => void;
  passages: EvidenceHit[];
  passagesOpen: boolean;
  setPassagesOpen: (open: boolean) => void;
  older: EvidenceHit[];
  versionsOpen: boolean;
  setVersionsOpen: (open: boolean) => void;
}) {
  return (
    <div className="knowledge-search__hit-foot">
      {expandable ? <button type="button" className="knowledge-search__toggle" aria-expanded={expanded}
        aria-controls={`${id}-passage`} onClick={toggle}>{expanded ? "Show less" : "Show full passage"}</button> : null}
      <button type="button" className="knowledge-search__toggle" aria-pressed={selectedKey === hit.evidence_key}
        onClick={() => onSelect(hit)}>Preview</button>
      {url ? <a href={url} target="_blank" rel="noopener noreferrer">{openInLabel(originKindOf(hit))}</a>
        : original ? <a href={original} target="_blank" rel="noopener noreferrer">Open original</a> : null}
      {passages.length ? <button type="button" className="knowledge-search__toggle" aria-expanded={passagesOpen}
        aria-controls={`${id}-passages`} data-testid="search-more-passages"
        onClick={() => setPassagesOpen(!passagesOpen)}>
        {passagesOpen ? "Hide more passages" : `+${passages.length} more ${passages.length === 1 ? "passage" : "passages"}`}
      </button> : null}
      {older.length ? <button type="button" className="knowledge-search__toggle" aria-expanded={versionsOpen}
        aria-controls={`${id}-versions`} data-testid="search-older-versions"
        onClick={() => setVersionsOpen(!versionsOpen)}>
        {versionsOpen ? "Hide older versions" : `+${older.length} older ${older.length === 1 ? "version" : "versions"}`}
      </button> : null}
    </div>
  );
}

function MorePassages({ id, hit, passages, terms, selectedKey, onSelect }: {
  id: string; hit: EvidenceHit; passages: EvidenceHit[]; terms: string[]; selectedKey: string | null; onSelect: (hit: EvidenceHit) => void;
}) {
  return (
    <ul id={`${id}-passages`} className="knowledge-search__versions knowledge-search__passages" aria-label={`More passages of ${hit.source_title}`}>
      {passages.map((passage) => (
        <li key={passage.evidence_key} data-testid="search-passage">
          <SnippetMarkdown text={excerptFor(passage.text, terms)} terms={terms} className="knowledge-search__passage" />
          <button type="button" className="knowledge-search__toggle" aria-pressed={selectedKey === passage.evidence_key}
            onClick={() => onSelect(passage)}>Preview</button>
        </li>
      ))}
    </ul>
  );
}

function OlderVersions({ id, hit, older, selectedKey, onSelect }: {
  id: string; hit: EvidenceHit; older: EvidenceHit[]; selectedKey: string | null; onSelect: (hit: EvidenceHit) => void;
}) {
  return (
    <ul id={`${id}-versions`} className="knowledge-search__versions" aria-label={`Older versions of ${hit.source_title}`}>
      {older.map((version) => (
        <li key={version.evidence_key}>
          <button type="button" className="knowledge-search__toggle" aria-pressed={selectedKey === version.evidence_key}
            onClick={() => onSelect(version)}>{version.source_title}</button>
          {hitDate(version) ? <span className="knowledge-search__meta"> · <HitDateText hit={version} /></span> : null}
        </li>
      ))}
    </ul>
  );
}
