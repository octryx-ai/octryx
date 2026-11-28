// Separate page ids for the two views, so stored links open the matching view.

import type { ChangeFact } from "../../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { originLabel } from "../../../admin/components/workspaceKnowledge/search/searchFacets";
import { relationLabel } from "../relationshipPresenter";

export type ExploreView = "list" | "graph";
export type ExploreTab = "knowledgeRelationships" | "knowledgeGraph";

export const EXPLORE_TABS: Record<ExploreView, ExploreTab> = { list: "knowledgeRelationships", graph: "knowledgeGraph" };

export function exploreViewForTab(tab: string | null | undefined): ExploreView {
  return tab === "knowledgeGraph" ? "graph" : "list";
}

// Presentation only; the server authorizes.
export function exploreViews(isAdmin: boolean): ExploreView[] {
  return isAdmin ? ["list", "graph"] : ["list"];
}

export const EXPLORE_VIEW_LABELS: Record<ExploreView, string> = { list: "List", graph: "Graph" };

// The relationship and graph endpoints do not send origin yet.
export type ExploreFilter = { text: string; type: string; origin: string };
export type ExploreState = ExploreFilter & { entity: string };

export const EMPTY_EXPLORE: ExploreState = { text: "", type: "", origin: "", entity: "" };

const PARAMS: Record<keyof ExploreState, string> = {
  text: "explore_q", type: "explore_type", origin: "explore_origin", entity: "explore_entity",
};
const MAX_TEXT = 500;

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

export function hasSource(fact: Pick<ChangeFact, "citation" | "source_url">): boolean {
  return Boolean(fact.citation?.trim() || fact.source_url?.trim());
}

const sameName = (left: string, right: string) => left.trim().toLowerCase() === right.trim().toLowerCase();

export function concernsEntity(fact: Pick<ChangeFact, "subject" | "object">, name: string): boolean {
  return Boolean(name.trim()) && (sameName(fact.subject, name) || sameName(fact.object, name));
}

export function filterFacts(facts: ExploreFact[], filter: ExploreFilter, showUnsourced = false): ExploreFact[] {
  const text = filter.text.trim().toLowerCase();
  return facts.filter((fact) =>
    (showUnsourced || hasSource(fact)) &&
    (!text || [fact.subject, fact.object, fact.fact].some((value) => value.toLowerCase().includes(text))) &&
    (!filter.type || fact.relation === filter.type) &&
    (!filter.origin || originKind(fact) === filter.origin));
}

export function unsourcedCount(facts: ExploreFact[]): number {
  return facts.filter((fact) => !hasSource(fact)).length;
}

const counted = (values: string[], label: (value: string) => string): FilterOption[] => {
  const counts = new Map<string, number>();
  for (const value of values) if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()].map(([value, count]) => ({ value, label: label(value), count }))
    .sort((left, right) => left.label.localeCompare(right.label));
};

export function relationTypeOptions(facts: ExploreFact[]): FilterOption[] {
  return counted(facts.map((fact) => fact.relation), relationLabel);
}

export function originOptions(facts: ExploreFact[]): FilterOption[] {
  return counted(facts.map(originKind), originLabel);
}

export function entityTypeOptions(nodeTypes: Record<string, number> | null | undefined): FilterOption[] {
  return Object.entries(nodeTypes ?? {}).filter(([, count]) => count > 0)
    .map(([value, count]) => ({ value, label: value, count }))
    .sort((left, right) => left.label.localeCompare(right.label));
}

// So a switch between views never hides everything.
export function keepOfferedType(type: string, options: FilterOption[]): string {
  return options.some((option) => option.value === type) ? type : "";
}

export function searchForHref(href: string, query: string): string {
  const url = new URL(href);
  for (const key of Object.values(PARAMS)) url.searchParams.delete(key);
  url.searchParams.set("tab", "knowledgeLibrary");
  url.searchParams.set(SEARCH_QUERY_PARAM, query.trim().slice(0, MAX_TEXT));
  return url.toString();
}

export const ENTITY_PAGE_PARAM = "explore_entity_page";

export function entityPageHref(href: string, entity: string, asPage = true): string {
  const url = new URL(href);
  if (entity.trim()) url.searchParams.set(PARAMS.entity, entity.trim().slice(0, MAX_TEXT));
  if (asPage && entity.trim()) url.searchParams.set(ENTITY_PAGE_PARAM, "1");
  else url.searchParams.delete(ENTITY_PAGE_PARAM);
  return url.toString();
}

export function isEntityPage(search: string): boolean {
  try {
    return new URLSearchParams(search).get(ENTITY_PAGE_PARAM) === "1";
  } catch {
    return false;
  }
}

// The same fact can be cited twice.
export function factRowKey(fact: Pick<ChangeFact, "subject" | "relation" | "object" | "citation" | "version">, index: number): string {
  return [fact.subject, fact.relation, fact.object, fact.version ?? "", fact.citation ?? "", index].join("|");
}

export function sourceText(fact: Pick<ChangeFact, "citation" | "source_title">, readable: (citation: string) => string): string {
  const citation = fact.citation?.trim() ? readable(fact.citation.trim()) : "";
  return citation || fact.source_title?.trim() || "";
}

export const SEARCH_QUERY_PARAM = "q";
