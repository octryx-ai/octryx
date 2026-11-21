// Knowledge Search: hits grouped by the system they come from, filters by source, space or project and
// time applied in the browser, the place in words (no revision, offsets or score), and progress instead
// of an empty "Searching…". Fields the server does not send are never guessed.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  activeFacetCount, applyFacets, facetOptions, groupHits, hitPlace, hitSourceUrl, NO_FACETS, openInLabel, originLabel,
} from "../../src/admin/components/workspaceKnowledge/search/searchFacets.ts";
import { searchProgressText, searchTimingText } from "../../src/admin/components/workspaceKnowledge/search/searchProgress.ts";

const NOW = Date.parse("2026-11-06T12:00:00Z");
const hit = (key, extra = {}) => ({
  evidence_key: key, text: `Passage ${key}`, citation: `Doc ${key} (rev 1, chars 0-200)`, source_title: `Doc ${key}`,
  source_url: null, products: [], version: null, kind: null, pages: null, section: null, found_by: [], relevance: null,
  similarity: null, ...extra,
});
const confluence = (key, extra) => hit(key, { origin: { kind: "confluence", url: `https://wiki/${key}` }, container: "TEAM", ...extra });
const jira = (key, extra) => hit(key, { origin: { kind: "jira", url: `https://jira/${key}` }, container: "ORDERS", ...extra });

test("groups keep the ranking: in the order of their best hit, each hit with its rank number", () => {
  const groups = groupHits([confluence("a"), jira("b"), confluence("c"), hit("d", { origin: { kind: "git" } })]);
  assert.deepEqual(groups.map((group) => [group.label, group.hits.map((entry) => [entry.hit.evidence_key, entry.number])]), [
    ["Confluence", [["a", 1], ["c", 3]]],
    ["Jira", [["b", 2]]],
    ["Code", [["d", 4]]],
  ]);
  assert.deepEqual(groupHits([hit("x"), hit("y")], 5).map((group) => [group.label, group.hits.map((entry) => entry.number)]), [["Sources", [5, 6]]],
    "a hit without origin: one group");
  assert.equal(originLabel("service_catalog"), "Service catalog");
});

test("filters offer only what the hits have, with counts, and narrow in the browser", () => {
  const hits = [
    confluence("a", { changed_at: "2026-11-05T10:00:00Z" }),
    jira("b", { changed_at: "2026-10-01T10:00:00Z" }),
    confluence("c", { container: "DOC17", changed_at: null }),
  ];
  const options = facetOptions(hits);
  assert.deepEqual(options.kinds.map((option) => [option.label, option.count]), [["Confluence", 2], ["Jira", 1]]);
  assert.deepEqual(options.containers.map((option) => [option.label, option.count]), [["DOC17", 1], ["ORDERS", 1], ["TEAM", 1]]);
  assert.deepEqual(applyFacets(hits, { ...NO_FACETS, kinds: ["jira"] }, NOW).map((entry) => entry.evidence_key), ["b"]);
  assert.deepEqual(applyFacets(hits, { ...NO_FACETS, containers: ["TEAM", "DOC17"] }, NOW).map((entry) => entry.evidence_key), ["a", "c"]);
  assert.deepEqual(applyFacets(hits, { ...NO_FACETS, within: "7d" }, NOW).map((entry) => entry.evidence_key), ["a"],
    "a hit without a date is kept only under Any time");
  assert.equal(applyFacets(hits, NO_FACETS, NOW).length, 3);
  assert.equal(activeFacetCount({ kinds: ["jira"], containers: [], within: "30d" }), 2);
});

test("facet counts are documents, not passages: two passages of one page count once", () => {
  const hits = [jira("p1", { source_id: "s1" }), jira("p2", { source_id: "s1" }), jira("p3", { source_id: "s2" }), confluence("c1", { source_id: "s3" })];
  const options = facetOptions(hits);
  assert.deepEqual(options.kinds.map((option) => [option.label, option.count]), [["Jira", 2], ["Confluence", 1]]);
  assert.deepEqual(options.containers.map((option) => [option.label, option.count]), [["ORDERS", 2], ["TEAM", 1]]);
});

test("the place is section, pages or lines; never the revision, offsets or a score", () => {
  assert.equal(hitPlace(hit("a", { section: "Doc a > 1. Setup > 1.2 Database", pages: [4, 5] })), "§ 1. Setup > 1.2 Database · pp. 4–5");
  assert.equal(hitPlace(hit("b", { pages: [7, 7] })), "p. 7");
  assert.equal(hitPlace(hit("c", { lines: [758, 759] })), "lines 758–759");
  assert.equal(hitPlace(hit("d")), "");
  assert.equal(openInLabel("confluence"), "Open in Confluence");
  assert.equal(openInLabel("upload"), "Open source");
  assert.equal(openInLabel(""), "Open source");
  assert.equal(hitSourceUrl(confluence("a", { source_url: "https://other" })), "https://wiki/a", "the origin's own link wins");
  assert.equal(hitSourceUrl(hit("e", { source_url: "https://x" })), "https://x");
  assert.equal(hitSourceUrl(hit("f")), null);
});

test("a running search names its progress; after ten seconds it says so", () => {
  assert.equal(searchProgressText(0), "Searching the Workspace's sources…");
  assert.equal(searchProgressText(4), "Searching the Workspace's sources · 4 s");
  assert.match(searchProgressText(12), /^Still searching · 12 s\. This takes longer than usual/);
  assert.equal(searchTimingText({ total: 3200, lexical: 200, vector: 800, rerank: 2100 }),
    "Found in 3.2 s (keywords 0.2 s · meaning 0.8 s · ranking 2.1 s)");
  assert.equal(searchTimingText({ total: 900 }), "Found in 0.9 s");
  assert.equal(searchTimingText(undefined), "");
});

test("the preview reads the server's window: the found passage between the ones before and after it", async () => {
  const { readEvidenceWindow } = await import("../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts");
  assert.deepEqual(readEvidenceWindow({ passages: [
    { evidence_key: "a", text: "before", is_hit: false },
    { evidence_key: "b", text: "found", is_hit: true },
    { evidence_key: "c", text: "after", is_hit: false },
  ] }), { passage: "found", before: ["before"], after: ["after"] });
  assert.equal(readEvidenceWindow({ passages: [{ text: "no hit" }] }), null);
  assert.equal(readEvidenceWindow({}), null, "without a window the hit text stands alone");
});
