// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/checkboxAndParkedDrawer.test.mjs
// The "Only changes" checkbox sits beside its label, and the parked trace drawer's close button is not focusable while
// aria-hidden. (The pull requests empty-state link is covered in workPullRequestsPilot.)
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const read = (relative) => fs.readFileSync(path.join(SRC, relative), "utf8");
const rule = (css, selector) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`^${escaped} \\{[^}]*\\}`, "m"));
  assert.ok(match, `${selector} exists`);
  return match[0];
};

test("Only changes: the checkbox sits beside its label, over the generic contribution label grid", () => {
  const css = read("chat/knowledge/explore/knowledge-explore.css");
  const checkbox = rule(css, ".knowledge-explore__options .admin-panel__checkbox");
  assert.match(checkbox, /display: inline-flex;/);
  assert.match(checkbox, /align-items: center;/);
  assert.match(read("chat/knowledge/KnowledgeRelationshipsPanel.tsx"), /<label className="admin-panel__checkbox">\s*<input type="checkbox"/);
});

test("the parked trace drawer is hidden, so nothing in it can take focus", () => {
  const css = read("styles/chat/trace-drawer-frame.css");
  const parked = rule(css, ".trace-drawer");
  assert.match(parked, /visibility: hidden;/);
  assert.match(parked, /transition: transform 180ms ease, visibility 0s linear 180ms;/, "hidden only after sliding out");
  assert.match(rule(css, ".trace-drawer--open"), /visibility: visible;/);
});
