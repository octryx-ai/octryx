// Pure model of the builder's content steps (content routing): which detectors a content policy names, the
// outcome rules (route only for model requests, sticky only with a route, the approved-model exception only for
// Mask on Call a model), the approved-model chips, the side badge, and the server's detector catalog and preview
// answers parsed defensively. Detection never runs in the browser: counts and the masked rendering come from
// `POST …/content-detectors/preview`.

import type { BuilderModel } from "./policyBuilderModel";

type Json = Record<string, unknown>;

const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const records = (value: unknown): Json[] => (Array.isArray(value) ? value.filter(isRecord) : []);

export const CONTENT_ACTIONS = ["call_model", "receive_tool_result"] as const;
export type OutcomeKind = "block" | "mask" | "reroute" | "mask_reroute";
export const OUTCOME_KINDS: OutcomeKind[] = ["block", "mask", "reroute", "mask_reroute"];
export const ROUTE_REFUSED = "Tool results are masked or blocked at the source; routing applies to model requests.";

export const blankContent = (): BuilderModel["content"] => ({ detectors: [], sticky: false, incomplete: false });
export const blankOutcome = (): BuilderModel["outcome"] => ({ kind: "block", reroute_to: "", mask_style: "", approved_except: false });

export const routes = (kind: string) => kind === "reroute" || kind === "mask_reroute";
export const masks = (kind: string) => kind === "mask" || kind === "mask_reroute";

/** The one content action of the model, or null: the Content and Outcome steps exist only then. */
export function contentAction(model: Pick<BuilderModel, "actions">): string | null {
  return model.actions.length === 1 && (CONTENT_ACTIONS as readonly string[]).includes(model.actions[0]) ? model.actions[0] : null;
}

export const isContentPolicy = (model: BuilderModel) => model.content.detectors.length > 0;

export function readOutcomeKind(value: unknown): OutcomeKind {
  return OUTCOME_KINDS.includes(value as OutcomeKind) ? (value as OutcomeKind) : "block";
}

/** Choose an outcome. A route keeps the conversation on the approved model (sticky) by default; leaving the route
 * clears sticky; the approved-model exception stays only for Mask; masking starts with the type-token style. */
export function withOutcome(model: BuilderModel, kind: OutcomeKind): BuilderModel {
  const outcome = model.outcome;
  return {
    ...model,
    content: { ...model.content, sticky: routes(kind) },
    outcome: {
      kind,
      reroute_to: routes(kind) ? outcome.reroute_to : "",
      mask_style: masks(kind) ? outcome.mask_style || "type_token" : "",
      approved_except: kind === "mask" ? outcome.approved_except : false,
    },
  };
}

/** Why an outcome cannot be chosen for the model's action ("" when it can). */
export function outcomeRefusal(kind: OutcomeKind, action: string | null): string {
  return routes(kind) && action === "receive_tool_result" ? ROUTE_REFUSED : "";
}

/** After an action change: tool results cannot route (falls back to Mask), and without a content action the
 * content and outcome are cleared. */
export function normalizeContent(model: BuilderModel): BuilderModel {
  if (!model.actions.some((action) => (CONTENT_ACTIONS as readonly string[]).includes(action))) {
    return isContentPolicy(model) || model.outcome.kind !== "block" ? { ...model, content: blankContent(), outcome: blankOutcome() } : model;
  }
  const action = contentAction(model);
  let next = model;
  if (action === "receive_tool_result" && routes(model.outcome.kind)) next = withOutcome(next, "mask");
  if (action !== "call_model" && next.outcome.approved_except) next = { ...next, outcome: { ...next.outcome, approved_except: false } };
  return next;
}

// ---- detectors -------------------------------------------------------------------------------------------------

export type DetectorInfo = { id: string; category: string; label: string; method: string; builtin: boolean };
export type DetectorCategory = { id: string; label: string; note: string };
export type DetectorCatalog = { categories: DetectorCategory[]; detectors: DetectorInfo[] };
export const EMPTY_DETECTORS: DetectorCatalog = { categories: [], detectors: [] };

export function readDetectorCatalog(raw: unknown): DetectorCatalog {
  const value = isRecord(raw) ? raw : {};
  return {
    categories: records(value.categories).map((item) => ({ id: str(item.id), label: str(item.label) || str(item.id), note: str(item.note) })),
    detectors: records(value.detectors).map((item) => ({
      id: str(item.id), category: str(item.category), label: str(item.label) || str(item.id), method: str(item.method), builtin: item.builtin === true,
    })).filter((item) => item.id),
  };
}

