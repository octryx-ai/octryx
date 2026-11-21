import { CEDAR_KEYWORDS } from "./cedarLanguage";

// Read-only Cedar colouring for the policy drawer and the builder preview: the same token classes
// as the Monaco language (keywords, strings, annotations, comments), as plain spans on the dark code surface.

export type CedarToken = { text: string; kind: "keyword" | "string" | "annotation" | "comment" | "plain" };

const KEYWORDS = new Set(CEDAR_KEYWORDS);

export function highlightCedar(source: string): CedarToken[] {
  const tokens: CedarToken[] = [];
  const push = (text: string, kind: CedarToken["kind"]) => {
    const last = tokens[tokens.length - 1];
    if (last && last.kind === kind && kind === "plain") last.text += text;
    else if (text) tokens.push({ text, kind });
  };
  let index = 0;
  while (index < source.length) {
    const rest = source.slice(index);
    const comment = /^\/\/[^\n]*/.exec(rest);
    const string = /^"(?:[^"\\]|\\.)*"?/.exec(rest);
    const annotation = /^@[A-Za-z_]\w*/.exec(rest);
    const word = /^[A-Za-z_]\w*/.exec(rest);
    if (comment) { push(comment[0], "comment"); index += comment[0].length; }
    else if (rest.startsWith('"') && string) { push(string[0], "string"); index += string[0].length; }
    else if (annotation) { push(annotation[0], "annotation"); index += annotation[0].length; }
    else if (word) { push(word[0], KEYWORDS.has(word[0]) ? "keyword" : "plain"); index += word[0].length; }
    else { push(source[index], "plain"); index += 1; }
  }
  return tokens;
}
