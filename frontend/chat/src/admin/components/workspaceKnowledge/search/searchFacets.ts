import type { EvidenceHit } from "../workspaceKnowledgeTypes";

export type SearchFacets = { kinds: string[]; containers: string[]; within: TimeWindow };
export type TimeWindow = "any" | "7d" | "30d" | "365d";
export const NO_FACETS: SearchFacets = { kinds: [], containers: [], within: "any" };

export const TIME_WINDOWS: { value: TimeWindow; label: string; days: number | null }[] = [
  { value: "any", label: "Any time", days: null },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
  { value: "365d", label: "Last year", days: 365 },
];

const ORIGIN_LABELS: Record<string, string> = {
  confluence: "Confluence",
  jira: "Jira",
  servicenow: "ServiceNow",
  git: "Code",
  git_repository: "Code",
  code: "Code",
  upload: "Uploaded documents",
  web: "Websites",
  custom_rest: "REST API",
};

export function originKindOf(hit: Pick<EvidenceHit, "origin">): string {
  return typeof hit.origin?.kind === "string" ? hit.origin.kind.trim().toLowerCase() : "";
}

export function originLabel(kind: string): string {
  if (!kind) return "Sources";
  return ORIGIN_LABELS[kind] ?? kind.replace(/[_-]+/g, " ").replace(/^./, (first) => first.toUpperCase());
}

export function openInLabel(kind: string): string {
  const label = ORIGIN_LABELS[kind];
  return label && kind !== "upload" ? `Open in ${label}` : "Open source";
}

export type NumberedHit = { hit: EvidenceHit; number: number; older: EvidenceHit[]; passages?: EvidenceHit[] };
export type HitGroup = { kind: string; label: string; hits: NumberedHit[] };

export function groupPresented(shown: NumberedHit[]): HitGroup[] {
  const groups: HitGroup[] = [];
  for (const entry of shown) {
    const kind = originKindOf(entry.hit);
    let group = groups.find((candidate) => candidate.kind === kind);
    if (!group) {
      group = { kind, label: originLabel(kind), hits: [] };
      groups.push(group);
    }
    group.hits.push(entry);
  }
  return groups;
}

export function groupHits(hits: EvidenceHit[], firstNumber = 1): HitGroup[] {
  return groupPresented(hits.map((hit, index) => ({ hit, number: firstNumber + index, older: [] })));
}

export type HitDate = { value: string; label: "changed" | "received" };

function sourceChangedAt(hit: Pick<EvidenceHit, "source_changed_at" | "origin">): string | null {
  return hit.origin?.source_changed_at || hit.source_changed_at || null;
}

export function hitDate(hit: Pick<EvidenceHit, "changed_at" | "source_changed_at" | "origin">): HitDate | null {
  const changed = sourceChangedAt(hit);
  if (changed) return { value: changed, label: "changed" };
  if (hit.changed_at) return { value: hit.changed_at, label: "received" };
  return null;
}

export type FacetOption = { value: string; label: string; count: number };

// Counts are documents, since the result list groups passages per document.
export function facetOptions(hits: EvidenceHit[]): { kinds: FacetOption[]; containers: FacetOption[] } {
  const count = (keyOf: (hit: EvidenceHit) => string) => {
    const sources = new Map<string, Set<string>>();
    for (const hit of hits) {
      const value = keyOf(hit);
      if (!value) continue;
      const seen = sources.get(value) ?? new Set<string>();
      seen.add(String(hit.source_id ?? hit.evidence_key ?? ""));
      sources.set(value, seen);
    }
    return [...sources.entries()].map(([value, seen]) => [value, seen.size] as [string, number]);
  };
  return {
    kinds: count(originKindOf).map(([value, total]) => ({ value, label: originLabel(value), count: total })),
    containers: count((hit) => (hit.container ?? "").trim())
      .map(([value, total]) => ({ value, label: value, count: total }))
      .sort((a, b) => a.label.localeCompare(b.label)),
  };
}

function changedAt(hit: Pick<EvidenceHit, "changed_at" | "source_changed_at" | "origin">): number | null {
  const value = sourceChangedAt(hit) || hit.changed_at;
  const time = typeof value === "string" ? Date.parse(value) : NaN;
  return Number.isFinite(time) ? time : null;
}

// A hit without a date is kept only under "Any time"; nothing is guessed.
export function applyFacets(hits: EvidenceHit[], facets: SearchFacets, now: number = Date.now()): EvidenceHit[] {
  const days = TIME_WINDOWS.find((entry) => entry.value === facets.within)?.days ?? null;
  return hits.filter((hit) => {
    if (facets.kinds.length && !facets.kinds.includes(originKindOf(hit))) return false;
    if (facets.containers.length && !facets.containers.includes((hit.container ?? "").trim())) return false;
    if (days !== null) {
      const time = changedAt(hit);
      if (time === null || now - time > days * 86_400_000) return false;
    }
    return true;
  });
}

export function activeFacetCount(facets: SearchFacets): number {
  return facets.kinds.length + facets.containers.length + Number(facets.within !== "any");
}

function sectionInside(section: string, title: string): string {
  return section.startsWith(`${title} > `) ? section.slice(title.length + 3) : section;
}

// Never revision, offsets or score: bookkeeping, not a place a reader can find.
export function hitPlace(hit: Pick<EvidenceHit, "section" | "pages" | "lines" | "source_title">): string {
  const parts: string[] = [];
  if (hit.section) parts.push(`§ ${sectionInside(hit.section, hit.source_title)}`);
  if (hit.pages && hit.pages.length === 2) {
    parts.push(hit.pages[0] === hit.pages[1] ? `p. ${hit.pages[0]}` : `pp. ${hit.pages[0]}–${hit.pages[1]}`);
  }
  if (hit.lines && hit.lines.length === 2) {
    parts.push(hit.lines[0] === hit.lines[1] ? `line ${hit.lines[0]}` : `lines ${hit.lines[0]}–${hit.lines[1]}`);
  }
  return parts.join(" · ");
}

export function hitSourceUrl(hit: Pick<EvidenceHit, "origin" | "source_url">): string | null {
  return hit.origin?.url || hit.source_url || null;
}
