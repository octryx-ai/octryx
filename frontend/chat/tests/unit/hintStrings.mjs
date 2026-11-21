// The placeholder, hint, help and example strings of a source file (attributes and object keys), with their
// line: shared by the neutral-placeholder and connector-card guards (delivery 5).

const ATTRIBUTES = "placeholder|hint|help|helpText|example";
const QUOTED = /"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g;

function literalsIn(expression) {
  return [...expression.matchAll(QUOTED)].map((match) => match[1] ?? match[2] ?? match[3] ?? "");
}

// The text of a JSX expression `{ ... }` starting at `open` (balanced braces, bounded).
function braced(source, open) {
  let depth = 0;
  for (let index = open; index < Math.min(source.length, open + 2000); index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, index);
    }
  }
  return source.slice(open + 1, open + 2000);
}

// Every string a placeholder/hint/help/example attribute or object key can show, with its line.
export function hintStrings(source) {
  const found = [];
  const line = (offset) => source.slice(0, offset).split("\n").length;
  const attribute = new RegExp(`\\b(?:${ATTRIBUTES})\\s*=\\s*(["'{])`, "g");
  for (const match of source.matchAll(attribute)) {
    const start = match.index + match[0].length - 1;
    if (match[1] === "{") {
      for (const text of literalsIn(braced(source, start))) found.push({ text, line: line(match.index) });
    } else {
      const end = source.indexOf(match[1], start + 1);
      found.push({ text: source.slice(start + 1, end), line: line(match.index) });
    }
  }
  const key = new RegExp(`\\b(?:${ATTRIBUTES})\\s*:\\s*("(?:[^"\\\\]|\\\\.)*"|'(?:[^'\\\\]|\\\\.)*'|\`(?:[^\`\\\\]|\\\\.)*\`)`, "g");
  for (const match of source.matchAll(key)) {
    for (const text of literalsIn(match[1])) found.push({ text, line: line(match.index) });
  }
  return found;
}

