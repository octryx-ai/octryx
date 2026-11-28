// Pure functions only, so unit tests can read the guide files from disk.

export type GuidePage = { guide: string; page: string; title: string; order: number; body: string };
export type GuideRef = { guide: string; page: string };

const FRONTMATTER = /^---\n([\s\S]*?)\n---\n?/;
const GUIDE_PATH = /(?:^|\/)guides\/([a-z0-9-]+)\/([a-z0-9-]+)\.md$/;
const GUIDE_LINK = /^guide:([a-z0-9-]+)\/([a-z0-9-]+)$/;

export function parseGuidePage(path: string, raw: string): GuidePage | null {
  const match = GUIDE_PATH.exec(path.replace(/\\/g, "/"));
  if (!match) return null;
  const text = raw.replace(/\r\n/g, "\n");
  const front = FRONTMATTER.exec(text);
  const field = (name: string) => front?.[1].split("\n").find((line) => line.startsWith(`${name}:`))?.slice(name.length + 1).trim()
    .replace(/^(['"])(.*)\1$/, "$2");
  const order = Number(field("order"));
  return {
    guide: match[1], page: match[2], title: field("title") || match[2],
    order: Number.isFinite(order) ? order : match[2] === "index" ? 0 : 99,
    body: (front ? text.slice(front[0].length) : text).trim(),
  };
}

export function readGuidePages(files: Record<string, string>): GuidePage[] {
  return Object.entries(files)
    .map(([path, raw]) => parseGuidePage(path, raw))
    .filter((page): page is GuidePage => page !== null)
    .sort((a, b) => a.guide.localeCompare(b.guide) || a.order - b.order || a.page.localeCompare(b.page));
}

export function guideLink(href: string): GuideRef | null {
  const match = GUIDE_LINK.exec(href.trim());
  return match ? { guide: match[1], page: match[2] } : null;
}

export function findGuidePage(pages: GuidePage[], ref: GuideRef): GuidePage | null {
  return pages.find((page) => page.guide === ref.guide && page.page === ref.page) ?? null;
}

export function guideContents(pages: GuidePage[], guide: string): GuidePage[] {
  return pages.filter((page) => page.guide === guide);
}
