// Knowledge → Explore: Relationships and Graph are two views of one page. The page ids stay
// (`knowledgeRelationships` is the List view and the visible entry, `knowledgeGraph` the Graph view, a hidden child),
// so stored links open the matching view. The shared filter and the selected entity live in the address, so a
// switch between the views (or a reload) keeps them. Pure functions only.

import type { ChangeFact } from "../../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { originLabel } from "../../../admin/components/workspaceKnowledge/search/searchFacets";
import { relationLabel } from "../relationshipPresenter";

export type ExploreView = "list" | "graph";
export type ExploreTab = "knowledgeRelationships" | "knowledgeGraph";

export const EXPLORE_TABS: Record<ExploreView, ExploreTab> = { list: "knowledgeRelationships", graph: "knowledgeGraph" };

/** The view a page id shows; anything else is the List view. */
export function exploreViewForTab(tab: string | null | undefined): ExploreView {
  return tab === "knowledgeGraph" ? "graph" : "list";
}

/** Graph is an admin page (presentation only, the server authorizes); everyone else sees the List view alone. */
export function exploreViews(isAdmin: boolean): ExploreView[] {
  return isAdmin ? ["list", "graph"] : ["list"];
}

export const EXPLORE_VIEW_LABELS: Record<ExploreView, string> = { list: "List", graph: "Graph" };

// `origin` is optional: the relationship and graph endpoints do not send it yet; the filter only offers what the
// shown items carry (search hits do).
export type ExploreFilter = { text: string; type: string; origin: string };
export type ExploreState = ExploreFilter & { entity: string };

export const EMPTY_EXPLORE: ExploreState = { text: "", type: "", origin: "", entity: "" };

const PARAMS: Record<keyof ExploreState, string> = {
  text: "explore_q", type: "explore_type", origin: "explore_origin", entity: "explore_entity",
};
const MAX_TEXT = 500;

/** The Explore state a URL carries. */
export function readExploreState(search: string): ExploreState {
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search);
  } catch {
    return EMPTY_EXPLORE;
  }
  const value = (key: keyof ExploreState) => (params.get(PARAMS[key]) ?? "").trim().slice(0, MAX_TEXT);
  return { text: value("text"), type: value("type"), origin: value("origin"), entity: value("entity") };
}

/** The same address with the Explore state written into it; empty fields leave the address. */
export function withExploreState(href: string, state: ExploreState): string {
  const url = new URL(href);
  for (const key of Object.keys(PARAMS) as (keyof ExploreState)[]) {
    const value = state[key].trim();
    if (value) url.searchParams.set(PARAMS[key], value);
    else url.searchParams.delete(PARAMS[key]);
  }
  return url.toString();
}

export type ExploreFact = ChangeFact & { origin?: { kind?: string | null } | null };
export type FilterOption = { value: string; label: string; count: number };

const originKind = (fact: ExploreFact) =>
  typeof fact.origin?.kind === "string" ? fact.origin.kind.trim().toLowerCase() : "";

/** A relationship with something to check: a citation or a link to its source. */
export function hasSource(fact: Pick<ChangeFact, "citation" | "source_url">): boolean {
  return Boolean(fact.citation?.trim() || fact.source_url?.trim());
}

const sameName = (left: string, right: string) => left.trim().toLowerCase() === right.trim().toLowerCase();

/** Whether a relationship is about the entity (its subject or its object). */
export function concernsEntity(fact: Pick<ChangeFact, "subject" | "object">, name: string): boolean {
  return Boolean(name.trim()) && (sameName(fact.subject, name) || sameName(fact.object, name));
}

/**
 * The relationships the filter keeps. The text narrows by subject, object or statement; the type is the kind of
 * relationship; relationships without a source stay hidden unless asked for (concept: "unbelegt" is hidden by
 * default).
 */
