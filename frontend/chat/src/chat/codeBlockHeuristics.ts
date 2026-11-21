// How a code block reads: its language, and whether it is a short reference list or compact technical output.

export function extractLanguage(className?: string) {
  const match = /language-([\w-]+)/.exec(className || "");
  return match?.[1] || "text";
}

export function normalizeCodeLines(value: string) {
  return value
    .trim()
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function isMarkdownLikeShortText(line: string) {
  return /^([*-]\s|\d+\.\s|#{1,6}\s|>\s)/.test(line);
}

function isCodeLikeLine(line: string) {
  return (
    /[{}[\];]/.test(line) ||
    /\b(function|const|let|var|class|return|import|export|SELECT|INSERT|UPDATE|DELETE)\b/.test(
      line,
    ) ||
    /(=>|::|&&|\|\||===|!==)/.test(line)
  );
}

export function isTechnicalToken(line: string) {
  const isPathLike =
    /^(\/|\.\/|\.\.\/|[A-Za-z]:\\)/.test(line) &&
    !/\s{2,}/.test(line) &&
    line.length <= 320;
  return (
    isPathLike ||
    /^[a-f0-9]{7,64}$/i.test(line) ||
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      line,
    ) ||
    /^[A-Za-z0-9][A-Za-z0-9._:/-]{5,320}$/.test(line)
  );
}

export function extractReferenceTitle(line: string) {
  const normalized = line.trim();
  const pathSegments = normalized.split(/[\\/]/).filter(Boolean);
  const lastSegment = pathSegments.at(-1);
  if (lastSegment) {
    return lastSegment;
  }
  try {
    const url = new URL(normalized);
    return url.hostname || normalized;
  } catch {
    return normalized;
  }
}

export function referenceKindLabel(line: string) {
  try {
    const url = new URL(line.trim());
    if (url.protocol === "http:" || url.protocol === "https:") {
      return "URL";
    }
    if (url.protocol === "file:") {
      return "FILE";
    }
  } catch {
    // fall through to path-like default
  }
  return "PATH";
}

function looksLikeReferencePath(line: string) {
  const trimmed = line.trim();
  if (!trimmed || /\s{2,}/.test(trimmed)) {
    return false;
  }
  // A file path needs a file name with an extension; a bare route such as
  // "/owners" stays ordinary code, never a large "PATH" card.
  if (/^(\/|\.\/|\.\.\/|[A-Za-z]:\\)/.test(trimmed)) {
    const lastSegment = trimmed.split(/[\\/]/).filter(Boolean).at(-1) ?? "";
    return /\.[A-Za-z0-9]{1,8}$/.test(lastSegment);
  }
  try {
    const url = new URL(trimmed);
    return (
      url.protocol === "http:" ||
      url.protocol === "https:" ||
      url.protocol === "file:"
    );
  } catch {
    return false;
  }
}

function looksLikeCompactTechnicalOutput(lines: string[]) {
  if (!lines.length || lines.length > 3) {
    return false;
  }
  const joined = lines.join(" ");
  if (joined.length > 360) {
    return false;
  }
  if (
    lines.some((line) => isMarkdownLikeShortText(line) || isCodeLikeLine(line))
  ) {
    return false;
  }
  return lines.every(
    (line) =>
      line.length <= 120 && (isTechnicalToken(line) || line.length <= 96),
  );
}

export function shouldRenderReferenceList(language: string, value: string) {
  if (!["text", "txt", "plaintext"].includes(language)) {
    return false;
  }
  const lines = normalizeCodeLines(value);
  if (!lines.length || lines.length > 6) {
    return false;
  }
  return lines.every((line) => looksLikeReferencePath(line));
}

export function shouldRenderCompactCode(language: string, value: string) {
  if (!["text", "txt", "plaintext"].includes(language)) {
    return false;
  }
  const lines = normalizeCodeLines(value);
  if (!lines.length) {
    return false;
  }
  return looksLikeCompactTechnicalOutput(lines);
}
