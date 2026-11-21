// Page help from Markdown: every area has help/<area>/index.md, a page file wins over its area index,
// every in-app link targets a page that exists, and the panel opens only when asked for (never by itself).
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { isAdminAreaKey, listAdminAreaTabRefs, resolveAdminAreaForTab } from "../../src/admin/config/adminPanelAreas.ts";
import { helpLinkTarget, helpPageFromSearch, parseHelpDoc, readHelpDocs, resolveHelpDoc } from "../../src/help/helpDocs.ts";
import { findGuidePage, guideLink, readGuidePages } from "../../src/help/helpGuides.ts";
import { AREA_TAB_EVENT, writeAreaTabToUrl } from "../../src/chat/areaNavigation.ts";

const HELP = new URL("../../help/", import.meta.url).pathname;
const files = {};
for (const area of readdirSync(HELP)) {
  for (const name of readdirSync(join(HELP, area))) files[`/help/${area}/${name}`] = readFileSync(join(HELP, area, name), "utf8");
}
const docs = readHelpDocs(files);
const GUIDES = new URL("../../guides/", import.meta.url).pathname;
const guideFiles = {};
for (const guide of readdirSync(GUIDES)) {
  for (const name of readdirSync(join(GUIDES, guide))) guideFiles[`/guides/${guide}/${name}`] = readFileSync(join(GUIDES, guide, name), "utf8");
}
const guidePages = readGuidePages(guideFiles);
const AREAS = ["chat", "knowledge", "work", "coding", "agents", "workflows", "admin", "operations", "personal", "setup"];
// Link targets: the areas plus the Setup guide's own area (`help`, whose files are help/setup/*.md).
const LINK_AREAS = [...AREAS, "help"];
const NAV = {
  setup: ["workspace", "connectors", "sources", "models", "sso", "roles", "agents"],
  work: ["board", "changePlans", "intake", "writeback"],
  agents: ["clients", "install", "board", "claims", "classification", "policy"],
  coding: ["sessions", "repositories", "pipelines", "rules"],
  personal: ["notifications"],
};

test("every area has an index with a title and text", () => {
  for (const area of AREAS) {
    const doc = resolveHelpDoc(docs, area, null);
    assert.ok(doc, area);
    assert.equal(doc.page, "index", area);
    assert.ok(doc.title && doc.title !== "index", area);
    assert.ok(doc.body.length > 40, area);
  }
});

test("a page's own file wins; an unknown page falls back to the area index", () => {
  assert.equal(resolveHelpDoc(docs, "work", "intake").title, "Intake");
  assert.equal(resolveHelpDoc(docs, "work", "nope").page, "index");
  assert.equal(resolveHelpDoc(docs, "unknown", null), null);
});

test("every page file belongs to a real page of its area", () => {
  for (const doc of docs) {
    if (doc.page === "index") continue;
    if (isAdminAreaKey(doc.area)) {
      assert.ok(listAdminAreaTabRefs(doc.area).some((ref) => ref.id === doc.page), `${doc.area}/${doc.page}.md`);
    } else {
      assert.ok(NAV[doc.area]?.includes(doc.page), `${doc.area}/${doc.page}.md`);
    }
  }
});

test("every in-app link opens a page that exists in the named area", () => {
  for (const doc of docs) {
    for (const [, href] of doc.body.matchAll(/\]\(([^)]+)\)/g)) {
      const guide = guideLink(href);
      if (guide) {
        assert.ok(findGuidePage(guidePages, guide), `${doc.area}/${doc.page}: ${href} opens no guide page`);
        continue;
      }
      const target = helpLinkTarget(href);
      assert.ok(target || /^https:\/\//.test(href), `${doc.area}/${doc.page}: ${href}`);
      if (!target) continue;
      assert.ok(LINK_AREAS.includes(target.area), `${doc.area}/${doc.page}: ${href}`);
      if (target.tab) {
        assert.ok(isAdminAreaKey(target.area), href);
        assert.equal(resolveAdminAreaForTab(target.tab), target.area, href);
      }
      if (target.params.work_view) assert.ok(NAV.work.includes(target.params.work_view), href);
      if (target.params.coding_view) assert.ok(NAV.coding.includes(target.params.coding_view), href);
      if (target.params.agents_view) assert.ok(NAV.agents.includes(target.params.agents_view), href);
    }
  }
});

test("every help page is short: purpose, what you do, next steps as links only", () => {
  for (const doc of docs) {
    const sections = doc.body.split(/\n### /);
    const names = sections.slice(1).map((section) => section.split("\n")[0]);
    assert.ok(names.includes("Next steps"), `${doc.area}/${doc.page} has Next steps`);
    const next = sections.find((section) => section.startsWith("Next steps")).split("\n").slice(1).filter((line) => line.trim());
    assert.ok(next.length >= 1 && next.length <= 5, `${doc.area}/${doc.page}: 1–5 next steps`);
    for (const line of next) assert.match(line, /^- \[[^\]]+\]\(\/chat\?[^)]+\)$/, `${doc.area}/${doc.page}: "${line}" must be one link`);
    const main = sections.slice(0, names.indexOf("Next steps") + 2).join(" ").replace(/\([^)]*\)/g, "");
    const words = main.match(/[A-Za-z0-9']+/g)?.length ?? 0;
    assert.ok(words <= 130, `${doc.area}/${doc.page}: ${words} words before the details`);
  }
});

