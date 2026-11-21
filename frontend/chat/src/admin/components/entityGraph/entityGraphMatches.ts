// What the entity-graph search found, stated plainly. The server marks an entity as matched when its
// name contains the query, or when it is an end of a shown relationship whose statement contains the
// query (backend `knowledge/temporal/visualization.py::_present`). The basis is re-derived here from the
// returned payload by that same rule; an entity the rule cannot explain is labelled as a server match
// instead of being given a guessed reason. Neighbours of matches are shown for context only.

import type { EntityGraphPayload } from "./entityGraphTypes";

export type MatchBasis = "name" | "statement" | "server";

export const MATCH_BASIS_ORDER: MatchBasis[] = ["name", "statement", "server"];

export function matchedIds(payload: Pick<EntityGraphPayload, "match_ids" | "nodes"> | null): Set<string> {
  if (!payload) return new Set();
  if (Array.isArray(payload.match_ids)) return new Set(payload.match_ids);
  return new Set(payload.nodes.filter((node) => node.matched).map((node) => node.id));
}

// The server strips, case-folds and caps the query at 500 characters. JavaScript has no case-fold;
// lower-casing agrees for ordinary text, and any disagreement falls back to the "server" basis.
export function normalizeQuery(query: string): string {
  return query.trim().toLowerCase().slice(0, 500);
}

export function matchBases(
  payload: Pick<EntityGraphPayload, "match_ids" | "nodes" | "edges"> | null, query: string,
): Map<string, MatchBasis> {
  const bases = new Map<string, MatchBasis>();
  const needle = normalizeQuery(query);
  if (!payload || !needle) return bases;
  const names = new Map(payload.nodes.map((node) => [node.id, (node.display_name || "").toLowerCase()]));
  const statementEnds = new Set<string>();
  for (const edge of payload.edges) {
    if (!(edge.description || "").toLowerCase().includes(needle)) continue;
    statementEnds.add(edge.source);
    statementEnds.add(edge.target);
  }
  for (const id of matchedIds(payload)) {
    if (names.get(id)?.includes(needle)) bases.set(id, "name");
    else if (statementEnds.has(id)) bases.set(id, "statement");
    else bases.set(id, "server");
  }
  return bases;
}

export function matchBasisLabel(basis: MatchBasis, query: string): string {
  if (basis === "name") return `Name contains “${query.trim()}”`;
  if (basis === "statement") return `A relationship statement mentions “${query.trim()}”`;
  return "Matched by the server";
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

// One summary line for the toolbar. Every count describes this bounded view, never the workspace.
export function viewSummary(input: {
  entities: number; relationships: number; truncated: boolean; query: string;
  bases: Map<string, MatchBasis>; capped?: boolean;
}): string {
  const shown = `Showing ${plural(input.entities, "entity", "entities")} and `
    + `${plural(input.relationships, "relationship", "relationships")} in this view${input.truncated ? " (bounded)" : ""}.`;
  const query = input.query.trim();
  if (!query) return shown;
  const count = input.bases.size;
  if (!count) return `${shown} No entities match “${query}” in this view.`;
  const by = (basis: MatchBasis) => [...input.bases.values()].filter((value) => value === basis).length;
  const parts = [`${by("name")} by name`, `${by("statement")} via a relationship statement`];
  if (by("server")) parts.push(`${by("server")} matched by the server`);
  const context = Math.max(0, input.entities - count);
  const head = `${count}${input.capped ? "+" : ""} ${count === 1 ? "entity matches" : "entities match"} “${query}”`;
  return `${shown} ${head}: ${parts.join(", ")}`
    + (context ? `; ${plural(context, "connected entity", "connected entities")} shown for context.` : ".");
}

export function totalsScopeLabel(scope: EntityGraphPayload["stats"]["scope"]): string {
  return scope === "project" ? "in this workspace (including shared entities)" : "across all workspaces";
}
