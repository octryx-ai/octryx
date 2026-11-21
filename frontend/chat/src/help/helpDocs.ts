// Page help from Markdown ("help instead of hint texts"): pages carry at most one purpose sentence; what
// a page is for, what one does there and the next steps live in `frontend/chat/help/<area>/<page>.md`, read by the
// help panel and the setup guide alike. A page without its own file shows its area's `index.md`. Links in the
// Markdown use the stable routes (`/chat?area=<area>&tab=<page>`), so a new or changed help file needs no code.
// Pure functions only, so unit tests can read the Markdown files from disk.

export type HelpDoc = { area: string; page: string; title: string; body: string };

export type HelpLinkTarget = { area: string; tab: string | null; params: Record<string, string> };

const FRONTMATTER = /^---\n([\s\S]*?)\n---\n?/;
const HELP_PATH = /(?:^|\/)help\/([a-z0-9-]+)\/([a-zA-Z0-9-]+)\.md$/;

/** One help file: `help/<area>/<page>.md` with an optional `title:` front matter; null for any other path. */
export function parseHelpDoc(path: string, raw: string): HelpDoc | null {
  const match = HELP_PATH.exec(path.replace(/\\/g, "/"));
  if (!match) return null;
  const text = raw.replace(/\r\n/g, "\n");
  const front = FRONTMATTER.exec(text);
  const title = front?.[1].split("\n").find((line) => line.startsWith("title:"))?.slice(6).trim() ?? "";
  const body = (front ? text.slice(front[0].length) : text).trim();
  return { area: match[1], page: match[2], title: title || match[2], body };
}

/** All parsed help files of a `{ path: raw }` map (Vite's glob import, or files read in a test). */
export function readHelpDocs(files: Record<string, string>): HelpDoc[] {
  return Object.entries(files)
    .map(([path, raw]) => parseHelpDoc(path, raw))
    .filter((doc): doc is HelpDoc => doc !== null);
}

/** The help of one page: its own file, else its area's index, else null. */
export function resolveHelpDoc(docs: HelpDoc[], area: string, page: string | null): HelpDoc | null {
  return (
    (page ? docs.find((doc) => doc.area === area && doc.page === page) : undefined) ??
    docs.find((doc) => doc.area === area && doc.page === "index") ??
    null
  );
}

/** The page a URL shows inside an area: the admin `tab`, else `work_view`, `agents_view` or `coding_view`. */
export function helpPageFromSearch(search: string): string | null {
  try {
    const params = new URLSearchParams(search);
    return params.get("tab") || params.get("work_view") || params.get("agents_view") || params.get("coding_view") || null;
  } catch {
    return null;
  }
}

/** Where an in-app help link (`/chat?area=…&tab=…`) leads; null for an external or non-area link. */
export function helpLinkTarget(href: string): HelpLinkTarget | null {
  if (!href.startsWith("/chat?")) return null;
  const params = new URLSearchParams(href.slice("/chat?".length));
  const area = params.get("area");
  if (!area) return null;
  const tab = params.get("tab");
  const rest: Record<string, string> = {};
  params.forEach((value, key) => {
    if (key !== "area" && key !== "tab") rest[key] = value;
  });
  return { area, tab, params: rest };
}
