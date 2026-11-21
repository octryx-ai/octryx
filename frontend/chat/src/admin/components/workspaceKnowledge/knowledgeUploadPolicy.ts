// What the Workspace Knowledge upload accepts, mirrored from the backend so the page states it
// truthfully and refuses an unusable file before it is sent:
// - backend/app/services/knowledge/ingestion/media_types.py (accepted media types),
// - backend/app/services/knowledge/ingestion/text_ingest.py (MAX_TEXT_BYTES, MAX_UPLOAD_BYTES).
// The server stays the authority: it re-checks the declared type, sniffs the bytes and bounds the size.

const MIB = 1024 * 1024;

// Parsed in the API process; MAX_TEXT_BYTES.
export const MAX_TEXT_BYTES = 8 * MIB;
// Parsed in the Docling sandbox; MAX_UPLOAD_BYTES (= MAX_OBJECT_BYTES).
export const MAX_DOCUMENT_BYTES = 32 * MIB;

export type UploadKind = "text" | "document";

export type AcceptedFormat = { extension: string; mediaType: string; kind: UploadKind; label: string };

// Every accepted extension with the media type the server expects. The browser's own `file.type` is
// not trusted: it is often empty (adoc, md) or wrong (csv as application/vnd.ms-excel).
export const ACCEPTED_FORMATS: readonly AcceptedFormat[] = [
  { extension: "txt", mediaType: "text/plain", kind: "text", label: "Plain text" },
  { extension: "md", mediaType: "text/markdown", kind: "text", label: "Markdown" },
  { extension: "markdown", mediaType: "text/markdown", kind: "text", label: "Markdown" },
  { extension: "adoc", mediaType: "text/asciidoc", kind: "text", label: "AsciiDoc" },
  { extension: "csv", mediaType: "text/csv", kind: "text", label: "CSV" },
  { extension: "json", mediaType: "application/json", kind: "text", label: "JSON" },
  { extension: "xml", mediaType: "application/xml", kind: "text", label: "XML" },
  { extension: "pdf", mediaType: "application/pdf", kind: "document", label: "PDF" },
  { extension: "html", mediaType: "text/html", kind: "document", label: "HTML" },
  { extension: "htm", mediaType: "text/html", kind: "document", label: "HTML" },
  {
    extension: "docx",
    mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    kind: "document",
    label: "Word",
  },
  {
    extension: "pptx",
    mediaType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    kind: "document",
    label: "PowerPoint",
  },
  {
    extension: "xlsx",
    mediaType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    kind: "document",
    label: "Excel",
  },
];

export type ChosenUpload = { file: File; format: AcceptedFormat };

// The file with the media type the server expects for its extension, never the browser's guess.
export function declaredUploadFile({ file, format }: ChosenUpload): File {
  return file.type === format.mediaType ? file : new File([file], file.name, { type: format.mediaType });
}

export const ACCEPT_ATTRIBUTE = ACCEPTED_FORMATS.map((format) => `.${format.extension}`).join(",");

export function maxBytesOf(kind: UploadKind): number {
  return kind === "text" ? MAX_TEXT_BYTES : MAX_DOCUMENT_BYTES;
}

export function formatBytes(bytes: number): string {
  if (bytes >= MIB) return `${(bytes / MIB).toFixed(bytes % MIB === 0 ? 0 : 1)} MB`;
  if (bytes >= 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${bytes} bytes`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export type UploadCheck =
  | { ok: true; format: AcceptedFormat }
  | { ok: false; reason: string };

// The client-side gate: a known extension and a size inside its class's bound.
export function checkUploadFile(name: string, size: number): UploadCheck {
  const format = ACCEPTED_FORMATS.find((item) => item.extension === extensionOf(name));
  if (!format) {
    return { ok: false, reason: `This file type is not accepted. Use one of: ${uniqueExtensions().join(", ")}.` };
  }
  if (size <= 0) return { ok: false, reason: "The file is empty." };
  const limit = maxBytesOf(format.kind);
  if (size > limit) {
    const group = format.kind === "text" ? "Text documents" : "PDF, Office and HTML documents";
    return { ok: false, reason: `${name} is ${formatBytes(size)}. ${group} may be up to ${formatBytes(limit)}.` };
  }
  return { ok: true, format };
}

function uniqueExtensions(): string[] {
  return ACCEPTED_FORMATS.filter((item) => item.extension !== "htm" && item.extension !== "markdown")
    .map((item) => item.extension);
}

// Human summary of the two classes, for the upload guide.
export function acceptedFormatsSummary(): { kind: UploadKind; extensions: string[]; maxBytes: number }[] {
  return (["document", "text"] as const).map((kind) => ({
    kind,
    extensions: uniqueExtensions().filter((extension) => ACCEPTED_FORMATS.some(
      (item) => item.extension === extension && item.kind === kind)),
    maxBytes: maxBytesOf(kind),
  }));
}

// What happens after an upload, in order; the last step is what makes a document searchable.
export function processingSteps(kind: UploadKind | null): string[] {
  const parse = kind === "text"
    ? "Parsed: the text is split into citable passages right away."
    : kind === "document"
      ? "Parsed: the document is converted in the isolated parser (no network); this can take a few minutes."
      : "Parsed: text files right away; PDF, Office and HTML in the isolated parser (no network).";
  return [
    "Uploaded: the original is stored unchanged as a new revision.",
    parse,
    "Indexed: the passages become searchable and citable in this workspace.",
  ];
}

// Stable source key from a file name; reusing a key adds a new revision of that source.
export function sourceKeyOf(name: string): string {
  return name
    .replace(/\.[^.]+$/, "")
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 200);
}
