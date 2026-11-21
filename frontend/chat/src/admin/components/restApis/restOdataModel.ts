// REST API model: OData options, templates, CSRF defaults and the per-operation preset choice.
import type {
  AuthScheme,
  OdataTemplate,
  PaginationType,
  PresetSource,
  RestOperation,
  RestParameter,
} from "./restApisApi";
import { type OperationDraft, paginationBody, type PaginationDraft } from "./restOperationEditorModel";
import type { ManualDraft } from "./restDefinitionDraftsModel";

// ---- OData (backend) ---------------------------------------------------------------------------------------

export const CSRF_HEADER = "x-csrf-token";
export const CSRF_LABEL = "Fetch a CSRF token before writes";
export const CSRF_HINT = "Before each write Octryx reads a token with x-csrf-token: Fetch and sends it with the write, as SAP Gateway requires.";
export const CSRF_FETCH_PATH_HINT = "Empty = the connection's base URL. Only needed if the base URL is above the service.";
export const CSRF_HEADER_HINT = "Empty = x-csrf-token, as SAP Gateway uses.";

/**
 * Whether the CSRF switch belongs on the form: only with an auth scheme, and only where writes are possible
 * (`hasWrites` null: not known yet, as when an API is entered by hand). A switch that is on always stays visible.
 */
export const csrfApplies = (scheme: AuthScheme, hasWrites: boolean | null, on: boolean) =>
  on || (scheme !== "none" && hasWrites !== false);

/** The import's default (backend openapi_reader): on for an OData spec with writes and an auth scheme. */
export const csrfDefault = (odata: boolean, hasWrites: boolean, scheme: AuthScheme) => odata && hasWrites && scheme !== "none";

/** A scheme change in a form: the switch follows the import's rule when auth is added, and is off without auth. */
export function withScheme<D extends Pick<ManualDraft, "scheme" | "csrf">>(draft: D, scheme: AuthScheme, odata: boolean, hasWrites: boolean): D {
  if (scheme === "none") return { ...draft, scheme, csrf: false };
  if (draft.scheme === "none") return { ...draft, scheme, csrf: draft.csrf || csrfDefault(odata, hasWrites, scheme) };
  return { ...draft, scheme };
}

export type TemplateOption = { value: OdataTemplate; label: string; hint: string };

// The wording follows backend odata.py: records path and next page per template.
export const ODATA_TEMPLATES: ReadonlyArray<TemplateOption> = [
  { value: "odata_v2", label: "OData v2", hint: "Records in d.results; the next page from d.__next." },
  { value: "odata_v2_offset", label: "OData v2, paged with $skip and $top", hint: "Records in d.results; pages with $skip and $top, 50 per page." },
  { value: "odata_v4", label: "OData v4", hint: "Records in value; the next page from @odata.nextLink." },
];
export const ALIAS_NOTE = "OData options such as $select are offered to the model without the $ (select) and sent with it.";
export const BY_HAND = "Set by hand";
export const ODATA_IMPORT_NOTE =
  "An OData document is recognized: its collection reads get the matching template, and with writes and authentication a CSRF token is fetched before writes.";

const TEMPLATE_VALUES: Record<OdataTemplate, { recordsPath: string; pagination: PaginationDraft }> = {
  odata_v2: { recordsPath: "d.results", pagination: { ...emptyPagination("next_url"), next_path: "d.__next" } },
  odata_v2_offset: {
    recordsPath: "d.results",
    pagination: { ...emptyPagination("offset"), offset_param: "$skip", limit_param: "$top", page_size: "50" },
  },
  odata_v4: { recordsPath: "value", pagination: { ...emptyPagination("next_url"), next_path: "@odata.nextLink" } },
};

function emptyPagination(type: PaginationType): PaginationDraft {
  return { type, cursor_path: "", cursor_param: "", offset_param: "", limit_param: "", page_size: "", next_path: "" };
}

export const templateLabel = (name: string | null | undefined) =>
  ODATA_TEMPLATES.find((entry) => entry.value === name)?.label ?? BY_HAND;
export const templateHint = (name: string | null | undefined) => ODATA_TEMPLATES.find((entry) => entry.value === name)?.hint ?? "";

