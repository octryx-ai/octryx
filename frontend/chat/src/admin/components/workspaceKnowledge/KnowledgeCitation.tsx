import { originalContentUrl } from "./workspaceKnowledgeRequest";

// A hit read through a binding belongs to another workspace that authorizes its own originals.
export type CitationOriginal = { workspaceId: string; sourceId: string; revisionId: string };

type Props = {
  title: string;
  url: string | null;
  citation: string;
  section?: string | null;
  original?: CitationOriginal | null;
  titleShown?: boolean;
};

export function citationPlace(citation: string, title: string): string {
  const prefix = `${title} (`;
  return citation.startsWith(prefix) && citation.endsWith(")") ? citation.slice(prefix.length, -1) : citation;
}

// The revision number is an internal counter, not something a reader looks up.
export function readableCitation(citation: string): string {
  return citation
    .replace(/\(rev \d+\)/g, "")
    .replace(/\brev \d+,\s*/g, "")
    .replace(/,\s*rev \d+\b/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function sectionPath(section: string, title: string): string {
  return section.startsWith(`${title} > `) ? section.slice(title.length + 3) : section;
}

export function KnowledgeCitation({ title, url, citation: full, section: fullSection, original, titleShown }: Props) {
  const citation = readableCitation(titleShown ? citationPlace(full, title) : full);
  const section = fullSection && titleShown ? sectionPath(fullSection, title) : fullSection;
  return (
    <div style={{ fontSize: "var(--ds-text-xs)", color: "var(--muted)", marginTop: "0.25rem", overflowWrap: "anywhere" }}>
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
        <span title={full}>{citation}</span>
      )}
      {section && !citation.includes(section) ? <span> · § {section}</span> : null}
    </div>
  );
}
