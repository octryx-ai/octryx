// Custom REST source: the form state, its defaults, the media types and mapping fields, and a stored source's form.
import type { Pair } from "../../../../chat/work/intake/restIntakeForm";
import { record, str } from "./restSourceValues";

export const REST_KIND = "custom_rest";

export type ContentFrom = "record" | "detail" | "field";
export type Visibility = "restricted" | "workspace";
export type MappingField = "title" | "id" | "url" | "updated_at" | "version";

export const MEDIA_JSON = "application/json";
// The server's media types (sync/rest_config.py MEDIA_TYPES), in words.
export const MEDIA_TYPES: Array<{ value: string; label: string }> = [
  { value: "text/markdown", label: "Markdown" },
  { value: "text/plain", label: "Plain text" },
  { value: "text/html", label: "HTML" },
  { value: "application/pdf", label: "PDF (base64 in the field)" },
  { value: MEDIA_JSON, label: "JSON (rendered as text)" },
];

export const MAPPING_FIELDS: Array<{ name: MappingField; label: string; placeholder: string; hint?: string }> = [
  { name: "title", label: "Title *", placeholder: "title" },
  { name: "id", label: "Id *", placeholder: "id", hint: "Stable per record: it identifies the item across syncs." },
  { name: "url", label: "Link", placeholder: "link", hint: "Where a reader opens the record. http(s) only." },
  { name: "updated_at", label: "Updated", placeholder: "updated", hint: "An ISO 8601 time. Updated or Version is required." },
  { name: "version", label: "Version", placeholder: "rev", hint: "Changes whenever the record changes." },
];

export type RestKnowledgeForm = {
  definition: string;
  operation: string;
  role: string;
  arguments: Pair[];
  contentFrom: ContentFrom;
  detailOperation: string;
  detailParam: string;
  // The field that holds the text: required for "field", optional for "detail" (empty: the whole detail answer).
  contentPath: string;
  mediaType: string;
  updatedSinceParam: string;
  mapping: Record<MappingField, string>;
  visibility: Visibility;
};

export function emptyRestKnowledgeForm(): RestKnowledgeForm {
  return {
    definition: "", operation: "", role: "", arguments: [], contentFrom: "record", detailOperation: "", detailParam: "",
    contentPath: "", mediaType: MEDIA_JSON, updatedSinceParam: "",
    mapping: { title: "", id: "", url: "", updated_at: "", version: "" },
    // Restricted by default: the grants decide who finds an item (backend rest_config.py).
    visibility: "restricted",
  };
}


/** The form of a stored source: the connector's `scope`, which holds its `mapping` (backend stores both together). */
export function restKnowledgeFormOf(scope: unknown): RestKnowledgeForm {
  const given = record(scope);
  const mapping = record(given.mapping);
  const detail = str(given.detail_operation);
  const content = str(mapping.content);
  const empty = emptyRestKnowledgeForm();
  return {
    ...empty,
    definition: str(given.definition),
    operation: str(given.operation),
    role: str(given.role),
    arguments: Object.entries(record(given.arguments)).map(([name, value]) => ({ name, value: str(value) })),
    contentFrom: detail ? "detail" : content ? "field" : "record",
    detailOperation: detail,
    detailParam: str(given.detail_param),
    contentPath: content,
    mediaType: str(given.media_type) || MEDIA_JSON,
    updatedSinceParam: str(given.updated_since_param),
    mapping: { title: str(mapping.title), id: str(mapping.id), url: str(mapping.url), updated_at: str(mapping.updated_at),
      version: str(mapping.version) },
    visibility: given.visibility === "workspace" ? "workspace" : "restricted",
  };
}

/** Switching where the content comes from keeps the mapping and sets the media type each variant starts with. */
export function withContentFrom(form: RestKnowledgeForm, contentFrom: ContentFrom): RestKnowledgeForm {
  if (contentFrom === form.contentFrom) return form;
  return { ...form, contentFrom, mediaType: contentFrom === "field" ? "text/markdown" : MEDIA_JSON,
    ...(contentFrom === "detail" ? {} : { detailOperation: "", detailParam: "" }),
    ...(contentFrom === "record" ? { contentPath: "" } : {}) };
}
