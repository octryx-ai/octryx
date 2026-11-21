// Pure model of the guided policy builder: the structured policy the builder edits, mirroring
// the backend `builder_model.PolicyModel`. The browser never writes Cedar: the server renders the model (live
// preview) and saves it. Which blocks a step shows comes from the catalog: a block is shown when it applies to
// every chosen action, shown disabled with the reason when only the enforcement point lacks the fact, hidden
// otherwise. A content policy adds the Content and Outcome steps (`builderContentModel`).

import { blankContent, blankOutcome, contentAction, readOutcomeKind, routes } from "./builderContentModel";
import type { OutcomeKind } from "./builderContentModel";
import type { Catalog, CatalogBlock, CatalogTemplate } from "./policyCatalogModel";

type Json = Record<string, unknown>;

export type BuilderModel = {
  id: string; name: string; description: string; template: string; actions: string[];
  who: { mode: "everyone" | "users" | "roles" | "groups"; items: string[]; except_admins: boolean; session_profile: string; session_client: string };
  what: {
    families: string[]; tools: string[]; writes_only: boolean; reads_logs: boolean; models: string[]; model_mode: "except" | "only";
    remote_class_below: string; programs: string[]; prefixes: string[]; arguments: string[]; option_values: string[];
    unparseable: boolean; paths: string[]; client_tools: string[];
  };
  where: { workspaces: string[]; classification_at_least: string; classification_is: string[]; unclassified: boolean; connections: string[] };
  conditions: { unless_option_values: string[]; admission_unverified: boolean; seat_mode: string; governed_required: boolean; route: string };
  content: { detectors: string[]; sticky: boolean; incomplete: boolean };
  outcome: { kind: OutcomeKind; reroute_to: string; mask_style: string; approved_except: boolean };
};

export function blankModel(): BuilderModel {
  return {
    id: "", name: "", description: "", template: "", actions: [],
    who: { mode: "everyone", items: [], except_admins: false, session_profile: "", session_client: "" },
    what: {
      families: [], tools: [], writes_only: false, reads_logs: false, models: [], model_mode: "except", remote_class_below: "",
      programs: [], prefixes: [], arguments: [], option_values: [], unparseable: false, paths: [], client_tools: [],
    },
    where: { workspaces: [], classification_at_least: "", classification_is: [], unclassified: false, connections: [] },
    conditions: { unless_option_values: [], admission_unverified: false, seat_mode: "", governed_required: false, route: "" },
    content: blankContent(),
    outcome: blankOutcome(),
  };
}

const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);

function merge<T extends Json>(base: T, raw: unknown): T {
  if (!isRecord(raw)) return base;
  const next: Json = { ...base };
  for (const [key, value] of Object.entries(base)) {
    const given = raw[key];
    if (Array.isArray(value)) next[key] = Array.isArray(given) ? given.filter((item): item is string => typeof item === "string") : value;
    else if (typeof value === "boolean") next[key] = typeof given === "boolean" ? given : value;
    else if (typeof value === "string") next[key] = typeof given === "string" ? given : value;
  }
  return next as T;
}

/** A model from the server (`item.model`) or a template's partial model, with every missing field defaulted. */
export function readModel(raw: unknown): BuilderModel {
  const base = blankModel();
  const value = isRecord(raw) ? raw : {};
  const top = merge({ id: base.id, name: base.name, description: base.description, template: base.template, actions: base.actions }, value);
  return {
    ...top,
    who: merge(base.who, value.who) as BuilderModel["who"],
    what: merge(base.what, value.what) as BuilderModel["what"],
    where: merge(base.where, value.where),
    conditions: merge(base.conditions, value.conditions),
    content: merge(base.content, value.content),
    outcome: { ...merge(base.outcome, value.outcome), kind: readOutcomeKind(isRecord(value.outcome) ? value.outcome.kind : undefined) },
  };
}

export const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);

export function fromTemplate(template: CatalogTemplate): BuilderModel {
  const model = readModel(template.model);
  return { ...model, template: template.id, id: slug(model.name) || template.id };
}

/** A copy under a new, unused `@id` (and " (copy)" in the name); never a template instance. */
export function duplicateModel(model: BuilderModel, existingIds: string[]): BuilderModel {
  let id = `${model.id}-copy`;
  for (let index = 2; existingIds.includes(id); index += 1) id = `${model.id}-copy-${index}`;
  return { ...model, id, name: model.name ? `${model.name} (copy)` : "" };
}

export const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);

type Section = "who" | "what" | "where" | "conditions" | "content" | "outcome";

export function fieldValue(model: BuilderModel, field: string): unknown {
  const [section, name] = field.split(".") as [Section, string];
  return (model[section] as Json)?.[name];
}

export function withField(model: BuilderModel, field: string, value: unknown): BuilderModel {
  const [section, name] = field.split(".") as [Section, string];
  return { ...model, [section]: { ...(model[section] as Json), [name]: value } } as BuilderModel;
}

const filled = (value: unknown) => (Array.isArray(value) ? value.length > 0 : Boolean(value));

/** Template inputs still empty (a connection, a role …): the builder marks them and the server refuses to save. */
export function missingPlaceholders(model: BuilderModel, catalog: Catalog | null): { field: string; label: string; hint: string }[] {
  const template = catalog?.templates.find((item) => item.id === model.template);
  return (template?.placeholders ?? []).filter((item) => !filled(fieldValue(model, item.field)));
}

export type BlockState = { state: "available" | "disabled" | "hidden"; reason: string };

