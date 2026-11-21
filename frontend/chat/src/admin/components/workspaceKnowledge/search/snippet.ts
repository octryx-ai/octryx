// Knowledge → Search: a hit's excerpt is not only the passage's headings ("Onboarding of new customers /
// Deliveries…"). The excerpt is the part of the passage where the question's words occur, starting at the
// line that holds the first of them, with the words marked; without a match it is the body after the headings.

const STOP_WORDS = new Set([
  "the", "and", "for", "are", "was", "were", "with", "that", "this", "what", "which", "who", "how", "when", "where",
  "why", "does", "did", "has", "have", "had", "can", "may", "our", "your", "their", "from", "into", "about", "there",
]);

export const EXCERPT_CHARS = 280;

/** The words of a question worth finding in a passage: three letters or more, no stop words, each once. */
export function queryTerms(query: string): string[] {
  const words = query.toLowerCase().match(/[\p{L}\p{N}][\p{L}\p{N}._-]*/gu) ?? [];
  return [...new Set(words.map((word) => word.replace(/[._-]+$/, "")).filter((word) => word.length >= 3 && !STOP_WORDS.has(word)))];
}

const isHeading = (line: string) => /^\s{0,3}#{1,6}\s/.test(line);
const plain = (line: string) => line.replace(/^\s{0,3}#{1,6}\s+/, "").toLowerCase();

/** Whether a passage holds nothing but headings and blank lines. */
export function isHeadingOnly(text: string): boolean {
  const lines = text.split("\n").filter((line) => line.trim());
  return lines.length > 0 && lines.every(isHeading);
}

function cut(lines: string[], from: number, limit: number): string {
  const kept: string[] = [];
  let size = 0;
  for (const line of lines.slice(from)) {
    if (size && size + line.length > limit) break;
    kept.push(line);
    size += line.length + 1;
  }
  const body = kept.join("\n").trim();
  return body.length > limit ? `${body.slice(0, limit).replace(/\s+\S*$/, "")}…` : body;
}

/**
 * The excerpt of a passage for a question: from the first body line with one of its words (or the heading right
 * above that line), else from the first body line; the whole passage when it is short or only headings.
 */
export function excerptFor(text: string, terms: string[], limit = EXCERPT_CHARS): string {
  const trimmed = text.trim();
  const lines = trimmed.split("\n");
  if (trimmed.length <= limit || isHeadingOnly(trimmed)) return trimmed;
  const body = lines.map((line, index) => ({ line, index })).filter((entry) => entry.line.trim() && !isHeading(entry.line));
  const match = terms.length ? body.find((entry) => terms.some((term) => plain(entry.line).includes(term))) : undefined;
  const start = match ?? body[0];
  if (!start) return cut(lines, 0, limit);
  // Keep the heading the matched line belongs to, so the excerpt still says where it is.
  let above = start.index;
  for (let index = start.index - 1; index >= 0 && !lines[index].trim(); index -= 1) above = index;
  above = above > 0 && isHeading(lines[above - 1]) ? above - 1 : start.index;
  const excerpt = cut(lines, above, limit);
  return above > 0 ? `…\n${excerpt}` : excerpt;
}

/** `text` split into plain and marked parts (case-insensitive), for marking the question's words. */
export function markTerms(text: string, terms: string[]): { text: string; marked: boolean }[] {
  if (!terms.length || !text) return [{ text, marked: false }];
  const escaped = [...terms].sort((a, b) => b.length - a.length).map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp(`(${escaped.join("|")})`, "giu");
  return text.split(pattern).filter((part) => part !== "").map((part) => ({
    text: part, marked: terms.includes(part.toLowerCase()),
  }));
}