/** Detector cards grouped by category, in the catalog's category order; categories without detectors are left out. */
export function detectorGroups(catalog: DetectorCatalog): { category: DetectorCategory; detectors: DetectorInfo[] }[] {
  const known = new Set(catalog.categories.map((item) => item.id));
  const extra = Array.from(new Set(catalog.detectors.map((item) => item.category))).filter((id) => !known.has(id)).map((id) => ({ id, label: id, note: "" }));
  return [...catalog.categories, ...extra]
    .map((category) => ({ category, detectors: catalog.detectors.filter((item) => item.category === category.id) }))
    .filter((group) => group.detectors.length > 0);
}

/** The categories the chosen detectors belong to, in detector order (what a route target must be approved for). */
export function categoriesOf(detectors: string[], catalog: DetectorCatalog): string[] {
  return Array.from(new Set(detectors.map((id) => catalog.detectors.find((item) => item.id === id)?.category ?? "").filter(Boolean)));
}

export type AliasOption = { alias: string; dataPolicyClass: string; approvedFor: string[] };

/** Every alias with whether it is approved for all the categories (only those can be picked). */
export function approvedAliases(aliases: AliasOption[], categories: string[]): (AliasOption & { approved: boolean })[] {
  return aliases.map((item) => ({ ...item, approved: categories.every((category) => item.approvedFor.includes(category)) }));
}

/** Toggle a detector; a route target no longer approved for the categories is cleared. */
export function toggleDetector(model: BuilderModel, id: string, catalog: DetectorCatalog, aliases: AliasOption[]): BuilderModel {
  const detectors = model.content.detectors.includes(id) ? model.content.detectors.filter((item) => item !== id) : [...model.content.detectors, id];
  const target = aliases.find((item) => item.alias === model.outcome.reroute_to);
  const categories = categoriesOf(detectors, catalog);
  const stillApproved = !target || categories.every((category) => target.approvedFor.includes(category));
  return {
    ...model,
    content: { ...model.content, detectors },
    outcome: stillApproved ? model.outcome : { ...model.outcome, reroute_to: "" },
  };
}

// ---- side card -------------------------------------------------------------------------------------------------

const BADGES: Record<OutcomeKind, string> = { block: "Blocks", mask: "Masks", reroute: "Routes", mask_reroute: "Masks · routes" };

export function effectBadge(model: BuilderModel): { label: string; tone: "danger" | "running" } {
  const kind = contentAction(model) ? model.outcome.kind : "block";
  return { label: BADGES[kind], tone: kind === "block" ? "danger" : "running" };
}

/** The side warning while a route has no target (`stepNumber`: the Outcome step's position; `onlyInput`: it is the
 * template's only missing input). */
export function routeTargetWarning(model: BuilderModel, stepNumber: number, onlyInput = false): string | null {
  if (!contentAction(model) || !routes(model.outcome.kind) || model.outcome.reroute_to) return null;
  return `Pick the approved model in step ${stepNumber} (Outcome)${onlyInput ? " — the only required input of this template" : ""}.`;
}

// ---- server preview --------------------------------------------------------------------------------------------

export type PreviewPart = { text: string; detector: string; masked: boolean; placeholder: string };
export type ContentPreview = { counts: Record<string, number>; parts: PreviewPart[]; truncated: boolean };
export const EMPTY_CONTENT_PREVIEW: ContentPreview = { counts: {}, parts: [], truncated: false };

export function readContentPreview(raw: unknown): ContentPreview {
  const value = isRecord(raw) ? raw : {};
  const counts = isRecord(value.counts) ? value.counts : {};
  return {
    counts: Object.fromEntries(Object.entries(counts).filter((entry): entry is [string, number] => typeof entry[1] === "number")),
    parts: records(value.parts).map((item) => ({ text: str(item.text), detector: str(item.detector), masked: item.masked === true, placeholder: str(item.placeholder) })),
    truncated: value.truncated === true,
  };
}

/** How a found part is shown: masked outcomes show the placeholder, block/route show the hit as found. */
export function previewMark(part: PreviewPart, model: BuilderModel): { shown: string; mark: "none" | "hit" | "blocked" } {
  if (!part.detector || !model.content.detectors.includes(part.detector)) return { shown: part.text, mark: "none" };
  const kind = model.outcome.kind;
  return { shown: masks(kind) && part.placeholder ? part.placeholder : part.text, mark: kind === "block" ? "blocked" : "hit" };
}
