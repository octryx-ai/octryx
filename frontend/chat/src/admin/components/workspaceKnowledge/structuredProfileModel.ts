// The Workspace's structured-graph profile: the instance default or the Workspace's own document.
// Pure: the common lists as form fields over the JSON document, and back. The server validates the
// whole document with the same loader it builds with; this model only keeps the two views in step.

export type ProfileDocument = Record<string, unknown>;

export type FileRule = { glob: string; format: string; manual_documented: boolean };

export type ProfileForm = {
  parameterHeaders: string;
  defaultHeaders: string;
  descriptionHeaders: string;
  allowedHeaders: string;
  files: FileRule[];
  commentPrefixes: Record<string, string>;
  variantPatterns: string;
  placeholderSources: string;
  ticketPatterns: string;
};

export const FILE_FORMATS = ["ini", "properties", "yaml"] as const;

// One list per line in the form; the path is where the list lives in the document.
export const LINE_LISTS: Array<{ field: keyof ProfileForm; label: string; path: string[]; hint: string }> = [
  { field: "parameterHeaders", label: "Parameter name headers", path: ["manual", "parameter_name_headers"],
    hint: "e.g. Parameter, Setting" },
  { field: "defaultHeaders", label: "Default value headers", path: ["manual", "default_headers"],
    hint: "e.g. Default, Default value" },
  { field: "descriptionHeaders", label: "Description headers", path: ["manual", "description_headers"],
    hint: "e.g. Description, Details" },
  { field: "allowedHeaders", label: "Allowed value headers", path: ["manual", "allowed_headers"],
    hint: "e.g. Possible values, Allowed values" },
  { field: "variantPatterns", label: "Variant file patterns", path: ["configuration", "variant_patterns"],
    hint: "regular expressions with the groups base and variant" },
  { field: "placeholderSources", label: "Placeholder source files", path: ["configuration", "placeholder_sources"],
    hint: "file-name globs, e.g. *_config.properties" },
];

const FILES_PATH = ["layers", "configuration", "files"];
const COMMENTS_PATH = ["configuration", "comment_prefixes"];
const TICKETS_PATH = ["operations", "ticket_patterns"];

export function getAt(document: unknown, path: string[]): unknown {
  let current: unknown = document;
  for (const key of path) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

export function setAt(document: ProfileDocument, path: string[], value: unknown): ProfileDocument {
  const [head, ...rest] = path;
  const current = document[head];
  const child = current && typeof current === "object" && !Array.isArray(current) ? current as ProfileDocument : {};
  return { ...document, [head]: rest.length ? setAt(child, rest, value) : value };
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function linesToList(text: string): string[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean);
}

// "Incident = \bINC[0-9]{7}\b" per line; the first " = " separates the node type from its pattern.
export function ticketPatternsToLines(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  return Object.entries(value as Record<string, unknown>)
    .filter(([, pattern]) => typeof pattern === "string")
    .map(([name, pattern]) => `${name} = ${pattern}`).join("\n");
}

export function linesToTicketPatterns(text: string): { value: Record<string, string>; error: string | null } {
  const value: Record<string, string> = {};
  for (const line of linesToList(text)) {
    const at = line.indexOf(" = ");
    if (at <= 0 || !line.slice(at + 3).trim()) {
      return { value, error: `Ticket pattern line "${line}" needs the form "Type = pattern".` };
    }
    const name = line.slice(0, at).trim();
    if (name in value) return { value, error: `Ticket type ${name} is listed twice.` };
    value[name] = line.slice(at + 3).trim();
  }
  return { value, error: null };
}

export function formOf(document: ProfileDocument): ProfileForm {
  const comments = getAt(document, COMMENTS_PATH);
  const files = getAt(document, FILES_PATH);
  const form = {
    files: Array.isArray(files)
      ? files.filter((item) => item && typeof item === "object").map((item) => ({
        glob: String((item as FileRule).glob ?? ""), format: String((item as FileRule).format ?? "ini"),
        manual_documented: (item as FileRule).manual_documented === true,
      }))
      : [],
    commentPrefixes: Object.fromEntries(FILE_FORMATS.map((format) => [
      format, strings(getAt(comments, [format])).join(" "),
    ])),
    ticketPatterns: ticketPatternsToLines(getAt(document, TICKETS_PATH)),
  } as ProfileForm;
  for (const list of LINE_LISTS) (form[list.field] as string) = strings(getAt(document, list.path)).join("\n");
  return form;
}

// The document with the form's lists written in; everything the form does not show is kept as is.
export function applyForm(document: ProfileDocument, form: ProfileForm): { document: ProfileDocument; error: string | null } {
  let next = document;
  for (const list of LINE_LISTS) next = setAt(next, list.path, linesToList(form[list.field] as string));
  next = setAt(next, FILES_PATH, form.files
    .filter((rule) => rule.glob.trim())
    .map((rule) => ({ glob: rule.glob.trim(), format: rule.format, manual_documented: rule.manual_documented })));
  next = setAt(next, COMMENTS_PATH, Object.fromEntries(FILE_FORMATS.map((format) => [
    format, (form.commentPrefixes[format] ?? "").split(/\s+/).filter(Boolean),
  ])));
  const tickets = linesToTicketPatterns(form.ticketPatterns);
  next = setAt(next, TICKETS_PATH, tickets.value);
  return { document: next, error: tickets.error };
}

export function parseDocument(text: string): { document: ProfileDocument | null; error: string | null } {
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { document: null, error: "The profile must be a JSON object." };
    }
    return { document: value as ProfileDocument, error: null };
  } catch (error) {
    return { document: null, error: `Not valid JSON: ${error instanceof Error ? error.message : String(error)}` };
  }
}

export function formatDocument(document: ProfileDocument): string {
  return JSON.stringify(document, null, 2);
}

export const SAVE_CONFIRMATION = "Saving the profile re-extracts every layer of this workspace's structured graph "
  + "(manual, configuration, operations). Until the build completes, the graph and the Handbook vs. reality "
  + "report show only what the new profile has extracted. Continue?";

export const RESET_CONFIRMATION = "Return to the instance default profile? This also re-extracts every layer of "
  + "this workspace's structured graph. Continue?";