test("a link always looks the same: a table cell is either one whole link or plain text", () => {
  for (const doc of docs) {
    for (const row of doc.body.split("\n").filter((line) => line.startsWith("|") && !/^\|[-| ]+\|$/.test(line))) {
      for (const cell of row.split("|").slice(1, -1).map((part) => part.trim())) {
        if (!cell.includes("](")) continue;
        assert.match(cell, /^\[[^\]]+\]\([^)]+\)$/, `${doc.area}/${doc.page}: "${cell}" mixes link and text`);
      }
    }
  }
});

test("help text carries no developer notes", () => {
  for (const doc of docs) {
    assert.doesNotMatch(doc.body, /OCTRYX_|#\d{3,}|WP 20\d\d|renamed from|endpoint/i, `${doc.area}/${doc.page}`);
  }
});

test("parsing: front matter title, CRLF, foreign paths", () => {
  assert.deepEqual(parseHelpDoc("/help/work/intake.md", "---\r\ntitle: Intake\r\n---\r\nText"), { area: "work", page: "intake", title: "Intake", body: "Text" });
  assert.equal(parseHelpDoc("/help/work/intake.md", "Text").title, "intake");
  assert.equal(parseHelpDoc("/docs/x.md", "Text"), null);
});

test("the page comes from the admin tab, then Work's view, then Agents' view", () => {
  assert.equal(helpPageFromSearch("?area=admin&tab=users"), "users");
  assert.equal(helpPageFromSearch("?area=work&work_view=intake"), "intake");
  assert.equal(helpPageFromSearch("?area=agents&agents_view=policy"), "policy");
  assert.equal(helpPageFromSearch("?area=chat"), null);
  assert.deepEqual(helpLinkTarget("/chat?area=work&work_view=intake"), { area: "work", tab: null, params: { work_view: "intake" } });
  assert.equal(helpLinkTarget("https://example.org"), null);
});

test("help never opens by itself and has no switch for it", () => {
  const SRC = new URL("../../src/", import.meta.url).pathname;
  const hook = readFileSync(join(SRC, "help/usePageHelp.ts"), "utf8");
  const drawer = readFileSync(join(SRC, "chat/PageHelpDrawer.tsx"), "utf8");
  const shell = readFileSync(join(SRC, "chat/AppContainerView.tsx"), "utf8");
  assert.doesNotMatch(hook, /setTimeout|localStorage|markHelpSeen|shouldAutoOpenHelp/);
  assert.match(hook, /addEventListener\(OPEN_EVENT, show\)/, "only the open event (? button, page Help) opens it");
  assert.doesNotMatch(drawer, /open help automatically|type="checkbox"/);
  assert.match(shell, /usePageHelp\(\)/);
});

test("each Knowledge page shows its own help: Documents is not Search", () => {
  assert.equal(resolveHelpDoc(docs, "knowledge", "knowledgeLibrary").title, "Search");
  assert.equal(resolveHelpDoc(docs, "knowledge", "knowledgeSources").title, "Documents");
  assert.equal(resolveHelpDoc(docs, "knowledge", "knowledgeResearch").title, "Research websites");
  assert.equal(resolveHelpDoc(docs, "knowledge", "workspaceKnowledge").title, "Sources");
  assert.equal(resolveHelpDoc(docs, "knowledge", "knowledgeRelationships").title, "Explore");
});

test("a page switch inside an area is announced, so the open help follows it", () => {
  const events = [];
  const location = new URL("https://octryx.test/chat?area=knowledge&tab=knowledgeLibrary");
  const saved = globalThis.window;
  globalThis.window = {
    get location() { return { href: location.toString(), search: location.search }; },
    history: { state: null, replaceState: (_state, _title, next) => { location.href = next; } },
    dispatchEvent: (event) => events.push(event.type),
  };
  try {
    writeAreaTabToUrl("knowledgeSources");
    assert.equal(helpPageFromSearch(window.location.search), "knowledgeSources");
    assert.deepEqual(events, [AREA_TAB_EVENT]);
    writeAreaTabToUrl("knowledgeSources");
    assert.deepEqual(events, [AREA_TAB_EVENT], "no event when the address stays");
  } finally {
    globalThis.window = saved;
  }
});

test("next steps outside the Setup guide never offer connecting a system: static help cannot know it is done", () => {
  for (const doc of docs) {
    if (doc.area === "setup") continue;
    const next = doc.body.split(/\n### /).find((section) => section.startsWith("Next steps")) ?? "";
    assert.doesNotMatch(next, /- \[(Connect|Upload)\b/, `${doc.area}/${doc.page}`);
  }
});
