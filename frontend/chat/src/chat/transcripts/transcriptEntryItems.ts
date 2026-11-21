// One transcript line as display items (user, assistant, thinking, tool call/result, system) and byte formatting.
import { count, isRecord, text } from "./transcriptValues";

// ---- Entry → display items ----------------------------------------------------------------------------------------

export type DisplayKind = "user" | "assistant" | "thinking" | "tool_use" | "tool_result" | "system" | "other" | "omitted" | "unparsed";

export type DisplayItem = {
  key: string;
  line: number;
  kind: DisplayKind;
  // The block's name ("You", "Claude", "Bash", "Tool result").
  label: string;
  // One short line next to the label while collapsed (a command, a path, a subtype).
  summary: string;
  // The block's content; plain text, shown as is.
  body: string;
  collapsed: boolean;
  error: boolean;
  timestamp: string | null;
  // Assistant text may be shown as Markdown; everything else is plain text.
  markdown: boolean;
};

const COLLAPSED: Record<DisplayKind, boolean> = {
  user: false, assistant: false, thinking: true, tool_use: true, tool_result: true, system: true, other: true,
  omitted: false, unparsed: true,
};

function json(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return String(value);
  }
}

function oneLine(value: string, max = 120): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

// What a tool call is about, in one line: the command, the path, the pattern or the description it was given.
function toolSummary(input: unknown): string {
  if (!isRecord(input)) return "";
  for (const key of ["command", "file_path", "path", "pattern", "url", "query", "description", "prompt"]) {
    const value = text(input[key]);
    if (value) return oneLine(value);
  }
  return "";
}

// A tool result's content: a string, or a list of {type: "text", text} parts (images are named, not shown).
function resultText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content === undefined || content === null ? "" : json(content);
  return content.map((part) => {
    if (!isRecord(part)) return json(part);
    if (part.type === "text") return text(part.text);
    if (part.type === "image") return "[image]";
    return json(part);
  }).join("\n");
}

// The structured toolUseResult: stdout/stderr or a file's content are shown as text, anything else as JSON.
function toolUseResultText(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (!isRecord(value)) return json(value);
  if (typeof value.stdout === "string" || typeof value.stderr === "string") {
    return [text(value.stdout), text(value.stderr) ? `stderr:\n${text(value.stderr)}` : ""].filter(Boolean).join("\n\n");
  }
  if (isRecord(value.file) && typeof value.file.content === "string") {
    const path = text(value.file.filePath);
    return path ? `${path}\n\n${value.file.content}` : value.file.content;
  }
  return json(value);
}

function item(line: number, index: number, kind: DisplayKind, fields: Partial<DisplayItem> & { label: string }, timestamp: string | null): DisplayItem {
  return {
    key: `${line}-${index}`, line, kind, summary: "", body: "", collapsed: COLLAPSED[kind], error: false, timestamp,
    markdown: false, ...fields,
  };
}

/** One transcript line as the blocks the view shows, in their order. */
export function entryItems(line: number, entry: unknown): DisplayItem[] {
  if (!isRecord(entry)) {
    return [item(line, 0, "unparsed", { label: "Unreadable line", summary: "Line could not be read", body: json(entry) }, null)];
  }
  const type = text(entry.type);
  const timestamp = text(entry.timestamp) || null;
  if (type === "octryx_omitted") {
    const bytes = count(entry.bytes);
    return [item(line, 0, "omitted", {
      label: "Line too large, not stored",
      summary: bytes !== null ? formatBytes(bytes) : "",
    }, timestamp)];
  }
  if (type === "octryx_unparsed") {
    return [item(line, 0, "unparsed", { label: "Line could not be read", body: text(entry.text) }, timestamp)];
  }
  const message = isRecord(entry.message) ? entry.message : null;
  if (type === "user" && message) {
    const content = message.content;
    if (typeof content === "string") return [item(line, 0, "user", { label: "You", body: content }, timestamp)];
    if (Array.isArray(content)) {
      const extra = toolUseResultText(entry.toolUseResult);
      const items = content.map((part, index) => {
        if (isRecord(part) && part.type === "tool_result") {
          const body = resultText(part.content);
          return item(line, index, "tool_result", {
            label: "Tool result",
            summary: oneLine(body || extra, 120),
            body: extra && extra !== body ? `${body}${body ? "\n\n" : ""}${extra}` : body,
            error: part.is_error === true,
          }, timestamp);
        }
        if (isRecord(part) && part.type === "text") return item(line, index, "user", { label: "You", body: text(part.text) }, timestamp);
        return item(line, index, "other", { label: "Message part", summary: isRecord(part) ? text(part.type) : "", body: json(part) }, timestamp);
      });
      if (items.length) return items;
    }
  }
  if (type === "assistant" && message && Array.isArray(message.content)) {
    const items = message.content.map((part, index) => {
      if (isRecord(part) && part.type === "text") {
        return item(line, index, "assistant", { label: "Claude", body: text(part.text), markdown: true }, timestamp);
      }
      if (isRecord(part) && part.type === "thinking") {
        const body = text(part.thinking);
        return item(line, index, "thinking", { label: "Thinking", summary: oneLine(body, 100), body }, timestamp);
      }
      if (isRecord(part) && part.type === "tool_use") {
        return item(line, index, "tool_use", {
          label: text(part.name) || "Tool call", summary: toolSummary(part.input), body: json(part.input),
        }, timestamp);
      }
      return item(line, index, "other", { label: "Message part", summary: isRecord(part) ? text(part.type) : "", body: json(part) }, timestamp);
    });
    if (items.length) return items;
  }
  if (type === "system") {
    return [item(line, 0, "system", {
      label: "System", summary: humanize(text(entry.subtype)) || oneLine(text(entry.content), 100), body: json(entry),
    }, timestamp)];
  }
  return [item(line, 0, "other", {
    label: humanize(type) || "Entry", summary: type === "summary" ? oneLine(text(entry.summary), 100) : "", body: json(entry),
  }, timestamp)];
}

function humanize(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
