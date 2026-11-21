// Jira wiki markup of a description or comment, read into blocks and inline pieces (`{code:java}`,
// `{+}…{+}` and `_…_` are never shown raw). Pure and safe: the result is data that React renders as text, never HTML. Only
// what Jira descriptions use is understood; anything else stays as written.

export type WikiInline =
  | { kind: "text"; text: string }
  | { kind: "strong" | "em" | "underline" | "strike"; children: WikiInline[] }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

export type WikiBlock =
  | { kind: "code"; language: string; text: string }
  | { kind: "heading"; level: number; content: WikiInline[] }
  | { kind: "list"; ordered: boolean; items: WikiInline[][] }
  | { kind: "quote"; lines: WikiInline[][] }
  | { kind: "paragraph"; lines: WikiInline[][] };

const CODE_OPEN = /^\s*\{(code|noformat)(?::([^}]*))?\}\s*(.*)$/;
const HEADING = /^\s*h([1-6])\.\s+(.*)$/;
const LIST_ITEM = /^\s*([*#-]+)\s+(.*)$/;
const QUOTE_LINE = /^\s*bq\.\s+(.*)$/;

/** A link only when it is an absolute http(s) or mailto address; anything else stays text. */
export function safeHref(value: string): string | null {
  const href = value.trim();
  return /^(https?:\/\/|mailto:)[^\s"'<>]+$/i.test(href) ? href : null;
}

// Inline markup in order of precedence: {{code}}, [text|url] / [url], {+}underline{+} and +underline+, *strong*,
// _em_, -strike-. A marker only counts at a word boundary, so snake_case and "a - b" stay text.
const INLINE = new RegExp(
  [
    String.raw`\{\{(?<code>.+?)\}\}`,
    String.raw`\[(?<link>[^\]\n]+)\]`,
    String.raw`\{\+\}(?<u1>.+?)\{\+\}`,
    String.raw`(?<![\w+])\+(?<u2>[^\s+](?:[^+\n]*[^\s+])?)\+(?![\w+])`,
    String.raw`(?<![\w*])\*(?<strong>[^\s*](?:[^*\n]*[^\s*])?)\*(?![\w*])`,
    String.raw`(?<![\w_])_(?<em>[^\s_](?:[^_\n]*[^\s_])?)_(?![\w_])`,
    String.raw`(?<![\w-])-(?<strike>[^\s-](?:[^-\n]*[^\s-])?)-(?![\w-])`,
  ].join("|"),
  "g",
);

export function wikiInline(text: string): WikiInline[] {
  const out: WikiInline[] = [];
  let last = 0;
  // exec in a loop, not matchAll: the result stays an array-free loop for every compile target.
  const pattern = new RegExp(INLINE.source, "g");
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    const groups = match.groups ?? {};
    const index = match.index ?? 0;
    if (index > last) out.push({ kind: "text", text: text.slice(last, index) });
    last = index + match[0].length;
    if (groups.code !== undefined) out.push({ kind: "code", text: groups.code });
    else if (groups.link !== undefined) {
      const [label, target] = groups.link.includes("|") ? groups.link.split("|", 2) : [groups.link, groups.link];
      const href = safeHref(target);
      out.push(href ? { kind: "link", text: label.trim() || href, href } : { kind: "text", text: match[0] });
    } else if (groups.u1 !== undefined || groups.u2 !== undefined) {
      out.push({ kind: "underline", children: wikiInline(groups.u1 ?? groups.u2) });
    } else if (groups.strong !== undefined) out.push({ kind: "strong", children: wikiInline(groups.strong) });
    else if (groups.em !== undefined) out.push({ kind: "em", children: wikiInline(groups.em) });
    else if (groups.strike !== undefined) out.push({ kind: "strike", children: wikiInline(groups.strike) });
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** The blocks of a Jira wiki text: code and noformat, headings, lists, quotes and paragraphs. */
export function wikiBlocks(text: string | null | undefined): WikiBlock[] {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: WikiBlock[] = [];
  let paragraph: WikiInline[][] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", lines: paragraph });
    paragraph = [];
  };
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const code = CODE_OPEN.exec(line);
    if (code) {
      flush();
      const tag = code[1];
      const language = tag === "code" ? (code[2] || "").split("|")[0].trim() : "";
      const body: string[] = [];
      let rest = code[3];
      const close = `{${tag}}`;
      for (;;) {
        const end = rest.indexOf(close);
        if (end >= 0) {
          if (rest.slice(0, end).trim()) body.push(rest.slice(0, end));
          break;
        }
        if (rest.length || body.length) body.push(rest);
        index += 1;
        if (index >= lines.length) break;
        rest = lines[index];
      }
      blocks.push({ kind: "code", language, text: body.join("\n").replace(/^\n+|\s+$/g, "") });
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: "heading", level: Number(heading[1]), content: wikiInline(heading[2].trim()) });
      continue;
    }
    const item = LIST_ITEM.exec(line);
    // "- " starts a list only at the start of a block of items, so a dash inside prose stays prose.
    if (item && (item[1] !== "-" || !paragraph.length)) {
      flush();
      const ordered = item[1].endsWith("#");
      const previous = blocks[blocks.length - 1];
      if (previous?.kind === "list" && previous.ordered === ordered) previous.items.push(wikiInline(item[2].trim()));
      else blocks.push({ kind: "list", ordered, items: [wikiInline(item[2].trim())] });
      continue;
    }
    const quote = QUOTE_LINE.exec(line);
    if (quote) {
      flush();
      blocks.push({ kind: "quote", lines: [wikiInline(quote[1].trim())] });
      continue;
    }
    paragraph.push(wikiInline(line.trimEnd()));
  }
  flush();
  return blocks;
}
