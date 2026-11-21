import { originalContentUrl } from "./workspaceKnowledgeRequest";

// The uploaded original a citation can open: only for a hit of the reading workspace itself, because a
// hit read through a binding belongs to another workspace that authorizes its own originals.
export type CitationOriginal = { workspaceId: string; sourceId: string; revisionId: string };

type Props = {
  title: string;
  url: string | null;
  citation: string;
  section?: string | null;
  original?: CitationOriginal | null;
  // The title is already the heading above: show only the place inside the source.
  titleShown?: boolean;
};

// "Title (rev 1, p. 205, § 4.4.11 Database)" -> "rev 1, p. 205, § 4.4.11 Database" when the title is shown.
export function citationPlace(citation: string, title: string): string {
  const prefix = `${title} (`;
  return citation.startsWith(prefix) && citation.endsWith(")") ? citation.slice(prefix.length, -1) : citation;
}

// "Title (rev 1, p. 702, § 4.4 Database)" -> "Title (p. 702, § 4.4 Database)": the revision number is an internal
// counter of Octryx AI, not something a reader looks up. The full citation stays the tooltip.
export function readableCitation(citation: string): string {
  return citation
    .replace(/\(rev \d+\)/g, "")
    .replace(/\brev \d+,\s*/g, "")
    .replace(/,\s*rev \d+\b/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

// "Title > 1. Chapter > 1.2 Section" -> "1. Chapter > 1.2 Section" when the title is shown.
export function sectionPath(section: string, title: string): string {
  return section.startsWith(`${title} > `) ? section.slice(title.length + 3) : section;
}

// One citation: the source title as a link to exactly where the evidence came from. A source without an
// origin link (an uploaded file) opens its stored original instead.
export function KnowledgeCitation({ title, url, citation: full, section: fullSection, original, titleShown }: Props) {
  const citation = readableCitation(titleShown ? citationPlace(full, title) : full);
  const section = fullSection && titleShown ? sectionPath(fullSection, title) : fullSection;
  return (
    <div style={{ fontSize: "var(--ds-text-xs)", color: "var(--muted)", marginTop: "0.25rem", overflowWrap: "anywhere" }}>
      {/* The citation already names the source title, revision and place; it is the link. */}
      {url ? (
        <a href={url} target="_blank" rel="noopener noreferrer" title={full}>
          {citation}
        </a>
      ) : original ? (
        <>
          <span title={full}>{citation}</span>{" · "}
          <a href={originalContentUrl(original.workspaceId, original.sourceId, original.revisionId)}
            target="_blank" rel="noopener noreferrer">Open original</a>
        </>
      ) : (
        // Without a link the place is enough; no "(no link)" marker.
        <span title={full}>{citation}</span>
      )}
      {section && !citation.includes(section) ? <span> · § {section}</span> : null}
    </div>
  );
}
