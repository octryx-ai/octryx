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

export const CSRF_HEADER = "x-csrf-token";
export const CSRF_LABEL = "Fetch a CSRF token before writes";
export const CSRF_HINT = "Before each write Octryx reads a token with x-csrf-token: Fetch and sends it with the write, as SAP Gateway requires.";
export const CSRF_FETCH_PATH_HINT = "Empty = the connection's base URL. Only needed if the base URL is above the service.";
export const CSRF_HEADER_HINT = "Empty = x-csrf-token, as SAP Gateway uses.";

// A switch that is on always stays visible.
export const csrfApplies = (scheme: AuthScheme, hasWrites: boolean | null, on: boolean) =>
  on || (scheme !== "none" && hasWrites !== false);

export const csrfDefault = (odata: boolean, hasWrites: boolean, scheme: AuthScheme) => odata && hasWrites && scheme !== "none";

export function withScheme<D extends Pick<ManualDraft, "scheme" | "csrf">>(draft: D, scheme: AuthScheme, odata: boolean, hasWrites: boolean): D {
  if (scheme === "none") return { ...draft, scheme, csrf: false };
  if (draft.scheme === "none") return { ...draft, scheme, csrf: draft.csrf || csrfDefault(odata, hasWrites, scheme) };
  return { ...draft, scheme };
}

export type TemplateOption = { value: OdataTemplate; label: string; hint: string };

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

export function applyTemplate<D extends Pick<OperationDraft, "recordsPath" | "pagination">>(draft: D, name: OdataTemplate | ""): D {
  if (!name) return draft;
  const values = TEMPLATE_VALUES[name];
  return { ...draft, recordsPath: values.recordsPath, pagination: { ...values.pagination } };
}

export function apiTemplate(operations: ReadonlyArray<Pick<RestOperation, "preset">>): { value: OdataTemplate; count: number } | null {
  const counts = new Map<OdataTemplate, number>();
  for (const op of operations) if (op.preset) counts.set(op.preset, (counts.get(op.preset) ?? 0) + 1);
  let best: { value: OdataTemplate; count: number } | null = null;
  for (const [value, count] of counts) if (!best || count > best.count) best = { value, count };
  return best;
}

export function apiTemplateText(operations: ReadonlyArray<Pick<RestOperation, "preset">>): string {
  const best = apiTemplate(operations);
  return best ? `${templateLabel(best.value)} on ${best.count} collection read${best.count === 1 ? "" : "s"}` : "";
}

export const BATCH_LABEL = "$batch is not supported";
export const BATCH_HINT = "A $batch carries several requests past the per-call grants and audit. Enable the single operations instead.";
export const isBatch = (op: { unsupported?: string }) => op.unsupported === "odata_batch";

export const wireNameOf = (param: Pick<RestParameter, "name" | "wire_name">) =>
  param.wire_name && param.wire_name !== param.name ? param.wire_name : null;

// Rows count blank lines too; the body keeps only the non-empty entries, split at commas (manualBody).
export function serverRowOfIndex(servers: string, index: number): number | null {
  let seen = 0;
  const rows = servers.split("\n");
  for (let row = 0; row < rows.length; row += 1) {
    seen += rows[row].split(",").filter((part) => part.trim()).length;
    if (index < seen) return row;
  }
  return null;
}

export type PresetChoice = "inherit" | "none" | OdataTemplate | "";

const SINGLE_RESULT_ENDINGS = [")", "/$count", "/$value", "/$batch", "}"];

export function isCollectionRead(op: Pick<RestOperation, "method" | "path">): boolean {
  const path = op.path.replace(/\/+$/, "");
  return op.method.toUpperCase() === "GET" && !SINGLE_RESULT_ENDINGS.some((ending) => path.endsWith(ending));
}

const emptyAnswer = (): { recordsPath: string; pagination: PaginationDraft } => ({ recordsPath: "", pagination: emptyPagination("none") });

export function initialPresetChoice(
  op: Pick<RestOperation, "preset" | "preset_source">,
  draft: Pick<OperationDraft, "recordsPath" | "pagination">,
): PresetChoice {
  if (op.preset_source !== "operation") return "inherit";
  if (op.preset) return op.preset;
  return !draft.recordsPath.trim() && draft.pagination.type === "none" ? "none" : "";
}

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

export function editAnswer(draft: OperationDraft, patch: Partial<Pick<OperationDraft, "recordsPath" | "pagination">>): OperationDraft {
  const next = { ...draft, ...patch };
  return { ...next, presetChoice: templateOf(next) };
}

export function answerBody(draft: OperationDraft): Record<string, unknown> {
  if (draft.presetChoice !== "") return { preset: draft.presetChoice };
  return { records_path: draft.recordsPath.trim(), pagination: paginationBody(draft.pagination) };
}

export const PRESET_SOURCE_LABELS: Record<PresetSource, string> = {
  definition: "From the API default",
  operation: "Set for this operation",
  none: "None",
};

export function presetInEffect(op: Pick<RestOperation, "method" | "path" | "preset" | "preset_source">): string {
  if (!isCollectionRead(op) && op.method.toUpperCase() === "GET") return SINGLE_READ_NOTE;
  const source = op.preset_source;
  if (source === "none") return PRESET_SOURCE_LABELS.none;
  const what = op.preset ? templateLabel(op.preset) : source === "operation" ? "Own records path and pages" : "No template";
  return `${what} · ${PRESET_SOURCE_LABELS[source]}`;
}

export const SINGLE_READ_NOTE = "Not applicable: a single-entity read returns one record and never pages.";

export type PresetOption = { value: PresetChoice; label: string };

export function presetOptions(defaultPreset: OdataTemplate | "" | undefined): PresetOption[] {
  const templates = ODATA_TEMPLATES.map((entry) => ({ value: entry.value as PresetChoice, label: entry.label }));
  return [
    { value: "inherit", label: `Use the API default (${defaultPreset ? templateLabel(defaultPreset) : "no template"})` },
    { value: "none", label: "No template" },
    ...templates,
    { value: "", label: BY_HAND },
  ];
}

export const DEFAULT_PRESET_OPTIONS: ReadonlyArray<{ value: OdataTemplate | ""; label: string }> = [
  { value: "", label: "No template" },
  ...ODATA_TEMPLATES.map((entry) => ({ value: entry.value, label: entry.label })),
];

export const DEFAULT_PRESET_HINT = "Collection reads without their own settings use it; an operation can choose another under Setup.";