/** Whether a block can be used with the chosen actions (see the module comment). */
export function blockState(catalog: Catalog | null, blockId: string, actions: string[]): BlockState {
  const block = catalog?.blocks.find((item) => item.id === blockId);
  if (!block || !actions.length) return { state: "hidden", reason: "" };
  const missing = actions.filter((action) => !block.actions.includes(action));
  if (!missing.length) return { state: "available", reason: "" };
  const unclassified = missing.filter((action) => catalog?.actions.find((item) => item.id === action)?.carriesClassification === false);
  if (block.classificationBound && unclassified.length === missing.length) {
    const labels = unclassified.map((action) => catalog?.actions.find((item) => item.id === action)?.label ?? action).join(", ");
    return { state: "disabled", reason: `Not available for ${labels} yet: that check does not know the Workspace classification. Pick Workspaces instead.` };
  }
  return { state: "hidden", reason: "" };
}

export const blockOf = (catalog: Catalog | null, blockId: string): CatalogBlock | null => catalog?.blocks.find((item) => item.id === blockId) ?? null;

/** The actions whose check does not carry the user: who-conditions are not effective there yet. */
export function actionsWithoutUser(catalog: Catalog | null, actions: string[]): string[] {
  return actions.filter((action) => catalog?.actions.find((item) => item.id === action)?.carriesUser === false);
}

export const usesWho = (model: BuilderModel) =>
  (model.who.mode !== "everyone" && model.who.items.length > 0) || model.who.except_admins || Boolean(model.who.session_profile || model.who.session_client);

export type StepId = "basics" | "who" | "what" | "content" | "where" | "outcome" | "exceptions" | "check";
/** `content`: shown only for a content action (Call a model or Receive a tool result). */
export const STEPS: { id: StepId; label: string; hint: string; content?: true }[] = [
  { id: "basics", label: "Basics", hint: "Name it the way people will search for it; the @id follows the name." },
  { id: "who", label: "Who", hint: "Everyone, or only members of roles, groups or named users." },
  { id: "what", label: "What", hint: "The actions to block and, optionally, which connector, tool, model, command or path." },
  { id: "content", label: "Content", hint: "What the content scan must find: detectors, and whether an unfinished scan counts too.", content: true },
  { id: "where", label: "Where", hint: "All Workspaces, chosen ones, a classification or named connections." },
  { id: "outcome", label: "Outcome", hint: "Block, mask, or route the request to a model approved for this data.", content: true },
  { id: "exceptions", label: "Exceptions", hint: "When the block does not apply, e.g. a non-prod context." },
  { id: "check", label: "Check & save", hint: "See what it would block, then save it into the draft." },
];

/** The steps of this model: Content and Outcome only for a content action. */
export function visibleSteps(model: BuilderModel): typeof STEPS {
  const content = contentAction(model) !== null;
  return STEPS.filter((item) => !item.content || content);
}

export function stepDone(model: BuilderModel, step: StepId): boolean {
  if (step === "basics") return Boolean(model.id);
  if (step === "who") return model.who.mode === "everyone" || model.who.items.length > 0;
  if (step === "what") return model.actions.length > 0;
  if (step === "content") return model.content.detectors.length > 0;
  if (step === "outcome") return !routes(model.outcome.kind) || Boolean(model.outcome.reroute_to);
  return step === "where" || step === "exceptions";
}

/** The step a template opens on: the first one with an empty placeholder, else Check & save. */
export function startStep(model: BuilderModel, catalog: Catalog | null): StepId {
  const missing = missingPlaceholders(model, catalog)[0];
  if (!missing) return model.actions.length ? "check" : "basics";
  const section = missing.field.split(".")[0];
  return section === "who" ? "who" : section === "where" ? "where" : section === "conditions" ? "exceptions"
    : section === "content" ? "content" : section === "outcome" ? "outcome" : "what";
}

/** How the gateway check splits a command (agent_gateway/command_match, simplified for the preview): program, then
 * the arguments; `--flag value` also counts as `--flag=value`. Marks tokens the model matches. */
export function commandSplit(command: string, model: BuilderModel): { token: string; role: "program" | "argument"; hit: boolean }[] {
  const tokens = command.trim().split(/\s+/).filter(Boolean);
  const program = (tokens[0] ?? "").split("/").pop() ?? "";
  const values = new Set<string>();
  tokens.slice(1).forEach((token, index, rest) => {
    if (token.startsWith("-") && token.includes("=")) values.add(token);
    else if (token.startsWith("-") && rest[index + 1] && !rest[index + 1].startsWith("-")) values.add(`${token}=${rest[index + 1]}`);
  });
  const prefixTokens = new Set(model.what.prefixes.flatMap((prefix) => prefix.split(" ")));
  const optionHit = (token: string, next?: string) => [...model.what.option_values, ...model.conditions.unless_option_values]
    .some((option) => option === token || (next !== undefined && option === `${token}=${next}`) || option.split("=")[1] === token);
  return tokens.map((token, index) => index === 0
    ? { token: program, role: "program", hit: model.what.programs.includes(program) || prefixTokens.has(program) }
    : { token, role: "argument", hit: model.what.arguments.includes(token) || prefixTokens.has(token) || (values.size > 0 && optionHit(token, tokens[index + 1])) });
}

/** The request body of a policy-level save. */
export function saveBody(model: BuilderModel, isNew: boolean, note: string) {
  return { model, create: isNew, ...(note ? { note } : {}) };
}