export function filterFacts(facts: ExploreFact[], filter: ExploreFilter, showUnsourced = false): ExploreFact[] {
  const text = filter.text.trim().toLowerCase();
  return facts.filter((fact) =>
    (showUnsourced || hasSource(fact)) &&
    (!text || [fact.subject, fact.object, fact.fact].some((value) => value.toLowerCase().includes(text))) &&
    (!filter.type || fact.relation === filter.type) &&
    (!filter.origin || originKind(fact) === filter.origin));
}

/** How many relationships the default hides because they cite no source. */
export function unsourcedCount(facts: ExploreFact[]): number {
  return facts.filter((fact) => !hasSource(fact)).length;
}

const counted = (values: string[], label: (value: string) => string): FilterOption[] => {
  const counts = new Map<string, number>();
  for (const value of values) if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()].map(([value, count]) => ({ value, label: label(value), count }))
    .sort((left, right) => left.label.localeCompare(right.label));
};

/** The kinds of relationship the shown facts offer ("renamed to", "removed", …). */
export function relationTypeOptions(facts: ExploreFact[]): FilterOption[] {
  return counted(facts.map((fact) => fact.relation), relationLabel);
}

/** The origins the shown items carry ("Confluence", "Jira", …); empty while the server sends none. */
export function originOptions(facts: ExploreFact[]): FilterOption[] {
  return counted(facts.map(originKind), originLabel);
}

/** The entity types of a graph view, from its stats ("System", "Component", …). */
export function entityTypeOptions(nodeTypes: Record<string, number> | null | undefined): FilterOption[] {
  return Object.entries(nodeTypes ?? {}).filter(([, count]) => count > 0)
    .map(([value, count]) => ({ value, label: value, count }))
    .sort((left, right) => left.label.localeCompare(right.label));
}

/** A type the current view does not offer is dropped, so a switch between views never hides everything. */
export function keepOfferedType(type: string, options: FilterOption[]): string {
  return options.some((option) => option.value === type) ? type : "";
}

/** The address of Knowledge → Search with a query to run ("Search for this"). */
export function searchForHref(href: string, query: string): string {
  const url = new URL(href);
  for (const key of Object.values(PARAMS)) url.searchParams.delete(key);
  url.searchParams.set("tab", "knowledgeLibrary");
  url.searchParams.set(SEARCH_QUERY_PARAM, query.trim().slice(0, MAX_TEXT));
  return url.toString();
}

// The entity's side panel opened as a page ("Open as page", design system): the same Explore address plus this flag.
export const ENTITY_PAGE_PARAM = "explore_entity_page";

/** The address of the selected entity as a full page (with it) or as the panel over the list (without it). */
export function entityPageHref(href: string, entity: string, asPage = true): string {
  const url = new URL(href);
  if (entity.trim()) url.searchParams.set(PARAMS.entity, entity.trim().slice(0, MAX_TEXT));
  if (asPage && entity.trim()) url.searchParams.set(ENTITY_PAGE_PARAM, "1");
  else url.searchParams.delete(ENTITY_PAGE_PARAM);
  return url.toString();
}

/** Whether the address asks for the entity as a page. */
export function isEntityPage(search: string): boolean {
  try {
    return new URLSearchParams(search).get(ENTITY_PAGE_PARAM) === "1";
  } catch {
    return false;
  }
}

/** A stable key of one relationship row (the same fact can be cited twice). */
export function factRowKey(fact: Pick<ChangeFact, "subject" | "relation" | "object" | "citation" | "version">, index: number): string {
  return [fact.subject, fact.relation, fact.object, fact.version ?? "", fact.citation ?? "", index].join("|");
}

/** The source of a row in one short line: the readable place (without "rev N"), else the source title, else "". */
export function sourceText(fact: Pick<ChangeFact, "citation" | "source_title">, readable: (citation: string) => string): string {
  const citation = fact.citation?.trim() ? readable(fact.citation.trim()) : "";
  return citation || fact.source_title?.trim() || "";
}

// Read by Knowledge → Search (KnowledgeSearchPanel), which runs it once and removes it from the address.
export const SEARCH_QUERY_PARAM = "q";