/** The template a draft's records path and pages equal (as backend odata.preset_of), else "" (set by hand). */
export function templateOf(draft: Pick<OperationDraft, "recordsPath" | "pagination">): OdataTemplate | "" {
  const same = (a: PaginationDraft, b: PaginationDraft) => (Object.keys(a) as Array<keyof PaginationDraft>)
    .filter((name) => name === "type" || PAGINATION_KEYS[a.type].includes(name))
    .every((name) => String(a[name]).trim() === String(b[name]).trim());
  for (const entry of ODATA_TEMPLATES) {
    const values = TEMPLATE_VALUES[entry.value];
    if (draft.recordsPath.trim() === values.recordsPath && draft.pagination.type === values.pagination.type && same(values.pagination, draft.pagination)) {
      return entry.value;
    }
  }
  return "";
}

const PAGINATION_KEYS: Record<PaginationType, Array<keyof PaginationDraft>> = {
  none: [], link_header: [], cursor: ["cursor_path", "cursor_param"], offset: ["offset_param", "limit_param", "page_size"], next_url: ["next_path"],
};

/** A template sets records path and pages; "" (set by hand) keeps what the draft has. */
export function applyTemplate<D extends Pick<OperationDraft, "recordsPath" | "pagination">>(draft: D, name: OdataTemplate | ""): D {
  if (!name) return draft;
  const values = TEMPLATE_VALUES[name];
  return { ...draft, recordsPath: values.recordsPath, pagination: { ...values.pagination } };
}

/** The template most of an API's operations use (import pre-fill), with how many; null when none uses one. */
export function apiTemplate(operations: ReadonlyArray<Pick<RestOperation, "preset">>): { value: OdataTemplate; count: number } | null {
  const counts = new Map<OdataTemplate, number>();
  for (const op of operations) if (op.preset) counts.set(op.preset, (counts.get(op.preset) ?? 0) + 1);
  let best: { value: OdataTemplate; count: number } | null = null;
  for (const [value, count] of counts) if (!best || count > best.count) best = { value, count };
  return best;
}

/** "OData v2 on 3 collection reads", or "" for an API without template. */
export function apiTemplateText(operations: ReadonlyArray<Pick<RestOperation, "preset">>): string {
  const best = apiTemplate(operations);
  return best ? `${templateLabel(best.value)} on ${best.count} collection read${best.count === 1 ? "" : "s"}` : "";
}

export const BATCH_LABEL = "$batch is not supported";
export const BATCH_HINT = "A $batch carries several requests past the per-call grants and audit. Enable the single operations instead.";
export const isBatch = (op: { unsupported?: string }) => op.unsupported === "odata_batch";

/** The name a parameter is sent under, when it differs from the one the model sees ($select for select); else null. */
export const wireNameOf = (param: Pick<RestParameter, "name" | "wire_name">) =>
  param.wire_name && param.wire_name !== param.name ? param.wire_name : null;

/**
 * The servers row (line of the textarea, blank lines included) that holds the body's server `index`: the body
 * keeps the non-empty entries of every line, split at commas (manualBody).
 */
export function serverRowOfIndex(servers: string, index: number): number | null {
  let seen = 0;
  const rows = servers.split("\n");
  for (let row = 0; row < rows.length; row += 1) {
    seen += rows[row].split(",").filter((part) => part.trim()).length;
    if (index < seen) return row;
  }
  return null;
}

// ---- OData preset as an API default (backend) ----------------------------------------------------------------

/** The template choice of one operation: the API default, none, a template, or "" (records path and pages by hand). */
export type PresetChoice = "inherit" | "none" | OdataTemplate | "";

const SINGLE_RESULT_ENDINGS = [")", "/$count", "/$value", "/$batch", "}"];

/** A GET of an entity set (as backend odata.is_collection_read); one entity by key, $count, $value never page. */
export function isCollectionRead(op: Pick<RestOperation, "method" | "path">): boolean {
  const path = op.path.replace(/\/+$/, "");
  return op.method.toUpperCase() === "GET" && !SINGLE_RESULT_ENDINGS.some((ending) => path.endsWith(ending));
}

