// How Knowledge → Relationships presents one extracted fact. The cited statement is the headline,
// because it is what the source says. The graph's subject/object entity names are only shown where the
// relation really relates two things; for a change that concerns one subject (removed, deprecated,
// introduced, default changed) the extractor still attaches some target entity (often a version or the
// document title), and showing it as "→ object" would contradict the statement.
//
// Relation types: backend/app/services/knowledge/temporal/profiles/change_records.json.

import type { ChangeFact, ChangesResult } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";

// The object is part of the meaning: new name, successor, new location, required baseline.
export const BINARY_RELATIONS: ReadonlySet<string> = new Set(["RENAMED", "REPLACED_BY", "MOVED_TO", "REQUIRES"]);

const RELATION_LABELS: Record<string, string> = {
  RENAMED: "renamed to",
  REPLACED_BY: "replaced by",
  MOVED_TO: "moved to",
  REQUIRES: "requires",
  REMOVED: "removed",
  DEPRECATED: "deprecated",
  DEFAULT_CHANGED: "default changed",
  INTRODUCED: "introduced",
};

// The server's page bounds (api/routes/knowledge_graph.py ChangesRequest.limit le=200).
export const RELATIONSHIP_PAGE = 30;
export const MAX_RELATIONSHIPS = 200;

export function relationLabel(relation: string): string {
  return RELATION_LABELS[relation] ?? relation.toLowerCase().replaceAll("_", " ");
}

export function isTypedChange(relation: string): boolean {
  return relation in RELATION_LABELS;
}

export type PresentedFact = {
  headline: string;
  subject: string;
  relation: string;
  // Null for a relation about the subject alone, and for an untyped relation.
  object: string | null;
  typed: boolean;
};

export function presentFact(fact: Pick<ChangeFact, "fact" | "relation" | "subject" | "object">): PresentedFact {
  const subject = fact.subject.trim();
  const object = fact.object.trim();
  const binary = BINARY_RELATIONS.has(fact.relation) && Boolean(object) && object !== subject;
  return {
    headline: fact.fact.trim() || `${subject} ${relationLabel(fact.relation)}${binary ? ` ${object}` : ""}`,
    subject,
    relation: relationLabel(fact.relation),
    object: binary ? object : null,
    typed: isTypedChange(fact.relation),
  };
}

// The next limit for "Show more", or null when the last page was short or the maximum is reached.
export function nextRelationshipLimit(limit: number, returned: number): number | null {
  if (returned < limit || limit >= MAX_RELATIONSHIPS) return null;
  return Math.min(limit + RELATIONSHIP_PAGE, MAX_RELATIONSHIPS);
}

// Truthful count line. Without a query the kind counts cover the whole range; with one they count the page.
export function relationshipCountText(
  result: Pick<ChangesResult, "facts" | "kind_counts">, hasQuery: boolean, upToVersion: string,
): string {
  const shown = result.facts.length;
  const total = Object.values(result.kind_counts ?? {}).reduce((sum, count) => sum + count, 0);
  const scope = `up to version ${upToVersion}`;
  if (!hasQuery && total > shown) return `Showing ${shown} of ${total} relationships ${scope}.`;
  if (hasQuery) return `Showing the ${shown} best ${shown === 1 ? "match" : "matches"} ${scope}.`;
  return `Showing all ${shown} ${shown === 1 ? "relationship" : "relationships"} ${scope}.`;
}
