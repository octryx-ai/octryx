// Guides (helpGuides.ts): short help pages on one subject, opened from page help by `guide:` links. Every guide has an
// index, every guide link opens a page that exists, pages are short and in plain words (written
// for someone doing it for the first time), and the panel keeps react-markdown's link safety for everything else.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { findGuidePage, guideContents, guideLink, parseGuidePage, readGuidePages } from "../../src/help/helpGuides.ts";

const GUIDES = new URL("../../guides/", import.meta.url).pathname;
const files = {};
for (const guide of readdirSync(GUIDES)) {
  for (const name of readdirSync(join(GUIDES, guide))) files[`/guides/${guide}/${name}`] = readFileSync(join(GUIDES, guide, name), "utf8");
}
const pages = readGuidePages(files);
const guides = [...new Set(pages.map((page) => page.guide))];

test("every guide has an index that links to each of its pages", () => {
  assert.ok(guides.includes("workflow-designer"));
  for (const guide of guides) {
    const index = findGuidePage(pages, { guide, page: "index" });
    assert.ok(index, guide);
    for (const page of guideContents(pages, guide).filter((item) => item.page !== "index"))
      assert.ok(index.body.includes(`guide:${guide}/${page.page}`), `${guide}/index links ${page.page}`);
  }
});

test("the workflow designer guide has the six pages in reading order", () => {
  assert.deepEqual(guideContents(pages, "workflow-designer").map((page) => page.page),
    ["index", "reading", "from-scratch", "conditions", "approvals", "checks", "publishing"]);
});

test("every link in a guide opens a guide page or an app page", () => {
  for (const page of pages) {
    for (const [, href] of page.body.matchAll(/\]\(([^)]+)\)/g)) {
      const ref = guideLink(href);
      if (ref) assert.ok(findGuidePage(pages, ref), `${page.guide}/${page.page}: ${href}`);
      else assert.match(href, /^(\/chat\?|https:\/\/)/, `${page.guide}/${page.page}: ${href}`);
    }
  }
});

test("guide pages are short and in plain words: no raw values, no developer notes", () => {
  for (const page of pages) {
    const words = page.body.replace(/\([^)]*\)/g, "").match(/[A-Za-z0-9']+/g)?.length ?? 0;
    assert.ok(words <= 260, `${page.guide}/${page.page}: ${words} words`);
    assert.doesNotMatch(page.body, /`|[a-z]+_[a-z_]+|OCTRYX_|#\d{3,}|endpoint|config\./i, `${page.guide}/${page.page}`);
    assert.ok(page.title && page.title !== page.page, `${page.guide}/${page.page} has a title`);
  }
});

test("parsing: title and order from front matter, CRLF, foreign paths and links", () => {
  assert.deepEqual(parseGuidePage("/guides/a/b.md", "---\r\ntitle: B\r\norder: 3\r\n---\r\nText"),
    { guide: "a", page: "b", title: "B", order: 3, body: "Text" });
  assert.equal(parseGuidePage("/guides/a/index.md", "Text").order, 0);
  assert.equal(parseGuidePage("/guides/a/b.md", "---\ntitle: 'Checks: \"Done when\"'\n---\nText").title, 'Checks: "Done when"');
  assert.equal(parseGuidePage("/help/a/b.md", "Text"), null);
  assert.deepEqual(guideLink("guide:workflow-designer/conditions"), { guide: "workflow-designer", page: "conditions" });
  assert.equal(guideLink("javascript:alert(1)"), null);
  assert.equal(guideLink("/chat?area=workflows"), null);
});

test("the help panel opens guide links inside the panel and keeps link safety for the rest", () => {
  const drawer = readFileSync(new URL("../../src/chat/PageHelpDrawer.tsx", import.meta.url), "utf8");
  assert.match(drawer, /urlTransform=\{\(url\) => \(guideLink\(url\) \? url : defaultUrlTransform\(url\)\)\}/);
  assert.match(drawer, /Back to the page help/);
});
