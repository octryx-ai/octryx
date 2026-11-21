// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgePhoneNavigation.test.mjs
// Like Chat, Work and Agents, a Knowledge page's narrow layout shows no inline sub-navigation between the page header
// and the page; the page takes the screen.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const CSS = fs.readFileSync(path.resolve(path.dirname(new URL(import.meta.url).pathname),
  "../../src/styles/chat/admin-panel-narrow.css"), "utf8");

test("the narrow Knowledge layout hides the sub-navigation and has no sidebar row", () => {
  const narrow = CSS.slice(CSS.indexOf("@media (max-width: 860px)"));
  assert.match(narrow, /\.admin-panel--knowledge \{\s*grid-template-rows: auto 1fr;\s*grid-template-areas:\s*"header"\s*"body";\s*\}/);
  assert.match(narrow, /\.admin-panel--knowledge \.admin-panel__sidebar \{\s*display: none;\s*\}/);
  const work = fs.readFileSync(path.resolve(path.dirname(new URL(import.meta.url).pathname),
    "../../src/styles/chat/work-area-narrow.css"), "utf8");
  assert.match(work.slice(work.indexOf("@media (max-width: 860px)")), /\.work-area__sidebar \{\s*display: none;/,
    "the same breakpoint and pattern as Work");
});