const emptyAnswer = (): { recordsPath: string; pagination: PaginationDraft } => ({ recordsPath: "", pagination: emptyPagination("none") });

/** The choice an operation opens with: what the server says it uses (`preset_source`, backend `serialize_operation`). */
export function initialPresetChoice(
  op: Pick<RestOperation, "preset" | "preset_source">,
  draft: Pick<OperationDraft, "recordsPath" | "pagination">,
): PresetChoice {
  if (op.preset_source !== "operation") return "inherit";
  if (op.preset) return op.preset;
  return !draft.recordsPath.trim() && draft.pagination.type === "none" ? "none" : "";
}

/**
 * A choice in the Template select: the fields show what the operation will run with (the API default's template for a
 * collection read, nothing for "none", the template's values); "set by hand" keeps the fields as they are.
 */
export function choosePreset(
  draft: OperationDraft,
  choice: PresetChoice,
  context: { defaultPreset: OdataTemplate | "" | undefined; collection: boolean },
): OperationDraft {
  if (choice === "") return { ...draft, presetChoice: "" };
  const effective = choice === "inherit" ? (context.collection ? context.defaultPreset || "" : "") : choice === "none" ? "" : choice;
  const fields = effective ? TEMPLATE_VALUES[effective] : emptyAnswer();
  return { ...draft, recordsPath: fields.recordsPath, pagination: { ...fields.pagination }, presetChoice: choice };
}

/** An edit of the records path or pages: they are then set by hand, unless they equal a template again. */
export function editAnswer(draft: OperationDraft, patch: Partial<Pick<OperationDraft, "recordsPath" | "pagination">>): OperationDraft {
  const next = { ...draft, ...patch };
  return { ...next, presetChoice: templateOf(next) };
}

/**
 * The response part of the operation PUT: a choice is sent as `{preset: "inherit" | "none" | <name>}`; by hand the
 * records path and pages are sent.
 */
export function answerBody(draft: OperationDraft): Record<string, unknown> {
  if (draft.presetChoice !== "") return { preset: draft.presetChoice };
  return { records_path: draft.recordsPath.trim(), pagination: paginationBody(draft.pagination) };
}

export const PRESET_SOURCE_LABELS: Record<PresetSource, string> = {
  definition: "From the API default",
  operation: "Set for this operation",
  none: "None",
};

/**
 * What the operation runs with now, in words: "OData v2 · From the API default", "No template · Set for this
 * operation", "None"; a single-entity read has no template at all.
 */
export function presetInEffect(op: Pick<RestOperation, "method" | "path" | "preset" | "preset_source">): string {
  if (!isCollectionRead(op) && op.method.toUpperCase() === "GET") return SINGLE_READ_NOTE;
  const source = op.preset_source;
  if (source === "none") return PRESET_SOURCE_LABELS.none;
  const what = op.preset ? templateLabel(op.preset) : source === "operation" ? "Own records path and pages" : "No template";
  return `${what} · ${PRESET_SOURCE_LABELS[source]}`;
}

export const SINGLE_READ_NOTE = "Not applicable: a single-entity read returns one record and never pages.";

export type PresetOption = { value: PresetChoice; label: string };

/** The Template select of a collection read: the API default (named), no template, each template, set by hand. */
export function presetOptions(defaultPreset: OdataTemplate | "" | undefined): PresetOption[] {
  const templates = ODATA_TEMPLATES.map((entry) => ({ value: entry.value as PresetChoice, label: entry.label }));
  return [
    { value: "inherit", label: `Use the API default (${defaultPreset ? templateLabel(defaultPreset) : "no template"})` },
    { value: "none", label: "No template" },
    ...templates,
    { value: "", label: BY_HAND },
  ];
}

/** The API's Default template select: none or a template (PUT /rest-apis/{id} {default_preset}). */
export const DEFAULT_PRESET_OPTIONS: ReadonlyArray<{ value: OdataTemplate | ""; label: string }> = [
  { value: "", label: "No template" },
  ...ODATA_TEMPLATES.map((entry) => ({ value: entry.value, label: entry.label })),
];

export const DEFAULT_PRESET_HINT = "Collection reads without their own settings use it; an operation can choose another under Setup.";
