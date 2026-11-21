export type AnswerSource = { url: string; label: string; statement: string };
export type SourceOverview = { sources: AnswerSource[]; excluded: number; truncated: boolean };
const MAX_LINKS = 100;
const SECRET_QUERY = /^(?:access[_-]?token|token|api[_-]?key|authorization|password|secret|signature|x-amz-.+|x-goog-.+)$/i;

export function safeSourceUrl(raw: string, origin: string): string | null {
  if (!raw || raw.length > 2048) return null;
  try {
    const url = new URL(raw, origin);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    if ([...url.searchParams.keys()].some((key) => SECRET_QUERY.test(key))) return null;
    if (!/^https?:\/\//i.test(raw) && !(url.origin === origin &&
      /^\/api\/v1\/workspaces\/[^/]+\/knowledge\//.test(url.pathname))) return null;
    return url.href;
  } catch { return null; }
}

// Inspect only this answer's rendered Markdown; traces and other turns are outside this boundary.
export function collectAnswerSources(article: Element | null, origin: string): SourceOverview {
  const links = article?.querySelectorAll<HTMLAnchorElement>(".message-markdown a[href]") ?? [];
  const sources: AnswerSource[] = [];
  const seen = new Set<string>();
  let excluded = 0;
  for (const link of Array.from(links).slice(0, MAX_LINKS)) {
    const url = safeSourceUrl(link.getAttribute("href") ?? "", origin);
    if (!url) { excluded++; continue; }
    // One source per address: the same URL cited again under another label is still one source,
    // listed with its first label and statement (distinct anchors such as #L10 stay distinct URLs).
    if (seen.has(url)) continue;
    seen.add(url);
    const label = (link.textContent?.trim() || new URL(url).hostname).slice(0, 300);
    const statement = (link.closest("p, li, td, th, blockquote")?.textContent ?? "").trim().slice(0, 600);
    sources.push({ url, label, statement });
  }
  return { sources, excluded, truncated: links.length > MAX_LINKS };
}

export type SourceKind = "knowledge" | "web";

// A short, human location for the compact list: the kind of source and where
// it lives, never the full query string.
export function describeSource(url: string, origin: string): { kind: SourceKind; location: string } {
  try {
    const parsed = new URL(url, origin);
    if (parsed.origin === origin && parsed.pathname.startsWith("/api/v1/workspaces/")) {
      return { kind: "knowledge", location: "Workspace knowledge" };
    }
    const path = parsed.pathname.length > 48 ? `${parsed.pathname.slice(0, 47)}…` : parsed.pathname;
    return { kind: "web", location: `${parsed.hostname}${path === "/" ? "" : path}` };
  } catch {
    return { kind: "web", location: url.slice(0, 60) };
  }
}

// First sentence-ish preview of the cited statement for the compact list.
export function previewStatement(statement: string, max = 180): string {
  const text = statement.replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

// A source marker in an answer: a link whose whole text is a number such as "1" or "[2]".
const MARKER = /^\[?\s*\d{1,3}\s*\]?$/;

export function isCitationMarker(text: string | null | undefined): boolean {
  return MARKER.test(String(text ?? "").trim());
}

/** The source a clicked marker opens in the side panel; null for any other link, which keeps opening in a new tab. */
export function citationMarkerTarget(link: { textContent: string | null; getAttribute(name: string): string | null },
  origin: string): string | null {
  if (!isCitationMarker(link.textContent)) return null;
  return safeSourceUrl(link.getAttribute("href") ?? "", origin);
}
