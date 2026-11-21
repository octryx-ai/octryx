import type { EvidenceHit } from "../workspaceKnowledgeTypes";
import { originKindOf } from "./searchFacets";

// Knowledge → Search: one page in several versions ("Service Catalog 2026", "… 2025 (deprecated)",
// "… 2022/2023") is not shown as near-identical hits. Versions of one page family become one hit with
// "+N older versions"; a title marked deprecated ranks below the current ones. Only the title and the place are
// compared (same origin, same space or project); the ranking inside each kind of hit stays the server's.
// Several passages of one page ("Service Catalog 2022/2023" as #2 and #5) are one hit at the best
// passage's rank, the others under "+N more passages"; passages of a folded older version stay with it, unseen.

export type PresentedHit = {
  hit: EvidenceHit;
  number: number;
  older: EvidenceHit[];
  passages: EvidenceHit[];
  // Further passages of a folded older version: not listed, but they carry the family's number.
  hidden: EvidenceHit[];
};

const DEPRECATED = /\b(deprecated|obsolete|outdated|archived?|superseded)\b/i;
const YEAR = /\b(19|20)\d{2}(\s*[/–-]\s*((19|20)?\d{2}))?\b/g;
const VERSION = /\b(v(ersion)?\s*\d+(\.\d+)*|\d+\.\d+(\.\d+)*)\b/gi;

export function isDeprecatedTitle(title: string): boolean {
  return DEPRECATED.test(title);
}

/** The title without years, versions and deprecation marks: what the versions of one page have in common. */
export function titleStem(title: string): string {
  return title
    .replace(/[([]\s*(deprecated|obsolete|outdated|archived?|superseded)\s*[)\]]/gi, " ")
    .replace(DEPRECATED, " ")
    .replace(YEAR, " ")
    .replace(VERSION, " ")
    .replace(/[\s·:,–_-]+/g, " ")
    .trim()
    .toLowerCase();
}

function familyKey(hit: EvidenceHit): string | null {
  const stem = titleStem(hit.source_title ?? "");
  // A title that is only a year or a version has nothing in common with others but that: never grouped.
  if (stem.length < 3) return null;
  return [originKindOf(hit), (hit.container ?? "").trim().toLowerCase(), stem].join("\u0000");
}

/** The page a passage belongs to: its source (per Workspace), else its link; null when nothing identifies it. */
export function pageKey(hit: EvidenceHit): string | null {
  const workspace = hit.workspace ?? "";
  if (hit.source_id) return `source\u0000${workspace}\u0000${hit.source_id}`;
  const url = (hit.origin?.url || hit.source_url || "").trim();
  return url ? `url\u0000${workspace}\u0000${url}` : null;
}

/**
 * The hits as the page shows them: current titles before deprecated ones (each in the server's order), and the
 * further versions of one page family folded under its first hit, further passages of one page under its best one.
 * Numbers count the shown hits from `firstNumber`.
 */
export function presentHits(hits: EvidenceHit[], firstNumber = 1): PresentedHit[] {
  const ordered = [
    ...hits.filter((hit) => !isDeprecatedTitle(hit.source_title ?? "")),
    ...hits.filter((hit) => isDeprecatedTitle(hit.source_title ?? "")),
  ];
  const families = new Map<string, PresentedHit>();
  // A page seen before: its shown entry, and whether that page is the entry's own (true) or a folded version.
  const pages = new Map<string, { entry: PresentedHit; own: boolean }>();
  const shown: PresentedHit[] = [];
  for (const hit of ordered) {
    const page = pageKey(hit);
    const seen = page === null ? undefined : pages.get(page);
    if (seen) {
      (seen.own ? seen.entry.passages : seen.entry.hidden).push(hit);
      continue;
    }
    const key = familyKey(hit);
    const family = key === null ? undefined : families.get(key);
    if (family) {
      family.older.push(hit);
      if (page !== null) pages.set(page, { entry: family, own: false });
      continue;
    }
    const entry: PresentedHit = { hit, number: firstNumber + shown.length, older: [], passages: [], hidden: [] };
    shown.push(entry);
    if (key !== null) families.set(key, entry);
    if (page !== null) pages.set(page, { entry, own: true });
  }
  return shown;
}

/** Each hit's number on the page; a folded version or passage carries the number of the hit it sits under. */
export function hitNumbers(presented: PresentedHit[]): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const entry of presented) {
    for (const hit of [entry.hit, ...entry.passages, ...entry.older, ...entry.hidden]) numbers.set(hit.evidence_key, entry.number);
  }
  return numbers;
}

/** Every passage of the presented hits: each page's best first, then further passages, then older versions. */
export function presentedEvidence(presented: PresentedHit[]): EvidenceHit[] {
  return [
    ...presented.map((entry) => entry.hit),
    ...presented.flatMap((entry) => entry.passages),
    ...presented.flatMap((entry) => [...entry.older, ...entry.hidden]),
  ];
}
