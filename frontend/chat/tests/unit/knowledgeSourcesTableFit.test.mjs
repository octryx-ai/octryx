// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeSourcesTableFit.test.mjs
// (kn-sources-1280/1440): the Sources table ran out of the page, State was off-screen and names broke
// inside a word ("confluenc|e-rt-inm"). The table fits: names wrap between words only, a count stays with its noun,
// "Reads" adds nothing to the minimum width and cuts a long address with an ellipsis and a tooltip.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { countParts, nameWords } from "../../src/admin/components/workspaceKnowledge/sources/sourceState.ts";

const DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin/components/workspaceKnowledge/sources");
const CSS = fs.readFileSync(path.join(DIR, "knowledge-sources.css"), "utf8");
const LIST = fs.readFileSync(path.join(DIR, "KnowledgeSourceList.tsx"), "utf8");
const rule = (selector) => CSS.match(new RegExp(`^${selector.replace(/[.>]/g, (c) => `\\${c}`)} \\{[^}]*\\}`, "m"))?.[0] ?? "";

test("a name wraps between its words only, a count stays with its noun", () => {
  assert.deepEqual(nameWords("acme-orders-server-ini (config, 7b338db)"), ["acme-orders-server-ini", "(config,", "7b338db)"]);
  assert.deepEqual(nameWords("confluence-rt-inm"), ["confluence-rt-inm"]);
  assert.deepEqual(countParts("720 articles and records"), ["720 articles", "and", "records"]);
  assert.deepEqual(countParts("282 pages"), ["282 pages"]);
  assert.match(rule(".knowledge-source__nowrap"), /white-space: nowrap;/);
  assert.doesNotMatch(rule(".knowledge-source__name"), /overflow-wrap: anywhere/, "no break inside a word");
});

test("Reads takes the width that is left and cuts a long address with an ellipsis", () => {
  const reads = rule(".knowledge-source__reads");
  assert.match(reads, /width: 0;/);
  assert.match(reads, /min-width: 100%;/);
  const scope = rule(".knowledge-source__scope");
  for (const part of ["overflow: hidden;", "text-overflow: ellipsis;", "white-space: nowrap;", "min-width: 0;"]) assert.ok(scope.includes(part), part);
  assert.match(LIST, /className="knowledge-source__scope" title=\{reads\}/, "the full text in the tooltip");
});

test("no column claims the whole width, Items and Last sync may wrap, State keeps one line", () => {
  assert.doesNotMatch(LIST, /grow: true/);
  assert.match(LIST, /\{ key: "items", header: "Items", align: "end"/);
  assert.match(LIST, /\{ key: "synced", header: "Last sync", render/);
  assert.match(LIST, /\{ key: "state", header: "State", nowrap: true/);
});
